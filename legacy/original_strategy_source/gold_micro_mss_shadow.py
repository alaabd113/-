#!/usr/bin/env python3
"""ماسح ظلّي أمامي — «السحب والكسر الجزئي — Micro MSS» (MICRO_MSS_GOLD).

بقرار علاء 2026-10-25 (تطبيقاً لاقتراح إدارة الخروج بالتأمين):
تشغيل ظلّي/ورقي فقط على محرك الذهب — دفتر ظلّي مستقل تماماً
(gold_micro_mss_shadow_ledger.json) ولا يمسّ gold_ledger.json ولا منفّذ
المرايا ولا أي ماسح آخر، ولا يرسل إلى تيليجرام (البطاقات في المحادثة فقط).

القواعد المجمدة (من اختبار GOLD V4 على شموعنا، 2026-10-25):
- الإشارة: v4_micro_mss حرفياً من gold_v4_research — سحب سيولة لقمة/قاع
  متأرجح (نافذة 3) وإغلاق عودة، ثم تأكيد بكسر بنية محلية (أعلى/أدنى
  مستوى في الشموع الأربع السابقة للسحب) بإغلاق اتجاهي خلال 4 شموع،
  وانتهاء صلاحية الإعداد بعد 6 شموع. فريم 15 دقيقة.
- الوقف: خلف طرف السحب + 0.15×ATR(14) كما يبنيه المحرك.
- سقف مسافة الوقف: 15$ (قاعدة علاء الحالية) — الأوسع يُرفض ويُسجَّل.
- مركز ظلّي واحد في كل مرة (كما في محاكاة البحث).
- إدارة الخروج بالتأمين: الهدف +2R. عند بلوغ +1R يُسلَّح التأمين
  ويصبح الوقف = الدخول فعّالاً من شمعة الدقيقة التالية (كقاعدة الدفتر)،
  فإما الهدف +2R أو الخروج عند التعادل 0R بدل -1R.
- تقييم الخروج على شموع دقيقة مغلقة، والوقف أولاً داخل الشمعة.
- R هنا سعري إجمالي قبل تكاليف التنفيذ التقديرية (نحو 0.02–0.03R للصفقة
  في محاكاة البحث) — اختبار جودة إشارة أمامي، لا محاكاة حساب كاملة
  (لا حد خسارة يومياً ولا إعادة قياس حجم).
- حارس حداثة freshness بوضع market، وحارس سوق market_hours.
- الشموع من القاعدة المحلية فقط (ctrader أولاً) — صفر طلبات API.
- معايير الحكم المكتوبة سلفاً: 4–6 أسابيع و40 صفقة مغلقة على الأقل،
  متوسط >= +0.10R وPF >= 1.15 ونتيجة موجبة في النصف الثاني أيضاً.
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

import pandas as pd
from gold_strategy import Settings, features
from gold_v4_research import make_v4_signals

TZ = ZoneInfo("Asia/Damascus")
FMT = "%Y-%m-%d %H:%M:%S"
STATE_F = os.path.join(GS, "gold_micro_mss_shadow_state.json")
LEDGER_F = os.path.join(GS, "gold_micro_mss_shadow_ledger.json")
OUT_F = os.path.join(GS, "gold_micro_mss_shadow.json")

CODE = "MICRO_MSS_GOLD"
NAME_AR = "السحب والكسر الجزئي — Micro MSS"
VARIANT = "v4_micro_mss"
MAX_STOP_USD = 15.0
BARS_15M = 1500
HOLD_LIMIT = timedelta(days=7)
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


def eval_position(pos, m1_bars, now):
    """تقييم مركز مفتوح على شموع دقيقة مغلقة مرتبة تصاعدياً.

    يُرجع (pos محدّث, closed_trade أو None, events).
    التأمين يُسلَّح عند لمس +1R ويصبح فعّالاً من الشمعة التالية.
    الوقف أولاً داخل الشمعة.
    """
    events = []
    d = 1 if pos["dir"] == "شراء" else -1
    entry, risk = float(pos["entry"]), float(pos["risk"])
    target, stop0 = float(pos["target"]), float(pos["stop"])
    be_level = entry + d * risk
    closed = None
    for bar in m1_bars:
        if bar["t"] < pos["entry_t"] or bar["t"] <= (pos.get("last_eval") or ""):
            continue
        pos["last_eval"] = bar["t"]
        if pos.get("be_pending") and not pos.get("be_active"):
            pos["be_active"] = True
            pos["be_pending"] = False
            events.append({"type": "be", "id": pos["id"], "dir": pos["dir"],
                           "entry": entry, "t": bar["t"]})
        eff_stop = entry if pos.get("be_active") else stop0
        fav = ((bar["h"] - entry) if d == 1 else (entry - bar["l"])) / risk
        adv = ((entry - bar["l"]) if d == 1 else (bar["h"] - entry)) / risk
        pos["mfe_r"] = round(max(float(pos.get("mfe_r", 0.0)), fav), 4)
        pos["mae_r"] = round(min(float(pos.get("mae_r", 0.0)), -adv), 4)
        stop_hit = (bar["l"] <= eff_stop) if d == 1 else (bar["h"] >= eff_stop)
        tgt_hit = (bar["h"] >= target) if d == 1 else (bar["l"] <= target)
        if stop_hit:
            closed = dict(pos)
            closed.update({"status": "closed", "exit_t": bar["t"],
                           "exit": eff_stop,
                           "exit_reason": "BE" if pos.get("be_active") else "STOP",
                           "r_multiple": 0.0 if pos.get("be_active") else -1.0})
            break
        if tgt_hit:
            closed = dict(pos)
            closed.update({"status": "closed", "exit_t": bar["t"],
                           "exit": target, "exit_reason": "TARGET",
                           "r_multiple": 2.0})
            break
        if not pos.get("be_active") and not pos.get("be_pending"):
            if fav >= 1.0:
                pos["be_pending"] = True
    if closed is None and m1_bars:
        entry_dt = datetime.strptime(pos["entry_t"], FMT)
        if now - entry_dt > HOLD_LIMIT:
            last = m1_bars[-1]
            closed = dict(pos)
            r = (float(last["c"]) - entry) * d / risk
            closed.update({"status": "closed", "exit_t": last["t"],
                           "exit": float(last["c"]), "exit_reason": "TIMEOUT",
                           "r_multiple": round(r, 4)})
    return pos, closed, events


def compute_stats(ledger):
    trades = ledger.get("trades", [])
    rs = [float(t["r_multiple"]) for t in trades]
    gp = sum(r for r in rs if r > 0)
    gl = -sum(r for r in rs if r < 0)
    return {"closed": len(trades),
            "wins": sum(1 for r in rs if r > 0),
            "total_r": round(sum(rs), 3),
            "avg_r": round(sum(rs) / len(rs), 4) if rs else None,
            "pf": round(gp / gl, 3) if gl > 0 else None}


def main():
    require_market_open()
    now = now_naive()
    state = load_json(STATE_F)
    ledger = load_json(LEDGER_F, {"trades": []}) or {"trades": []}
    out = {"signals": [], "events": [], "skipped": [],
           "run_at": now.strftime(FMT)}

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
                 "open": None, "next_id": 1,
                 "counts": {"opened": 0, "cap": 0, "stale": 0, "open_busy": 0}}
        save_json(state, STATE_F)
        out["stats"] = compute_stats(ledger)
        out["open"] = None
        save_json(out, OUT_F)
        return

    # ١) تقييم المركز المفتوح أولاً
    pos = state.get("open")
    if pos:
        need = int((now - datetime.strptime(pos["entry_t"], FMT)).total_seconds() // 60) + 120
        m1 = load_closed("1min", max(600, min(need, 12000)))
        pos, closed, events = eval_position(pos, m1, now)
        out["events"].extend(events)
        if closed:
            ledger.setdefault("trades", []).append(closed)
            save_json(ledger, LEDGER_F)
            out["events"].append({"type": "close", "id": closed["id"],
                                  "dir": closed["dir"], "entry": closed["entry"],
                                  "exit": closed["exit"],
                                  "exit_reason": closed["exit_reason"],
                                  "r_multiple": closed["r_multiple"],
                                  "entry_t": closed["entry_t"],
                                  "exit_t": closed["exit_t"],
                                  "mfe_r": closed.get("mfe_r")})
            state["open"] = None
        else:
            state["open"] = pos

    # ٢) إشارة جديدة على آخر شمعة مغلقة
    if sig["signal"] != 0 and sig["bar_t"] > (state.get("watermark") or ""):
        state["watermark"] = sig["bar_t"]
        d = sig["signal"]
        dir_ar = "شراء" if d == 1 else "بيع"
        stop = sig["stop"]
        ref_entry = sig["close"]
        risk_ref = abs(ref_entry - stop)
        target_ref = ref_entry + d * 2 * risk_ref
        if state.get("open"):
            state["counts"]["open_busy"] += 1
            out["skipped"].append({"type": "open_busy", "bar_t": sig["bar_t"],
                                   "dir": dir_ar})
        else:
            live = live_price()
            entry = float(live) if live else float(ref_entry)
            stale = stale_reason({"entry": ref_entry, "sl": stop,
                                  "tp1": target_ref, "dir": dir_ar},
                                 live, mode="market")
            risk = (entry - stop) * d
            if stale:
                state["counts"]["stale"] += 1
                out["skipped"].append({"type": "stale", "bar_t": sig["bar_t"],
                                       "dir": dir_ar, "reason": stale})
            elif risk <= 0 or risk > MAX_STOP_USD:
                state["counts"]["cap"] += 1
                out["skipped"].append({"type": "cap", "bar_t": sig["bar_t"],
                                       "dir": dir_ar, "risk": round(risk, 2)})
            else:
                pid = state["next_id"]
                state["next_id"] = pid + 1
                state["counts"]["opened"] += 1
                new_pos = {"id": pid, "strategy": CODE, "dir": dir_ar,
                           "dir_sign": d, "entry": round(entry, 2),
                           "stop": round(stop, 2),
                           "target": round(entry + d * 2 * risk, 2),
                           "risk": round(risk, 4),
                           "entry_t": now.strftime(FMT),
                           "signal_bar_t": sig["bar_t"],
                           "reason": sig["reason"],
                           "be_active": False, "be_pending": False,
                           "last_eval": None, "mfe_r": 0.0, "mae_r": 0.0,
                           "status": "open"}
                state["open"] = new_pos
                out["signals"].append(dict(new_pos))

    save_json(state, STATE_F)
    out["stats"] = compute_stats(ledger)
    out["open"] = state.get("open")
    save_json(out, OUT_F)


if __name__ == "__main__":
    main()
