#!/usr/bin/env python3
"""استراتيجية ICT 4-Step المنفصلة — XAUUSD (Daniel Harper — فيديو 2589096188261443).

الخطوات الأربع:
  1) الإطار (4H): سيولة خارجية (قمم/قيعان متأرجحة) وداخلية (FVGs) — أقرب POI غير
     مستهلكة تحدد التحيز والهدف (سيولة خارجية معاكسة) والإبطال.
  2) POI (15M): بعد لمس السعر لمنطقة POI الـ 4H — POI جديدة بنفس الاتجاه.
  3) الدخول — متغيرات: A) مباشر من FVG الـ 15M (50% إذا > 1×ATR15 وإلا من البداية)،
     A2) دخول 50% دائماً، A3) التعادل عند TP2 بدل TP1، A4) كلاهما،
     B) شمعة ابتلاع CISD عند الـ POI. فلتر Premium/Discount + وقف الحافة البعيدة
     + هدف السيولة المعاكسة + رفض إذا R:R < 2.
  4) المخرجات بصيغة إشاراتنا + رسم.

الدوال swings/atr/body/bullish_fvg/bearish_fvg منسوخة من ict_chart.py (ماسح ICT —
نموذج زين زكي) — لا يُستورد الملف لأنه ينفذ كوداً على مستوى الوحدة.

اجتهادات موثقة (A1..A10) في حقل assumptions لكل إشارة — ليست من الفيديو.
المتغير المعتمد حياً: A4 (دخول 50% دائماً + التعادل عند TP2) — باكتست 2026-10-19.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

OUT = os.path.expanduser("~/workspace/gold-station")
TZ = "Asia/Damascus"
_TZD = ZoneInfo(TZ)
STATE = os.path.join(OUT, "ict4step_state.json")

# ---------- معايير الاجتهاد (موثقة — ليست من الفيديو) ----------
P = {
    "swing_n_h4": 2,          # نوافذ القمم/القيعان (من ict_chart)
    "swing_n_m15": 4,         # (من ict_chart)
    "poi_max_age_h4": 40,     # أقصى عمر لـ POI الإطار (~7 أيام)
    "touch_tol_atr": 0.5,     # لمس منطقة الـ 4H ضمن 0.5×ATR4
    "fvg_big_atr": 1.0,       # فجوة > 1×ATR15 = كبيرة → دخول 50%
    "sl_buf_atr": 0.25,       # هامش الوقف
    "min_rr": 2.0,            # (قاعدة ict_chart)
    "disp_body_atr": 1.2,     # شمعة الإزاحة: جسم > 1.2×ATR (من ict_chart)
    "h4_fvg_lookback": 60,    # نافذة فجوات الـ 4H
    "m15_fvg_lookback": 120,  # نافذة فجوات الـ 15M
    "poi_fresh_m15": 48,      # POI الـ 15M خلال آخر 48 شمعة (12 سا)
    "min_penetration": 1.0,    # $ — اختراق حقيقي للسحب (من ict_chart)
    "spread": 0.30,           # $ — للباكتست
}


# ---------- دوال منسوخة من ict_chart.py (مصدرها: نموذج زين زكي) ----------
def body(c):
    return abs(c["c"] - c["o"])


def bullish_fvg(c1, c2, c3):
    # SIBI: فراغ بين ذيل الشمعة1 العلوي وذيل الشمعة3 السفلي + شمعة2 صاعدة قوية
    if c2["c"] <= c2["o"]:
        return None
    if c1["h"] <= c3["l"]:  # لا تلامس بين الذيلين
        return (c3["l"], c1["h"])
    return None


def bearish_fvg(c1, c2, c3):
    # BISI: فراغ بين ذيل الشمعة1 السفلي وذيل الشمعة3 العلوي + شمعة2 هابطة قوية
    if c2["c"] >= c2["o"]:
        return None
    if c1["l"] >= c3["h"]:
        return (c1["l"], c3["h"])
    return None


def swings(candles, n=3):
    highs, lows = [], []
    for i in range(n, len(candles) - n):
        h, l = candles[i]["h"], candles[i]["l"]
        if all(h >= candles[j]["h"] for j in range(i - n, i + n + 1) if j != i):
            highs.append((i, h, candles[i]["t"]))
        if all(l <= candles[j]["l"] for j in range(i - n, i + n + 1) if j != i):
            lows.append((i, l, candles[i]["t"]))
    return highs, lows


def atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:period]) / period
    for x in trs[period:]:
        a = (a * (period - 1) + x) / period
    return a


# ---------- أدوات الاستراتيجية ----------
def find_fvgs(candles, lookback):
    """فجوات (top, bot) مع الاستهلاك: مملوءة إذا أُغلق داخلها/خلفها لاحقاً."""
    out = []
    start = max(0, len(candles) - lookback - 2)
    for i in range(start, len(candles) - 2):
        c1, c2, c3 = candles[i], candles[i + 1], candles[i + 2]
        z = bullish_fvg(c1, c2, c3)
        if z:
            # مستهلكة إذا أغلقت شمعة لاحقة تحت قاع الفجوة
            consumed = any(candles[k]["c"] < z[1] for k in range(i + 3, len(candles)))
            out.append({"dir": "bullish", "top": z[0], "bot": z[1],
                        "idx": i + 1, "t": c2["t"], "consumed": consumed, "kind": "FVG"})
            continue
        z = bearish_fvg(c1, c2, c3)
        if z:
            consumed = any(candles[k]["c"] > z[0] for k in range(i + 3, len(candles)))
            out.append({"dir": "bearish", "top": z[0], "bot": z[1],
                        "idx": i + 1, "t": c2["t"], "consumed": consumed, "kind": "FVG"})
    return out


def find_obs(candles, a, lookback):
    """Order Blocks مبسطة: آخر شمعة معاكسة قبل شمعة إزاحة قوية."""
    out = []
    start = max(1, len(candles) - lookback)
    for i in range(start, len(candles)):
        c, p = candles[i], candles[i - 1]
        if body(c) > P["disp_body_atr"] * a:
            if c["c"] > c["o"] and p["c"] < p["o"]:
                consumed = any(candles[k]["c"] < p["l"] for k in range(i + 1, len(candles)))
                out.append({"dir": "bullish", "top": p["h"], "bot": p["l"],
                            "idx": i - 1, "t": p["t"], "consumed": consumed, "kind": "OB"})
            elif c["c"] < c["o"] and p["c"] > p["o"]:
                consumed = any(candles[k]["c"] > p["h"] for k in range(i + 1, len(candles)))
                out.append({"dir": "bearish", "top": p["h"], "bot": p["l"],
                            "idx": i - 1, "t": p["t"], "consumed": consumed, "kind": "OB"})
    return out


def framework(h4):
    """الخطوة 1 — الإطار على 4H.

    A1 (اجتهاد): أقرب POI غير مستهلكة (FVG أو OB) للسعر تحدد التحيز.
    الهدف = أقرب سيولة خارجية (قمة/قاع متأرجح) معاكسة. الإبطال = الحافة البعيدة.
    """
    if len(h4) < 40:
        return None
    a4 = atr(h4)
    price = h4[-1]["c"]
    h4h, h4l = swings(h4, P["swing_n_h4"])
    pois = [f for f in find_fvgs(h4, P["h4_fvg_lookback"])
            if not f["consumed"] and (len(h4) - 1 - f["idx"]) <= P["poi_max_age_h4"]]
    pois += [o for o in find_obs(h4, a4, P["h4_fvg_lookback"])
             if not o["consumed"] and (len(h4) - 1 - o["idx"]) <= P["poi_max_age_h4"]]
    if not pois:
        return None
    # الأقرب للسعر (من حافة المنطقة)
    def dist(p):
        return 0.0 if p["bot"] <= price <= p["top"] else min(abs(price - p["top"]), abs(price - p["bot"]))
    poi = min(pois, key=dist)
    bullish = poi["dir"] == "bullish"
    # السيولة الخارجية المعاكسة = الهدف
    if bullish:
        cands = [s[1] for s in h4h if s[1] > price]
        target = min(cands) if cands else None
        invalidation = poi["bot"]
    else:
        cands = [s[1] for s in h4l if s[1] < price]
        target = max(cands) if cands else None
        invalidation = poi["top"]
    # نطاق التعامل Premium/Discount (من ict_chart)
    deal_low = h4l[-1][1] if h4l else min(c["l"] for c in h4)
    deal_high = h4h[-1][1] if h4h else max(c["h"] for c in h4)
    eq = (deal_high + deal_low) / 2
    return {
        "bias": "buy" if bullish else "sell",
        "poi": poi, "target_ext": target, "invalidation": invalidation,
        "atr4": a4, "eq": eq, "deal_low": deal_low, "deal_high": deal_high,
        "price": price,
    }


def touch_4h_poi(m15, poi, a4):
    """هل لمس السعر منطقة POI الـ 4H مؤخراً (ضمن 0.5×ATR4)؟ A2."""
    tol = P["touch_tol_atr"] * a4
    lo, hi = poi["bot"] - tol, poi["top"] + tol
    for c in m15[-48:]:
        if c["l"] <= hi and c["h"] >= lo:
            return True, c["t"]
    return False, None


def detect(h4, m15, variant="A"):
    """تشغيل الخطوات الأربع على بيانات مغلقة. تُرجع قائمة إشارات (0..n).

    المتغيرات: A (أساس)، A2 (دخول 50% دائماً)، A3 (التعادل عند TP2)،
    A4 (كلاهما)، B (CISD).
    """
    signals = []
    if len(h4) < 40 or len(m15) < 130:
        return signals
    entry50 = variant in ("A2", "A4")   # A9 (اجتهاد): دخول 50% دائماً
    be_tp2 = variant in ("A3", "A4")     # A10 (اجتهاد): تأخير التعادل إلى TP2
    fw = framework(h4)
    if not fw or fw["target_ext"] is None:
        return signals
    a15 = atr(m15)
    price = m15[-1]["c"]
    is_buy = fw["bias"] == "buy"
    poi = fw["poi"]

    # الخطوة 2: لمس منطقة الـ 4H ثم POI جديدة على 15M بنفس الاتجاه
    touched, touch_t = touch_4h_poi(m15, poi, fw["atr4"])
    if not touched:
        return signals
    m15_pois = [f for f in find_fvgs(m15, P["m15_fvg_lookback"])
                if not f["consumed"]
                and (f["dir"] == "bullish") == is_buy
                and (len(m15) - 1 - f["idx"]) <= P["poi_fresh_m15"]]
    m15_pois += [o for o in find_obs(m15, a15, P["m15_fvg_lookback"])
                 if not o["consumed"]
                 and (o["dir"] == "bullish") == is_buy
                 and (len(m15) - 1 - o["idx"]) <= P["poi_fresh_m15"]]
    if not m15_pois:
        return signals
    # الأحدث
    mp = max(m15_pois, key=lambda x: x["idx"])

    # فلتر Premium/Discount (من ict_chart): ممنوع الشراء في العلاوة/البيع في الخصم
    eq = fw["eq"]

    cands = []
    if variant in ("A", "A2", "A3", "A4"):
        # الخطوة 3A: دخول مباشر من FVG الـ 15M
        fvgs = [f for f in m15_pois if f["kind"] == "FVG"]
        if not fvgs:
            return signals
        f = max(fvgs, key=lambda x: x["idx"])
        size = f["top"] - f["bot"]
        big = size > P["fvg_big_atr"] * a15  # A3: عتبة الكبيرة/الصغيرة
        use50 = entry50 or big               # A9: دخول 50% دائماً
        if is_buy:
            entry = (f["top"] + f["bot"]) / 2 if use50 else f["bot"]
            sl = f["bot"] - P["sl_buf_atr"] * a15  # A4: الحافة البعيدة + هامش
        else:
            entry = (f["top"] + f["bot"]) / 2 if use50 else f["top"]
            sl = f["top"] + P["sl_buf_atr"] * a15
        entry_kind = "50% دائم" if entry50 else ("50%" if big else "بداية الفجوة")
        cands.append((f, entry, sl, entry_kind))
    else:
        # الخطوة 3B: CISD — شمعة ابتلاع عند الـ POI
        z_lo, z_hi = mp["bot"], mp["top"]
        for i in range(max(1, len(m15) - 24), len(m15)):
            c, p = m15[i], m15[i - 1]
            if not (z_lo <= c["c"] <= z_hi or z_lo <= c["o"] <= z_hi):
                continue
            engulf_buy = (c["c"] > c["o"] and p["c"] < p["o"]
                          and c["c"] >= p["o"] and c["o"] <= p["c"]
                          and body(c) > 0.5 * body(p))
            engulf_sell = (c["c"] < c["o"] and p["c"] > p["o"]
                           and c["c"] <= p["o"] and c["o"] >= p["c"]
                           and body(c) > 0.5 * body(p))
            if (is_buy and engulf_buy) or ((not is_buy) and engulf_sell):
                entry = c["c"]
                sl = (c["l"] - P["sl_buf_atr"] * a15) if is_buy else (c["h"] + P["sl_buf_atr"] * a15)
                cands.append((mp, entry, sl, f"CISD ابتلاع {c['t'][11:16]}"))
    for f, entry, sl, entry_kind in cands:
        # فلتر Premium/Discount
        if is_buy and entry > eq:
            continue
        if (not is_buy) and entry < eq:
            continue
        risk = abs(entry - sl)
        if risk < 0.5:
            continue
        tp = fw["target_ext"]
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0
        if rr < P["min_rr"]:
            continue
        s = 1 if is_buy else -1
        t_sig = m15[-1]["t"]
        sig = {
            "strategy": "ICT 4-Step",
            "variant": variant,
            "dir": "شراء" if is_buy else "بيع",
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp1": round(entry + s * risk, 2),
            "tp2": round(entry + s * 2 * risk, 2),
            "tp3": round(entry + s * 3 * risk, 2),
            "rr": round(rr, 2),
            "key": f"ICT4-{variant}|{t_sig}|{'buy' if is_buy else 'sell'}|{round(entry,2)}",
            "t": t_sig,
            "reason": (
                f"خطوة1: تحيز {'شرائي' if is_buy else 'بيعي'} من {poi['kind']} "
                f"{'صاعدة' if is_buy else 'هابطة'} على 4H (غير مستهلكة) — "
                f"خطوة2: {mp['kind']} {'صاعدة' if is_buy else 'هابطة'} جديدة على 15M بعد اللمس — "
                f"خطوة3 ({'مباشر' if variant == 'A' else 'CISD'}): دخول {entry_kind} عند {entry:.2f} — "
                f"الوقف {sl:.2f} (إبطال)، الهدف سيولة خارجية {tp:.2f}، R:R={rr:.2f}"
            ),
            "assumptions": (
                "A1: التحيز من أقرب POI غير مستهلكة | A2: اللمس ضمن 0.5×ATR4 | "
                "A3: الفجوة الكبيرة > 1×ATR15 → دخول 50% | A4: الوقف = الحافة البعيدة ± 0.25×ATR15 | "
                "A5: POI الـ 15M خلال آخر 48 شمعة | A6: فلتر Premium/Discount من ict_chart | "
                "A7: رفض إذا R:R<2 | A8: أقصى عمر POI الإطار 40 شمعة 4H"
                + (" | A9: دخول 50% دائماً" if entry50 else "")
                + (" | A10: التعادل عند TP2 لا TP1" if be_tp2 else "")
            ),
            "mgmt": "be_tp2" if be_tp2 else "be_tp1",
            "_tp_ext": round(tp, 2),
        }
        signals.append(sig)
    return signals


def td_live(interval, outputsize):
    key = open(os.path.expanduser("~/.config/goldstation/twelvedata_key")).read().strip()
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}"
           f"&outputsize={outputsize}&order=ASC&timezone={TZ}&apikey={key}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "values" not in data:
        raise RuntimeError(str(data)[:200])
    return [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
             "l": float(v["low"]), "c": float(v["close"])} for v in data["values"]]


def draw(h4, m15, fw, sigs):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=False)
        fig.patch.set_facecolor("#0d1117")
        for ax in (ax1, ax2):
            ax.set_facecolor("#0d1117")
        # 4H
        d4 = h4[-60:]
        for i, c in enumerate(d4):
            col = "#26a69a" if c["c"] >= c["o"] else "#ef5350"
            ax1.plot([i, i], [c["l"], c["h"]], color=col, linewidth=0.9)
            b, t = min(c["o"], c["c"]), max(c["o"], c["c"])
            ax1.add_patch(Rectangle((i - 0.35, b), 0.7, max(t - b, 0.05), facecolor=col, edgecolor=col))
        if fw:
            p = fw["poi"]
            pi = p["idx"] - (len(h4) - len(d4))
            col = "#26a69a" if fw["bias"] == "buy" else "#ef5350"
            if 0 <= pi < len(d4):
                ax1.add_patch(Rectangle((pi - 1, p["bot"]), len(d4) - pi + 1, p["top"] - p["bot"],
                                        facecolor=col, alpha=0.18, edgecolor=col, linestyle="--"))
            if fw["target_ext"] is not None:
                ax1.axhline(fw["target_ext"], color="#f0b90b", linestyle=":", linewidth=1.2)
                ax1.set_title(f"4H إطار: تحيز {fw['bias']} — هدف {fw['target_ext']:.2f}",
                              color="white", fontsize=10, weight="bold")
            else:
                ax1.set_title(f"4H إطار: تحيز {fw['bias']} — بلا هدف مؤكد",
                              color="white", fontsize=10, weight="bold")
        else:
            ax1.set_title("4H إطار: تحيز غير مؤكد", color="white", fontsize=10, weight="bold")
        # 15M
        d15 = m15[-120:]
        off = len(m15) - len(d15)
        for i, c in enumerate(d15):
            col = "#26a69a" if c["c"] >= c["o"] else "#ef5350"
            ax2.plot([i, i], [c["l"], c["h"]], color=col, linewidth=0.8)
            b, t = min(c["o"], c["c"]), max(c["o"], c["c"])
            ax2.add_patch(Rectangle((i - 0.35, b), 0.7, max(t - b, 0.05), facecolor=col, edgecolor=col))
        for sg in sigs:
            for lv, cc, ls in ((sg["entry"], "#58a6ff", "-"), (sg["sl"], "#ef5350", ":"),
                               (sg["tp1"], "#26a69a", "--"), (sg["tp2"], "#26a69a", "--"),
                               (sg["tp3"], "#26a69a", "--")):
                ax2.axhline(lv, color=cc, linewidth=1.1, linestyle=ls, alpha=0.9)
            ax2.text(len(d15) - 1, sg["entry"],
                     f" ICT 4-Step-{sg['variant']} {sg['dir']}: {sg['entry']} / وقف {sg['sl']}",
                     color="#58a6ff", fontsize=9, weight="bold", va="bottom", ha="right")
        ax2.set_title("15M دخول", color="white", fontsize=10, weight="bold")
        for ax in (ax1, ax2):
            ax.tick_params(colors="#8b949e", labelsize=8)
            for sp in ax.spines.values():
                sp.set_color("#30363d")
        plt.tight_layout()
        plt.savefig(os.path.join(OUT, "gold_ict4step.png"), dpi=130, facecolor="#0d1117")
        plt.close()
    except Exception as e:
        print(f"رسم: {e}", file=sys.stderr)


def main():
    from market_hours import require_market_open
    require_market_open()
    from candle_db import get_candles
    h4 = get_candles("4h", 120, live=lambda: td_live("4h", 120))
    m15 = get_candles("15min", 300, live=lambda: td_live("15min", 300))
    # إسقاط الشمعة المتشكلة (منع إعادة الرسم)
    now = datetime.now(_TZD).replace(tzinfo=None)
    m15 = [c for c in m15
           if datetime.strptime(c["t"], "%Y-%m-%d %H:%M:%S")
           <= now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)]
    fw = framework(h4)
    sigs = []
    # A4 هو المتغير المعتمد (باكتست 2026-10-19: +0.056R/صفقة — الأعلى expectancy)
    for variant in ("A4", "B"):
        sigs.extend(detect(h4, m15, variant))
    # إزالة التكرار داخل التشغيل
    seen, uniq = set(), []
    for s in sigs:
        if s["key"] not in seen:
            seen.add(s["key"])
            uniq.append(s)
    # حارس الحداثة (قرار علاء 2026-10-23): الدخول هنا مستوى معلّق بتصميم
    # النموذج — يُسقَط الإعداد فقط إذا تجاوز السعر الحي هدفه الأول أو وقفه
    # قبل التسجيل (منع الصفقات الشبحية مثل #158)
    from freshness import filter_fresh
    uniq, dropped_stale = filter_fresh(uniq, mode="levels")
    # تسليح مسبق (قرار علاء 2026-10-27): متغير A4 دخوله مستوى 50% معلّق
    # بتصميم النموذج — اكتب نية لمنفّذ المرآة فيعلّق الأوامر عند البروكر
    # قبل وصول السعر. متغير B دخوله سوقي فلا نية له. كتلة صامتة تماماً.
    try:
        import mirror_intents as _mi
        for _s in uniq:
            if _s.get("variant") == "A4":
                _mi.append_intent(
                    "ICT 4-Step", _s["dir"], _s["entry"], _s["sl"],
                    tp1=_s.get("tp1"), tp2=_s.get("tp2"),
                    tp3=_s.get("tp3"), expiry_min=120, mgmt="secure",
                    note="نية تسليح من ماسح ICT 4-Step (دخول 50%)",
                    key=_s.get("key"))
    except Exception:
        pass
    with open(os.path.join(OUT, "gold_ict4step.json"), "w") as f:
        json.dump({"signals": uniq,
                   "dropped_stale": dropped_stale,
                   "framework": {k: (round(v, 2) if isinstance(v, float) else v)
                                 for k, v in (fw or {}).items() if k != "poi"}
                   if fw else None,
                   "at": datetime.now(_TZD).strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=1)
    draw(h4, m15, fw, uniq)
    print(json.dumps({"signals": [{k: s[k] for k in ("strategy", "variant", "dir", "entry", "sl", "rr", "key")} for s in uniq]}, ensure_ascii=False)[:1500])
    print("ICT4STEP DONE")


if __name__ == "__main__":
    main()
