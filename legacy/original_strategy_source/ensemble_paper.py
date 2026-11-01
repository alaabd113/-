#!/usr/bin/env python3
"""ماسح المحفظة الورقية الحية — Harper Ensemble v1 (m3-shrunk-mc2).

بقرار علاء 2026-10-20: تشغيل ورقي فقط — دفتر مستقل تماماً
(ensemble_paper_ledger.json) ولا يمس gold_ledger.json ولا أي ماسح آخر.

المكونات (الأوزان من ENSEMBLE_STRATEGY.md):
- EST-longonly ‏(50.6%): منطق est_inst.run_variant (mode=parent, bias, 2R, شراء فقط)
  — مركز كامل، هدف 2R، وقف خلف المستوى + 0.25×ATR، مهلة 48 شمعة 1h، سبريد كلي 0.30$.
- Rectangle & Line ‏(29.9%): منطق 1645487330291351.run() حرفياً (ترند 4H فراكتل
  k=3 + سحب/ارتداد + FVG، دخول عند 50% من FVG الـ15m، وقف عند سوينغ 15m،
  هدف وحيد = السيولة الخارجية) — إدارة w5_common.simulate بوضع 'single'
  (وقف أولاً، ختم 0.60$ سبريد ذهاباً وإياباً، مهلة 1920 شمعة 15m)، وسلسلة
  busy داخل الكاشف كما في المصدر (محاكاة simulate لتحديد شمعة الخروج).
- 6Secrets-FVG ‏(19.5%): منطق 2111121629442174.py حرفياً (FVG بعد سحب سيولة
  بنفس الاتجاه خلال 48 شمعة، لمسة أولى لـ50% ثم كنسها والدخول عند اللمسة
  الثانية) — إدارة w7_lib.Sim: وقف 1×ATR(14)، أهداف 1R/2R/3R بأثلاث،
  تعادل بعد TP1، سبريد 0.15$/جهة على أسعار التنفيذ، مهلة 96 شمعة،
  وحظر دخول جديد 96 شمعة بعد أي دخول (busy_until كما في المصدر).

قاعدة المحفظة (من ensemble_engine): أقصى صفقتين ورقيتين مفتوحتين معاً.
النتيجة المرجحة لكل صفقة = الوزن × R الخام.

الشموع: candle_db.get_candles (الأولوية لـ ctrader الآن) مع سقوط احتياطي
لقراءة القاعدة مباشرة، وشموع مغلقة فقط. حارس السوق: market_hours.
الحالة: ensemble_paper_state.json (watermark لكل مكوّن يبدأ من «الآن»
عند أول تشغيل — لا إشارات رجعية).
"""
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GS = os.path.expanduser("~/workspace/gold-station")
HB = os.path.join(GS, "harper_backtests")
ENS = os.path.join(HB, "ensemble")
for _p in (GS, HB, ENS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from market_hours import require_market_open
from candle_db import get_candles, read as db_read

import est_inst      # ensemble/est_inst.py — منطق EST الأصلي
import w5_common     # harper_backtests/w5_common.py — أدوات Rectangle & Line + simulate
import w7_lib        # harper_backtests/w7_lib.py — أدوات 6Secrets-FVG

TZ = ZoneInfo("Asia/Damascus")
FMT = "%Y-%m-%d %H:%M:%S"
STATE_F = os.path.join(GS, "ensemble_paper_state.json")
LEDGER_F = os.path.join(GS, "ensemble_paper_ledger.json")
OUT_F = os.path.join(GS, "ensemble_paper.json")

WEIGHTS = {"est": 0.506, "rectline": 0.299, "sixsecrets": 0.195}
NAMES = {"est": "EST-longonly", "rectline": "Rectangle & Line",
         "sixsecrets": "6Secrets-FVG"}
TF_OF = {"est": "1h", "rectline": "15min", "sixsecrets": "15min"}
MAX_CONCURRENT = 2
SPREAD_HALF = w7_lib.HALF          # 0.15$/جهة (6Secrets)
RECT_MAX_BARS = 1920               # مهلة Rectangle & Line (شمعات 15m)
SIX_MAX_BARS = 96                  # مهلة 6Secrets (شمعات 15m)


# ---------------------------------------------------------------- أدوات عامة

def now_naive():
    return datetime.now(TZ).replace(tzinfo=None)


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _fallback_read(interval, n):
    for src in ("ctrader", "twelvedata"):
        try:
            rows = db_read(interval=interval, source=src, limit=n)
        except Exception:
            rows = []
        if rows:
            return rows
    return []


PERIOD_MIN = {"15min": 15, "1h": 60, "4h": 240}


def load_closed(interval, n):
    """شموع مغلقة فقط من get_candles (ctrader أولاً) مع سقوط احتياطي للقاعدة."""
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


def close_pos(pos, exit_t, reason, r_raw):
    pos["status"] = "closed"
    pos["exit_t"] = exit_t
    pos["exit_reason"] = reason
    pos["r_raw"] = round(r_raw, 4)
    pos["r_weighted"] = round(pos["weight"] * r_raw, 4)
    return {"strategy": pos["name"], "component": pos["component"],
            "dir": pos["dir_ar"], "entry": pos["entry"], "entry_t": pos["entry_t"],
            "exit_t": exit_t, "exit_reason": reason,
            "r_raw": pos["r_raw"], "r_weighted": pos["r_weighted"]}


# ---------------------------------------------------------------- EST-longonly
# نقل حرفي لمنطق est_inst.run_variant(mode='parent', bias_filter=True,
# tp_mode='2R', long_only=True) — الكشف فقط؛ المحاكاة في step_est.

def detect_est(h1, watermark, cutoff):
    cands = []
    n = len(h1)
    for ai in range(n):
        a = h1[ai]
        if a["t"] < cutoff:
            continue
        dt = datetime.strptime(a["t"], FMT)
        if dt.hour != est_inst.anchor_hour(dt, "parent") or dt.minute != 0:
            continue
        hi, lo = a["h"], a["l"]
        if hi <= lo:
            continue
        a_bull = a["c"] >= a["o"]
        bias = "short" if a_bull else "long"   # عكس اللون [صريح]
        if bias != "long":
            continue  # فلتر التحيز + شراء فقط معاً
        atr = est_inst.atr_at(h1, ai)
        if not atr:
            continue
        sig = None
        for j in range(ai + 1, min(ai + 1 + est_inst.SCAN_AFTER, n)):
            x = h1[j]
            sw_h = x["h"] > hi
            sw_l = x["l"] < lo
            if sw_h and x["c"] <= hi and not (sw_l and x["c"] >= lo):
                sig = ("short", j, hi)
                break
            if sw_l and x["c"] >= lo and not (sw_h and x["c"] <= hi):
                sig = ("long", j, lo)
                break
            if sw_h and sw_l:
                mid = (hi + lo) / 2
                sig = ("short" if x["c"] > mid else "long", j,
                       hi if x["c"] > mid else lo)
                break
            if x["c"] > hi or x["c"] < lo:
                break  # إغلاق خارج النطاق = استمرار — توقف عن البحث
        if not sig:
            continue
        direction, ji, level = sig
        if direction != "long":
            continue
        if h1[ji]["t"] <= watermark:
            continue
        entry = h1[ji]["c"]
        sl = level - est_inst.SL_BUF_ATR * atr
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + 2 * risk
        cands.append({
            "component": "est", "dir_sign": 1, "entry": entry,
            "sl": sl, "tp": tp, "tps": [tp] * 3,
            "risk": risk, "rr": 2.0, "entry_t": h1[ji]["t"],
            "anchor_t": a["t"], "level": level,
            "reason": (f"محفظة ورقية — شمعة 20:00 EST ({a['t'][:10]}) هابطة، "
                       f"كنس قاعها {lo:.2f} مع فشل الإغلاق تحته، دخول شراء "
                       f"{entry:.2f} بهدف 2R كامل (وزن 50.6%)"),
        })
    return cands


def step_est(pos, bars):
    """محاكاة est_inst: وقف أولاً، هدف 2R، مهلة 48 شمعة، سبريد كلي 0.30$."""
    mg = pos["mgmt"]
    for b in bars:
        mg["bars"] += 1
        pos["last_bar_t"] = b["t"]
        gross = reason = None
        if b["l"] <= pos["sl"]:
            gross, reason = -1.0, "sl"
        elif b["h"] >= pos["tp"]:
            gross = abs(pos["tp"] - pos["entry"]) / pos["risk"]
            reason = "tp"
        if gross is None and mg["bars"] >= est_inst.MAX_HOLD:
            gross = round((b["c"] - pos["entry"]) / pos["risk"], 3)
            reason = "timeout"
        if gross is not None:
            net = round(gross - est_inst.SPREAD_TOTAL / pos["risk"], 3)
            return close_pos(pos, b["t"], reason, net)
    return None


# ------------------------------------------------------------ Rectangle & Line
# نقل حرفي لحلقة الكشف في 1645487330291351.run() — الإدارة في step_rectline.

def detect_rectline(h4, m15, watermark, cutoff_h4, busy_until_t):
    K_HTF, K_LTF = 3, 5
    a4 = w5_common.atr_list(h4)
    tm = w5_common.TimeMap(h4, m15)
    cands = []
    busy_bar_t = busy_until_t
    for i in range(40, len(h4) - 1):
        if h4[i]["t"] < cutoff_h4:
            continue
        if busy_bar_t and h4[i]["t"] <= busy_bar_t:
            continue
        if a4[i] is None:
            continue
        for direction in (1, -1):
            highs, lows = w5_common.last_swings(h4, i, K_HTF, n=2)
            if len(highs) < 2 or len(lows) < 2:
                continue
            sh1, sh2 = highs[0], highs[1]
            sl1, sl2 = lows[0], lows[1]
            if direction == 1:
                trend = (h4[sh1]["h"] > h4[sh2]["h"]
                         and h4[sl1]["l"] > h4[sl2]["l"])
            else:
                trend = (h4[sh1]["h"] < h4[sh2]["h"]
                         and h4[sl1]["l"] < h4[sl2]["l"])
            if not trend:
                continue
            target = h4[sh1]["h"] if direction == 1 else h4[sl1]["l"]
            s_idx = f_idx = poi = None
            for s in range(i, max(i - 30, 0), -1):
                hsw_s, lsw_s = w5_common.last_swings(h4, s, K_HTF, n=1)
                if direction == 1:
                    if not lsw_s:
                        continue
                    ref = h4[lsw_s[0]]["l"]
                    swept = h4[s]["l"] < ref and h4[s]["c"] > ref
                else:
                    if not hsw_s:
                        continue
                    ref = h4[hsw_s[0]]["h"]
                    swept = h4[s]["h"] > ref and h4[s]["c"] < ref
                if not swept:
                    continue
                s_idx = s
                for f in range(s + 1, i + 1):
                    fz = (w5_common.fvg_bull(h4, f) if direction == 1
                          else w5_common.fvg_bear(h4, f))
                    if fz:
                        f_idx, poi = f, fz
                        break
                break  # أحدث سحب فقط
            if s_idx is None or poi is None:
                continue
            js = tm.start_of[max(s_idx - 2, 0)]
            if js is None:
                continue
            entry_j = entry = None
            k = js
            end_k = min(js + 400, len(m15))
            while k < end_k and entry_j is None:
                fz = (w5_common.fvg_bull(m15, k) if direction == 1
                      else w5_common.fvg_bear(m15, k))
                if fz:
                    tol = 0.5 * a4[i]
                    aligned = not (fz[1] < poi[0] - tol or fz[0] > poi[1] + tol)
                    if aligned:
                        mid = (fz[0] + fz[1]) / 2
                        for k2 in range(k + 1, min(k + 97, len(m15))):
                            touch = ((m15[k2]["l"] <= mid) if direction == 1
                                     else (m15[k2]["h"] >= mid))
                            if touch:
                                if direction == 1:
                                    sw = None
                                    for q in range(k2 - K_LTF, K_LTF, -1):
                                        if w5_common.is_swing_low(m15, q, K_LTF):
                                            sw = q
                                            break
                                    if sw is None:
                                        break
                                    stop = m15[sw]["l"]
                                    if stop >= mid:
                                        break
                                else:
                                    sw = None
                                    for q in range(k2 - K_LTF, K_LTF, -1):
                                        if w5_common.is_swing_high(m15, q, K_LTF):
                                            sw = q
                                            break
                                    if sw is None:
                                        break
                                    stop = m15[sw]["h"]
                                    if stop <= mid:
                                        break
                                risk = abs(mid - stop)
                                if risk > 3 * a4[i] or risk <= 0:
                                    break
                                entry, entry_j = mid, k2
                                break
                        if entry_j is not None:
                            break
                k += 1
            if entry_j is None:
                continue
            # سلسلة busy كما في المصدر: محاكاة كاملة على النافذة الحالية
            sim = w5_common.simulate(entry, stop, direction, m15, entry_j,
                                     tp_mode="single", tp_price=target,
                                     max_bars=RECT_MAX_BARS)
            if sim is None:
                continue
            busy_bar_t = h4[tm.htf_of_ltf(sim["exit_j"])]["t"]
            if m15[entry_j]["t"] > watermark:
                risk = abs(entry - stop)
                cands.append({
                    "component": "rectline", "dir_sign": direction,
                    "entry": entry, "sl": stop,
                    "tp": target, "tps": [target] * 3,
                    "risk": risk,
                    "rr": round(abs(target - entry) / risk, 2) if risk else 0,
                    "entry_t": m15[entry_j]["t"], "htf_t": h4[i]["t"],
                    "reason": (f"محفظة ورقية — ترند 4H "
                               f"{'صاعد' if direction == 1 else 'هابط'} + سحب "
                               f"سيولة وارتداد + FVG؛ دخول عند 50% من FVG "
                               f"الـ15m عند {entry:.2f}، الهدف سيولة خارجية "
                               f"{target:.2f} (وزن 29.9%)"),
                })
            break  # إشارة واحدة لكل شمعة 4H كحد أقصى
    return cands, busy_bar_t


def step_rectline(pos, bars):
    """محاكاة w5_common.simulate بوضع 'single': وقف أولاً عند تعارض
    الشمعة، ختم سبريد 0.60$ من الناتج، مهلة 1920 شمعة."""
    mg = pos["mgmt"]
    d = pos["dir_sign"]
    for b in bars:
        mg["bars"] += 1
        pos["last_bar_t"] = b["t"]
        hit_stop = (b["l"] <= pos["sl"]) if d == 1 else (b["h"] >= pos["sl"])
        hit_tp = (b["h"] >= pos["tp"]) if d == 1 else (b["l"] <= pos["tp"])
        exit_px = reason = None
        if hit_stop:
            exit_px, reason = pos["sl"], "sl"
        elif hit_tp:
            exit_px, reason = pos["tp"], "tp"
        elif mg["bars"] >= RECT_MAX_BARS:
            exit_px, reason = b["c"], "timeout"
        if exit_px is not None:
            gross = d * (exit_px - pos["entry"])
            net_r = (gross - 2 * w5_common.SPREAD) / pos["risk"]
            return close_pos(pos, b["t"], reason, net_r)
    return None


# --------------------------------------------------------------- 6Secrets-FVG
# نقل حرفي لحلقة 2111121629442174.py — الإدارة في step_six (نظير w7_lib.Sim).

def detect_sixsecrets(m15, watermark, cutoff_fvg, last_entry_t):
    A15 = w7_lib.atr_wilder(m15)
    F15 = w7_lib.detect_fvgs(m15)
    SWEEP_AT = {}
    for k, d in w7_lib.detect_sweeps(m15, A15):
        SWEEP_AT.setdefault(k, []).append(d)
    n = len(m15)
    cands = []
    # busy_until في المصدر عدّاد شمعات (index + 96) لا زمن حائطي — فجوات
    # الويكند/السوق تجعل التحويل الزمني غير مكافئ، فنحمل فهرس آخر دخول.
    idx_by_t = {c["t"]: i for i, c in enumerate(m15)}
    busy_idx = idx_by_t.get(last_entry_t, -1) + SIX_MAX_BARS \
        if last_entry_t else -1
    for f in F15:
        fi = f["idx"]
        if fi < 30 or A15[fi] is None:
            continue
        if m15[fi]["t"] < cutoff_fvg:
            continue
        d = f["dir"]
        # السر 4: FVG بعد سحب سيولة بنفس الاتجاه (خلال 48 شمعة قبلها)
        need = -1 if d == 1 else 1
        if not any(need in SWEEP_AT.get(k, []) for k in range(fi - 48, fi)):
            continue
        mid = f["mid"]
        first_touch_extreme = None
        for j in range(fi + 1, min(n, fi + 49)):
            if j <= busy_idx:
                continue  # مشغول: الشمعة تُتخطى كلياً كما في المصدر
            cj, aj = m15[j], A15[j]
            if aj is None:
                continue
            # إبطال: إغلاق عبر المنطقة
            if (d == 1 and cj["c"] < f["bot"]) or (d == -1 and cj["c"] > f["top"]):
                break
            if first_touch_extreme is None:
                # السر 3+5: أول لمس لـ50% مع إغلاق راجع باتجاه الـFVG
                touch = (d == 1 and cj["l"] <= mid
                         and cj["l"] >= f["bot"] - 0.5 * aj
                         and cj["c"] >= mid) or \
                        (d == -1 and cj["h"] >= mid
                         and cj["h"] <= f["top"] + 0.5 * aj
                         and cj["c"] <= mid)
                if touch:
                    first_touch_extreme = cj["l"] if d == 1 else cj["h"]
            else:
                # كنس اللمسة الأولى ثم إغلاق راجع = دخول (اللمسة الثانية)
                if d == 1:
                    swept = cj["l"] < first_touch_extreme - 0.15 * aj
                    reclaim = cj["c"] > first_touch_extreme
                else:
                    swept = cj["h"] > first_touch_extreme + 0.15 * aj
                    reclaim = cj["c"] < first_touch_extreme
                if swept and reclaim:
                    entry = cj["c"]
                    sl = entry - d * aj
                    tps = [entry + d * kk * aj for kk in (1, 2, 3)]
                    if cj["t"] > watermark:
                        cands.append({
                            "component": "sixsecrets", "dir_sign": d,
                            "entry": entry, "sl": sl,
                            "tp": tps[-1],
                            "tps": list(tps),
                            "risk": abs(entry - sl), "rr": 3.0,
                            "entry_t": cj["t"],
                            "reason": (f"محفظة ورقية — FVG "
                                       f"{'صاعدة' if d == 1 else 'هابطة'} بعد "
                                       f"سحب سيولة؛ لمسة ثانية بعد كنس الأولى، "
                                       f"دخول {entry:.2f} ووقف 1×ATR "
                                       f"(وزن 19.5%)"),
                        })
                    # busy_until = فهرس شمعة الدخول + 96 (كما في المصدر)
                    busy_idx = j + SIX_MAX_BARS
                    last_entry_t = cj["t"]
                    break
    return cands, last_entry_t


def step_six(pos, bars):
    """نظير w7_lib.Sim.trade خطوة بخطوة: وقف أولاً، أثلاث 1R/2R/3R،
    تعادل بعد TP1، أسعار تنفيذ ±0.15$ سبريد، مهلة 96 شمعة."""
    mg = pos["mgmt"]
    d = pos["dir_sign"]
    entry_fill = mg["entry_fill"]
    for b in bars:
        mg["bars"] += 1
        pos["last_bar_t"] = b["t"]
        lo, hi = b["l"], b["h"]
        hit_sl = (lo <= mg["cur_sl"]) if d == 1 else (hi >= mg["cur_sl"])
        tgt = pos["tps"][mg["tp_i"]] if mg["tp_i"] < len(pos["tps"]) else None
        hit_tp = False
        if tgt is not None:
            hit_tp = (hi >= tgt) if d == 1 else (lo <= tgt)
        closed = None
        if hit_sl:  # الوقف أولاً (محافظ)
            fill = mg["cur_sl"] - d * SPREAD_HALF
            mg["pnl"] += d * (fill - entry_fill) * mg["frac"]
            mg["frac"] = 0.0
            closed = "sl" if mg["tp_i"] == 0 else "sl_after_tp"
        elif hit_tp:
            fill = tgt - d * SPREAD_HALF
            if mg["tp_i"] < len(pos["tps"]) - 1:
                part = 1.0 / 3.0
                mg["pnl"] += d * (fill - entry_fill) * part
                mg["frac"] -= part
                if mg["tp_i"] == 0:
                    mg["cur_sl"] = pos["entry"]  # تعادل بعد TP1
                mg["tp_i"] += 1
            else:
                mg["pnl"] += d * (fill - entry_fill) * mg["frac"]
                mg["frac"] = 0.0
                closed = "tp3"
        if closed is None and mg["frac"] > 0 and mg["bars"] >= SIX_MAX_BARS:
            fill = b["c"] - d * SPREAD_HALF
            mg["pnl"] += d * (fill - entry_fill) * mg["frac"]
            mg["frac"] = 0.0
            closed = "timeout"
        if closed is not None:
            return close_pos(pos, b["t"], closed, mg["pnl"] / pos["risk"])
    return None


STEPPERS = {"est": step_est, "rectline": step_rectline, "sixsecrets": step_six}


def make_position(cand, pid):
    # ملاحظة دقة: الأسعار تُحفظ بكامل دقتها دون تقريب — أهداف/وقوف مشتقة من
    # سوينغات تصطدم بحدود الشموع بمساواة حرفية أحياناً (قمة 4216.2071 في
    # باكتست Rectangle & Line)، وأي تقريب لمنزلتين يقلب نتيجة الصفقة.
    comp = cand["component"]
    d = cand["dir_sign"]
    pos = {
        "id": pid, "component": comp, "name": NAMES[comp],
        "strategy": NAMES[comp],
        "dir_sign": d, "dir_ar": "شراء" if d == 1 else "بيع",
        "dir": "شراء" if d == 1 else "بيع",
        "entry": cand["entry"], "sl": cand["sl"], "tp": cand["tp"],
        "tps": cand["tps"], "risk": cand["risk"], "rr": cand["rr"],
        "weight": WEIGHTS[comp], "entry_t": cand["entry_t"],
        "key": f"ENSPAPER|{comp}|{cand['entry_t']}|{cand['entry']}",
        "reason": cand["reason"], "status": "open",
        "exit_t": None, "exit_reason": None, "r_raw": None,
        "r_weighted": None, "last_bar_t": cand["entry_t"],
    }
    if comp == "est":
        pos["mgmt"] = {"kind": "est_full", "bars": 0}
    elif comp == "rectline":
        pos["mgmt"] = {"kind": "rect_single", "bars": 0}
    else:
        pos["mgmt"] = {"kind": "six_thirds", "bars": 0,
                       "entry_fill": cand["entry"] + d * SPREAD_HALF,
                       "cur_sl": cand["sl"], "tp_i": 0, "frac": 1.0,
                       "pnl": 0.0}
    return pos


def signal_view(pos):
    return {"strategy": pos["name"], "component": pos["component"],
            "dir": pos["dir_ar"], "entry": pos["entry"], "sl": pos["sl"],
            "tp1": pos["tps"][0], "tp2": pos["tps"][1], "tp3": pos["tps"][2],
            "rr": pos["rr"], "weight": pos["weight"], "key": pos["key"],
            "t": pos["entry_t"], "reason": pos["reason"], "paper": True}


def paper_stats(ledger):
    trades = ledger.get("trades", [])
    closed = [t for t in trades if t["status"] == "closed"]
    open_ = [t for t in trades if t["status"] == "open"]
    contribs = [t["r_weighted"] for t in closed]
    wins = [c for c in contribs if c > 0]
    gl = -sum(c for c in contribs if c < 0)
    pf = round(sum(wins) / gl, 2) if gl > 0 else None
    return {"closed": len(closed), "open": len(open_),
            "total_weighted_R": round(sum(contribs), 3),
            "total_raw_R": round(sum(t["r_raw"] for t in closed), 3),
            "pf": pf}


# --------------------------------------------------------------------- main

def main():
    require_market_open()
    now_s = now_naive().strftime(FMT)
    state = load_json(STATE_F)
    ledger = load_json(LEDGER_F)
    if ledger is None:
        ledger = {"config": {"weights": WEIGHTS, "max_concurrent": MAX_CONCURRENT,
                             "spread_usd": 0.30, "paper": True},
                  "trades": [], "next_id": 1}

    if state is not None:
        state.pop("six_busy_until", None)  # مفتاح قديم من نسخة التهيئة الأولى

    h1 = load_closed("1h", 400)
    h4 = load_closed("4h", 800)
    m15 = load_closed("15min", 5148)
    latest = {"1h": h1[-1]["t"] if h1 else None,
              "15min": m15[-1]["t"] if m15 else None}

    if state is None:
        # أول تشغيل: الـwatermark من الآن — لا إشارات رجعية إطلاقاً
        state = {"watermarks": {"est": latest["1h"],
                                "rectline": latest["15min"],
                                "sixsecrets": latest["15min"]},
                 "rectline_busy_until": None, "six_last_entry_t": None,
                 "initialized_at": now_s, "last_run": now_s}
        save_json(STATE_F, state)
        save_json(LEDGER_F, ledger)
        out = {"signals": [], "events": [], "stats": paper_stats(ledger),
               "note": "initialized — watermarks set to now, no retro signals",
               "at": now_s}
        save_json(OUT_F, out)
        print(json.dumps(out, ensure_ascii=False))
        print("ENSEMBLE PAPER INIT DONE")
        return

    wm = state["watermarks"]
    bars_by_tf = {"1h": h1, "15min": m15}

    # 1) إدارة الصفقات الورقية المفتوحة على الشموع الجديدة
    events = []
    for pos in ledger["trades"]:
        if pos["status"] != "open":
            continue
        bars = [b for b in bars_by_tf[TF_OF[pos["component"]]]
                if b["t"] > pos["last_bar_t"]]
        if bars:
            ev = STEPPERS[pos["component"]](pos, bars)
            if ev:
                events.append(ev)

    # 2) صيانة busy الخاص بـ Rectangle & Line من الدفتر
    rect_open = any(t["component"] == "rectline" and t["status"] == "open"
                    for t in ledger["trades"])
    rect_busy = state.get("rectline_busy_until")
    if rect_open and h4:
        rect_busy = h4[-1]["t"]  # ما دامت الصفقة مفتوحة: كبت كامل كما في المصدر
    else:
        closed_rect = [t for t in ledger["trades"]
                       if t["component"] == "rectline" and t["status"] == "closed"
                       and t["exit_t"]]
        if closed_rect and h4:
            last_exit = max(t["exit_t"] for t in closed_rect)
            bar = max((b["t"] for b in h4 if b["t"] <= last_exit), default=None)
            if bar and (rect_busy is None or bar > rect_busy):
                rect_busy = bar

    # 3) كشف الإشارات الجديدة منذ الـwatermark
    def cutoff(wm_t, days):
        if not wm_t:
            return ""
        return (datetime.strptime(wm_t, FMT) - timedelta(days=days)).strftime(FMT)

    cands = []
    if latest["1h"]:
        cands += detect_est(h1, wm["est"], cutoff(wm["est"], 2))
    if latest["15min"]:
        rc, rect_busy = detect_rectline(h4, m15, wm["rectline"],
                                        cutoff(wm["rectline"], 12), rect_busy)
        cands += rc
        sc, six_last = detect_sixsecrets(m15, wm["sixsecrets"],
                                         cutoff(wm["sixsecrets"], 1),
                                         state.get("six_last_entry_t"))
        cands += sc
        state["six_last_entry_t"] = six_last
    state["rectline_busy_until"] = rect_busy

    # 4) قبول المحفظة: أقصى صفقتين مفتوحتين معاً (حسب زمن الدخول)
    intervals = [(t["entry_t"], t["exit_t"]) for t in ledger["trades"]]

    def covering(t_s):
        return sum(1 for (e, x) in intervals if e <= t_s and (x is None or x > t_s))

    signals = []
    skipped_cap = 0
    for cand in sorted(cands, key=lambda c: (c["entry_t"], c["component"])):
        if covering(cand["entry_t"]) >= MAX_CONCURRENT:
            skipped_cap += 1
            continue
        pos = make_position(cand, ledger["next_id"])
        ledger["next_id"] += 1
        ledger["trades"].append(pos)
        intervals.append((pos["entry_t"], None))
        signals.append(signal_view(pos))

    # 5) تحديث الـwatermark والحالة والمخرجات
    if latest["1h"]:
        wm["est"] = latest["1h"]
    if latest["15min"]:
        wm["rectline"] = latest["15min"]
        wm["sixsecrets"] = latest["15min"]
    state["last_run"] = now_s
    save_json(STATE_F, state)
    save_json(LEDGER_F, ledger)
    out = {"signals": signals, "events": events, "stats": paper_stats(ledger),
           "skipped_cap": skipped_cap, "at": now_s}
    save_json(OUT_F, out)
    print(json.dumps(out, ensure_ascii=False))
    print("ENSEMBLE PAPER DONE")


if __name__ == "__main__":
    main()
