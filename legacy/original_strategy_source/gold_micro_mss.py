#!/usr/bin/env python3
"""ماسح حي — «السحب والكسر الجزئي — Micro MSS» (MICRO_MSS_GOLD).

بقرار علاء 2026-10-25 (تصحيح صريح لخطة التشغيل الظلّي): تشغيل نظامي
حي على محرك الذهب اعتباراً من افتتاح السوق الاثنين 2026-10-26 —
الإشارة تُسجَّل في الدفتر الحقيقي (gold_ledger) فتنعكس تلقائياً على
حساب الديمو عبر منفّذ المرايا، وتصل بطاقتها إلى المحادثة وتيليجرام
(المساعد الرئيسي هو المرسل الوحيد — هذا السكربت لا يرسل شيئاً).

القواعد المجمدة (من اختبار GOLD V4 المستقل على شموعنا، 2026-10-25):
- الإشارة: v4_micro_mss حرفياً من gold_v4_research — سحب سيولة لقمة/قاع
  متأرجح (نافذة 3) وإغلاق عودة، ثم تأكيد بكسر بنية محلية (أعلى/أدنى
  مستوى في الشموع الأربع السابقة للسحب) بإغلاق اتجاهي خلال 4 شموع،
  وانتهاء صلاحية الإعداد بعد 6 شموع. فريم 15 دقيقة.
- الوقف: خلف طرف السحب + 0.15×ATR(14) كما يبنيه المحرك.
- سقف مسافة الوقف: أقل من 15$ بصرامة (قاعدة علاء 2026-10-24؛ والصرامة
  دون 15 تمنع أيضاً تفعيل الوقف المتحرك واسع الوقف على المرآة).
  الأوسع يُسجَّل في سجل الظل (shadow_signals.jsonl) ويُتخطى بصمت.
- صفقة مفتوحة واحدة للاستراتيجية في كل مرة (كما في محاكاة البحث).
- إدارة الخروج بالتأمين (mgmt="be_only" في الدفتر): مركز كامل بلا
  إغلاق جزئي؛ الهدف ‎+2R؛ عند بلوغ ‎+1R ينتقل الوقف إلى الدخول
  (be_trigger_r=1.0 — الدفتر يسلّحه من الشمعة التالية، ومنفّذ المرايا
  ينقله حياً على الحساب عند بلوغ ‎+1R بالسعر المباشر).
- حارس حداثة freshness بوضع market، وحارس سوق market_hours.
- الشموع من القاعدة المحلية فقط (ctrader أولاً) — صفر طلبات API.
- أول تشغيل: العلامة المائية تبدأ من آخر شمعة مغلقة — لا إشارات رجعية.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GS = os.path.expanduser("~/workspace/gold-station")
if GS not in sys.path:
    sys.path.insert(0, GS)

from market_hours import require_market_open
from candle_db import get_candles, read as db_read
from freshness import live_price, stale_reason
from gold_ledger import load as ledger_load, shadow_append

import pandas as pd
from gold_strategy import Settings, features
from gold_v4_research import make_v4_signals

TZ = ZoneInfo("Asia/Damascus")
FMT = "%Y-%m-%d %H:%M:%S"
STATE_F = os.path.join(GS, "gold_micro_mss_state.json")
OUT_F = os.path.join(GS, "gold_micro_mss.json")

CODE = "MICRO_MSS_GOLD"
NAME_AR = "السحب والكسر الجزئي — Micro MSS"
VARIANT = "v4_micro_mss"
MAX_STOP_USD = 15.0
BARS_15M = 1500
PERIOD_MIN = {"15min": 15, "1min": 1}
CFG = Settings()


def now_naive():
    return datetime.now(TZ).replace(tzinfo=None)


def save_json(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _fallback_read(interval, n):
    for src in ("ctrader", "twelvedata"):
        try:
            rows = db_read(interval=interval, source=src, limit=n)
        except Exception:
            rows = []
        if rows:
            return rows
    return []


def load_closed(interval, n):
    """شموع مغلقة فقط من القاعدة المحلية (ctrader أولاً)."""
    try:
        cs = get_candles(interval, n, live=lambda: _fallback_read(interval, n))
    except Exception:
        cs = _fallback_read(interval, n)
    now = now_naive()
    step = timedelta(minutes=PERIOD_MIN[interval])
    out, seen = [], set()
    for c in cs or []:
        if c["t"] in seen:
            continue
        t = datetime.strptime(c["t"], FMT)
        if t + step <= now:
            seen.add(c["t"])
            out.append({"t": c["t"], "o": float(c["o"]), "h": float(c["h"]),
                        "l": float(c["l"]), "c": float(c["c"])})
    out.sort(key=lambda x: x["t"])
    return out


def build_signal_frame(m15):
    """تحويل شموع القاعدة (توقيت دمشق) إلى إطار المحرك (UTC) كما في البحث."""
    df = pd.DataFrame({
        "time": pd.to_datetime([c["t"] for c in m15]) - pd.Timedelta(hours=3),
        "open": [c["o"] for c in m15],
        "high": [c["h"] for c in m15],
        "low": [c["l"] for c in m15],
        "close": [c["c"] for c in m15],
        "spread_price": 0.2,
    })
    df["time"] = df["time"].dt.tz_localize("UTC")
    return df


def latest_signal(m15):
    """إشارة آخر شمعة مغلقة أو None. يُرجع dict بوقت الشمعة بتوقيت دمشق."""
    if len(m15) < 200:
        return None
    df = build_signal_frame(m15)
    f = features(df, CFG)
    x = make_v4_signals(f, CFG, VARIANT)
    last = x.iloc[-1]
    bar_t_damascus = (last["time"] + pd.Timedelta(hours=3)).strftime(FMT)
    if int(last["signal"]) == 0:
        return {"bar_t": bar_t_damascus, "signal": 0}
    return {"bar_t": bar_t_damascus, "signal": int(last["signal"]),
            "stop": float(last["stop"]), "close": float(last["close"]),
            "reason": str(last.get("reason", "SWEEP+INTERNAL_BREAK"))}


def reason_ar(d):
    if d == 1:
        return ("سحب سيولة لقاع متأرجح ثم إغلاق عودة داخل النطاق، وتأكيد "
                "بكسر بنية محلية صاعدة (Micro MSS) خلال 4 شموع من السحب — "
                "الدخول مع الكسر والوقف خلف طرف السحب")
    return ("سحب سيولة لقمة متأرجحة ثم إغلاق عودة داخل النطاق، وتأكيد "
            "بكسر بنية محلية هابطة (Micro MSS) خلال 4 شموع من السحب — "
            "الدخول مع الكسر والوقف خلف طرف السحب")


def main():
    require_market_open()
    now = now_naive()
    state = load_json(STATE_F)
    out = {"signals": [], "skipped": [], "run_at": now.strftime(FMT)}

    m15 = load_closed("15min", BARS_15M)
    if not m15:
        save_json(out, OUT_F)
        return
    sig = latest_signal(m15)
    if sig is None:
        save_json(out, OUT_F)
        return

    if state is None:
        # أول تشغيل: العلامة تبدأ من آخر شمعة مغلقة — لا إشارات رجعية أبداً.
        state = {"started_at": now.strftime(FMT), "watermark": sig["bar_t"],
                 "counts": {"emitted": 0, "cap": 0, "stale": 0, "open_busy": 0}}
        save_json(state, STATE_F)
        save_json(out, OUT_F)
        return

    if sig["signal"] != 0 and sig["bar_t"] > (state.get("watermark") or ""):
        state["watermark"] = sig["bar_t"]
        d = sig["signal"]
        dir_ar = "شراء" if d == 1 else "بيع"
        stop = float(sig["stop"])
        ref_entry = float(sig["close"])
        risk_ref = abs(ref_entry - stop)
        target_ref = ref_entry + d * 2 * risk_ref

        ledger = ledger_load()
        trades = ledger.get("trades", [])
        dup = any(t.get("strategy") == CODE and sig["bar_t"] in (t.get("note") or "")
                  for t in trades)
        busy = any(t.get("strategy") == CODE and t.get("status") == "open"
                   for t in trades)
        if dup:
            out["skipped"].append({"type": "duplicate", "bar_t": sig["bar_t"],
                                   "dir": dir_ar})
        elif busy:
            state["counts"]["open_busy"] += 1
            out["skipped"].append({"type": "open_busy", "bar_t": sig["bar_t"],
                                   "dir": dir_ar})
        else:
            live = live_price()
            entry = float(live) if live else ref_entry
            stale = stale_reason({"entry": ref_entry, "sl": stop,
                                  "tp1": target_ref, "dir": dir_ar},
                                 live, mode="market")
            risk = (entry - stop) * d
            if stale:
                state["counts"]["stale"] += 1
                out["skipped"].append({"type": "stale", "bar_t": sig["bar_t"],
                                       "dir": dir_ar, "reason": stale})
            elif risk <= 0 or risk >= MAX_STOP_USD:
                state["counts"]["cap"] += 1
                shadow_append({
                    "reason": "risk_cap", "strategy": CODE, "dir": dir_ar,
                    "entry": round(entry, 2), "sl": round(stop, 2),
                    "tp1": round(entry + d * 2 * risk, 2),
                    "risk_usd": round(abs(risk), 2),
                    "note": f"Micro MSS — شمعة الإشارة {sig['bar_t']}"})
                out["skipped"].append({"type": "cap", "bar_t": sig["bar_t"],
                                       "dir": dir_ar, "risk": round(risk, 2)})
            else:
                target = entry + d * 2 * risk
                state["counts"]["emitted"] += 1
                out["signals"].append({
                    "key": f"{CODE}|{sig['bar_t']}|{dir_ar}",
                    "strategy": CODE, "name_ar": NAME_AR,
                    "dir": dir_ar, "dir_sign": d,
                    "entry": round(entry, 2), "sl": round(stop, 2),
                    "tp1": round(target, 2), "tp2": round(target, 2),
                    "tp3": round(target, 2), "target": round(target, 2),
                    "rr": 2.0, "risk_usd": round(risk, 2),
                    "be_trigger_r": 1.0, "be_level": round(entry, 2),
                    "mgmt": "be_only",
                    "t": now.strftime(FMT), "signal_bar_t": sig["bar_t"],
                    "reason": reason_ar(d),
                    "note": (f"{reason_ar(d)} · تأمين عند +1R وهدف +2R · "
                             f"شمعة الإشارة {sig['bar_t']}"),
                })

    save_json(state, STATE_F)
    save_json(out, OUT_F)


if __name__ == "__main__":
    main()
