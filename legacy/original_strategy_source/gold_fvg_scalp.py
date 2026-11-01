#!/usr/bin/env python3
"""سكالبينج FVG للذهب — 15M سياق + 1M دخول (استراتيجية فهد عزت).

مرحلة 1: سكانر فقط — لا كرون، لا دفتر، لا تيليجرام.
يقرأ 15min و1min من candle_db، ويخرج gold_fvg_scalp.json + gold_fvg_scalp.png.

القرارات الكمية الثابتة (ليست من الفيديو حرفياً — موثقة في assumptions كل إشارة):
  A1. FVG صاعدة: low[i] > high[i-2] → منطقة [high[i-2], low[i]].
  A2. Order Block صاعد: آخر شمعة هابطة قبل شمعة إزاحة صاعدة
      (إزاحة = جسم > 50% من المدى) → المنطقة = [low, high] تلك الشمعة.
  A3. «غير مستهلكة»: لا إغلاق تجاوز المنطقة منذ تشكلها
      (صاعدة: لا close تحت القاع / هابطة: لا close فوق القمة).
  A4. «ارتدت المنطقة» (15M): شمعة ذيلها دخل المنطقة (low < قمة المنطقة)
      وأغلقت فوق قمتها — مرة واحدة على الأقل.
  A5. «شمعة قوية»: جسم > 50% من مدى الشمعة.
  A6. القرب من المنطقة: |السعر - المنطقة| <= 0.3×ATR15.
  A7. الدخول عند قاع الفجوة - سبريد 0.30$؛ إشارة قديمة تُرفض إذا
      السعر الحالي > الدخول + 0.5×المخاطرة.
  A8. الوقف = أدنى low لشموع الفجوة الثلاث؛ يُرفض إذا المخاطرة < 1.0$.
  A9. الهدف النهائي = أبعد OB معاكس غير مستهلك على 15M ضمن 8×ATR15
      («لآخر حاجة فوق» per الفيديو)؛ يُرفض إذا المسافة < 2×المخاطرة أو غاب.
  A10. TP1 = أول OB وسيط بين الدخول والهدف النهائي (إن كان >= 1R)
      + إغلاق 50% ونقل الوقف للتعادل عنده.
  A11. البيع مرآة الشراء (مستنتج — الفيديو شرح الشراء فقط).
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_hours import require_market_open
from candle_db import read

OUT = os.path.dirname(os.path.abspath(__file__))
STATE_F = os.path.join(OUT, "fvg_scalp_state.json")
JSON_F = os.path.join(OUT, "gold_fvg_scalp.json")
PNG_F = os.path.join(OUT, "gold_fvg_scalp.png")
TZ = ZoneInfo("Asia/Damascus")

STRAT = "سكالبينج FVG — 15M+1M"
SPREAD = 0.30          # A7
MIN_RISK = 1.0         # A8 ($)
PROX_K = 0.3           # A6
STALE_K = 0.5          # A7
MIN_TP_RR = 2.0        # A9
BODY_PCT = 0.50        # A2/A5
ATR_P = 14


def atr(candles, period=ATR_P):
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def find_fvgs(c):
    """A1 — قائمة FVGs: dict(i, dir, top, bot, t)."""
    out = []
    for i in range(2, len(c)):
        a, b, d = c[i - 2], c[i - 1], c[i]
        if d["l"] > a["h"]:
            out.append({"i": i, "dir": "buy", "top": d["l"], "bot": a["h"], "t": d["t"]})
        elif d["h"] < a["l"]:
            out.append({"i": i, "dir": "sell", "top": a["l"], "bot": d["h"], "t": d["t"]})
    return out


def _body_pct(k):
    rng = k["h"] - k["l"]
    return abs(k["c"] - k["o"]) / rng if rng > 0 else 0.0


def find_obs(c):
    """A2 — Order Blocks من شموع الإزاحة."""
    out = []
    for i in range(1, len(c)):
        k = c[i]
        if _body_pct(k) <= BODY_PCT:
            continue
        prev = c[i - 1]
        if k["c"] > k["o"] and prev["c"] < prev["o"]:      # إزاحة صاعدة
            out.append({"i": i, "dir": "buy", "top": prev["h"], "bot": prev["l"],
                        "t": k["t"]})
        elif k["c"] < k["o"] and prev["c"] > prev["o"]:    # إزاحة هابطة
            out.append({"i": i, "dir": "sell", "top": prev["h"], "bot": prev["l"],
                        "t": k["t"]})
    return out


def unmitigated(c, zone, up_to):
    """A3 — لم يُستهلك حتى الشمعة up_to (غير شاملة)."""
    lo, hi = (zone["i"] + 1), up_to
    for k in c[lo:hi]:
        if zone["dir"] == "buy" and k["c"] < zone["bot"]:
            return False
        if zone["dir"] == "sell" and k["c"] > zone["top"]:
            return False
    return True


def bounced(c, zone, up_to):
    """A4 — ارتداد واحد على الأقل بعد التشكل."""
    for k in c[zone["i"] + 1:up_to]:
        if zone["dir"] == "buy" and k["l"] < zone["top"] and k["c"] > zone["top"]:
            return True
        if zone["dir"] == "sell" and k["h"] > zone["bot"] and k["c"] < zone["bot"]:
            return True
    return False


def near_zone(price, zone, atr15):
    """A6."""
    if price > zone["top"]:
        return (price - zone["top"]) <= PROX_K * atr15
    if price < zone["bot"]:
        return (zone["bot"] - price) <= PROX_K * atr15
    return True


def scan(m15, m1):
    """يفحص أحدث حالة ويرجع قائمة إشارات (0 أو 1 لكل اتجاه)."""
    signals = []
    if len(m15) < 60 or len(m1) < 60:
        return signals
    a15 = atr(m15)
    if a15 <= 0:
        return signals
    price = m1[-1]["c"]
    n15, n1 = len(m15), len(m1)

    obs15 = find_obs(m15)
    fvgs1 = find_fvgs(m1)

    for side in ("buy", "sell"):
        sgn = 1 if side == "buy" else -1
        # --- منطقة 15M مؤهلة: الأحدث غير المستهلكة والمرتدة ---
        zones = [z for z in obs15
                 if z["dir"] == side
                 and unmitigated(m15, z, n15)
                 and bounced(m15, z, n15)]
        if not zones:
            continue
        zone = zones[-1]
        if not near_zone(price, zone, a15):
            continue
        # --- FVGs غير مستهلكة على 1m خلال آخر 20 شمعة (لا الأحدث فقط —
        # وإلا حجبت FVG أحدث غير مؤهلة إشارةً صالحة سبقتها بدقائق) ---
        fvgs = [f for f in fvgs1
                if f["dir"] == side and unmitigated(m1, f, n1)
                and (n1 - 1 - f["i"]) <= 20]
        for f in fvgs:
            fc = m1[f["i"] - 2:f["i"] + 1]
            if side == "buy":
                entry = f["bot"] - SPREAD
                sl = min(k["l"] for k in fc)
            else:
                entry = f["top"] + SPREAD
                sl = max(k["h"] for k in fc)
            risk = sgn * (entry - sl)
            if risk < MIN_RISK:
                continue
            if sgn * (price - entry) > STALE_K * risk:   # A7 إشارة قديمة
                continue
        # --- الهدف: أبعد OB معاكس غير مستهلك ضمن 8×ATR15 (A9 معدّلة) ---
        # الفيديو: «الهدف لآخر حاجة فوق» والبلوكات الوسيطة = TP1/TP2 مرحلية
            opp = "sell" if side == "buy" else "buy"
            cands = []
            for z in obs15:
                if z["dir"] != opp or not unmitigated(m15, z, n15):
                    continue
                lv = z["bot"] if side == "buy" else z["top"]
                d = sgn * (lv - entry)
                if 0 < d <= 8 * a15:
                    cands.append((d, lv))
            if not cands:
                continue
            cands.sort(key=lambda x: x[0])
            tp2 = cands[-1][1]                       # الأبعد
            if sgn * (tp2 - entry) < MIN_TP_RR * risk:
                continue
            # --- TP1: أول OB وسيط بين الدخول والهدف (A10) ---
            tp1 = None
            for d, lv in cands[:-1]:
                if sgn * (lv - entry) >= risk:      # >= 1R
                    tp1 = lv
                    break
            rr = sgn * (tp2 - entry) / risk
            key = f"FVG-SCALP|{side}|{f['t']}|{entry:.1f}"
            reason = (f"منطقة 15M مرتدة {'صاعدة' if side=='buy' else 'هابطة'} عند "
                      f"{zone['bot']:.1f}-{zone['top']:.1f} + FVG {'صاعدة' if side=='buy' else 'هابطة'} "
                      f"غير مستهلكة على 1m — دخول {'شراء' if side=='buy' else 'بيع'} عند حافة الفجوة")
            signals.append({
                "strategy": STRAT,
                "dir": "شراء" if side == "buy" else "بيع",
                "entry": round(entry, 2), "sl": round(sl, 2),
                "tp": round(tp2, 2), "tp1": round(tp1, 2) if tp1 else None,
                "tp2": round(tp2, 2), "rr": round(rr, 2),
                "risk": round(risk, 2),
                "key": key, "t": m1[-1]["t"],
                "reason": reason,
                "zone15": {"dir": side, "bot": round(zone["bot"], 2),
                           "top": round(zone["top"], 2), "t": zone["t"]},
                "assumptions": ("A1-A11: FVG=[high[i-2],low[i]]؛ OB=آخر شمعة عكسية قبل إزاحة "
                                "(جسم>50%)؛ غير مستهلكة=لا إغلاق متجاوز؛ ارتداد=ذيل دخل المنطقة "
                                "وأغلق خارجها؛ قرب<=0.3×ATR15؛ دخول=حافة الفجوة∓سبريد 0.30$؛ "
                                "وقف=ذيل شموع الفجوة (≥1$)؛ هدف=أبعد OB معاكس ضمن 8×ATR15 (≥2R)؛ "
                                "TP1=أول OB وسيط (≥1R) + إغلاق 50% وتعادل؛ "
                                "البيع مرآة الشراء (مستنتج)"),
            })
    return signals


def load_state():
    try:
        with open(STATE_F) as f:
            return json.load(f)
    except Exception:
        return {"alerted_keys": []}


def save_state(st):
    st["alerted_keys"] = st["alerted_keys"][-50:]
    with open(STATE_F, "w") as f:
        json.dump(st, f, ensure_ascii=False)


def draw(m15, m1, signals):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    BG, FG, GRID = "#0d1117", "white", "#30363d"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6), facecolor=BG)
    for ax, data, name in ((ax1, m15[-120:], "XAUUSD 15M"), (ax2, m1[-160:], "XAUUSD 1M")):
        ax.set_facecolor(BG)
        xs = list(range(len(data)))
        up = [k["c"] >= k["o"] for k in data]
        for i, k in enumerate(data):
            col = "#26a69a" if up[i] else "#ef5350"
            ax.plot([i, i], [k["l"], k["h"]], color=col, linewidth=0.9)
            ax.plot([i - 0.35, i + 0.35], [k["o"], k["o"]], color=col, linewidth=0.9)
            ax.plot([i - 0.35, i + 0.35], [k["c"], k["c"]], color=col, linewidth=0.9)
        ax.set_title(name, color=FG, fontsize=11, weight="bold")
        ax.tick_params(colors="#8b949e", labelsize=7)
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.grid(color=GRID, alpha=0.3, linewidth=0.5)
    # مناطق وإشارات
    for s in signals:
        z = s["zone15"]
        for ax, data in ((ax1, m15[-120:]), (ax2, m1[-160:])):
            ax.add_patch(Rectangle((0, z["bot"]), len(data), z["top"] - z["bot"],
                                   color="#d2a8ff", alpha=0.12))
        for ax in (ax1, ax2):
            ax.axhline(s["entry"], color="#58a6ff", linewidth=1.4)
            ax.axhline(s["sl"], color="#ef5350", linewidth=1.2, linestyle=":")
            ax.axhline(s["tp"], color="#26a69a", linewidth=1.2, linestyle=":")
            if s["tp1"]:
                ax.axhline(s["tp1"], color="#f0b90b", linewidth=1.0, linestyle="--")
        ax2.text(len(m1[-160:]) - 1, s["entry"],
                 f" {s['strategy']} {s['dir']}: دخول {s['entry']} وقف {s['sl']} "
                 f"هدف {s['tp']} (R:R {s['rr']})",
                 color="#58a6ff", fontsize=9, weight="bold", va="bottom", ha="right")
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    fig.suptitle(f"سكالبينج FVG — 15M+1M | {now} دمشق | "
                 f"{'إشارة: ' + signals[0]['dir'] if signals else 'لا إشارات جديدة'}",
                 color=FG, fontsize=12, weight="bold")
    plt.tight_layout()
    plt.savefig(PNG_F, dpi=120, facecolor=BG)
    plt.close()


def main():
    require_market_open()
    m15 = read(interval="15min", limit=400)
    m1 = read(interval="1min", limit=600)
    st = load_state()
    fresh = [s for s in scan(m15, m1) if s["key"] not in st["alerted_keys"]]
    for s in fresh:
        st["alerted_keys"].append(s["key"])
    save_state(st)
    report = {"t": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
              "price": m1[-1]["c"] if m1 else None,
              "signals": fresh}
    with open(JSON_F, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    draw(m15, m1, fresh)
    print(f"FVG-SCALP DONE | إشارات جديدة: {len(fresh)}")
    for s in fresh:
        print(json.dumps(s, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
