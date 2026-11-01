#!/usr/bin/env python3
"""تحليل ICT ميكانيكي على الذهب — مستخرج حرفياً من ملخص كورس زين زكي (ICT Full Course).

النموذج عالي الاحتمالية (فيديو 20):
  1) سحب سيولة واضح فوق قمة سابقة أو تحت قاع سابق (Liquidity Sweep)
  2) إزاحة سعرية قوية بشموع أجسام كبيرة (Displacement)
  3) كسر هيكل السوق بإغلاق جسم واضح (MSS)
  4) تكوين فجوة سعرية نظيفة (FVG)
  5) إعادة اختبار: عودة السعر لملء FVG الواقعة في الخصم (شراء) أو العلاوة (بيع)
  6) الدخول: وقف عند قاع/قمة الإزاحة، هدف السيولة المقابلة، R:R لا يقل عن 1:2

القواعد الميكانيكية:
- Premium/Discount: النطاق من قاع التأرجح إلى قمته، خط 50% هو التوازن.
  ممنوع الشراء في العلاوة نهائياً حتى لو الاتجاه صاعد بقوة.
- FVG تُلغى إذا تداخل ذيل الشمعة 1 مع ذيل الشمعة 3.
- الأوردر بلوك يتفعل بإغلاق جسم الشمعة لا بكسر الذيل.
"""
import json, urllib.request, os
from datetime import datetime

KEY = open(os.path.expanduser("~/.config/goldstation/twelvedata_key")).read().strip()
OUT = os.path.expanduser("~/workspace/gold-station")
os.makedirs(OUT, exist_ok=True)
TZ = "Asia/Damascus"

def td(interval, outputsize):
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}"
           f"&outputsize={outputsize}&order=ASC&timezone={TZ}&apikey={KEY}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "values" not in data:
        raise RuntimeError(str(data)[:200])
    return [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
             "l": float(v["low"]), "c": float(v["close"])} for v in data["values"]]

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

# ---------- البيانات (H4 لنطاق التعامل + M15 للنموذج): القاعدة أساساً ----------
from market_hours import require_market_open
require_market_open()  # السوق مغلق = خروج صامت بلا أي طلب API (بأمر علاء 2026-10-17)

def db_candles(interval, n):
    # بقرار علاء 2026-10-30: شموع cTrader من القاعدة المحلية حصراً — لا جلب
    # TwelveData أبداً. عند قِدَم بيانات cTrader تُقرأ آخر صفوف cTrader
    # المتاحة بدل التبديل إلى أي مصدر آخر.
    from candle_db import get_candles, read as _db_read
    try:
        return get_candles(interval, n, source="ctrader")
    except Exception:
        rows = _db_read(interval=interval, source="ctrader", limit=n)
        if len(rows) >= min(n, 20):
            return rows
        raise

h4 = db_candles("4h", 80)
m15 = db_candles("15min", 220)
a15 = atr(m15)
price = m15[-1]["c"]
now_t = m15[-1]["t"]

h4h, h4l = swings(h4, 2)
m15h, m15l = swings(m15, 4)

# ---------- نطاق التعامل Premium/Discount (من H4: آخر قاع رئيسي -> آخر قمة) ----------
deal_low = h4l[-1][1] if h4l else min(c["l"] for c in h4)
deal_high = h4h[-1][1] if h4h else max(c["h"] for c in h4)
# إن كانت القمة أقدم من القاع نأخذ أوسع نطاق حديث
if h4h and h4l and h4h[-1][0] < h4l[-1][0]:
    deal_high = max(c["h"] for c in m15[-96:])
eq = (deal_high + deal_low) / 2
zone = "علاوة Premium (ممنوع الشراء)" if price > eq else "خصم Discount (ممنوع البيع)"

# ---------- سحب السيولة (آخر 96 شمعة M15 = 24 ساعة) — الأحدث باختراق حقيقي (≥ 1$) ----------
sweeps = []
MIN_PEN = 1.0
for i in range(len(m15) - 96, len(m15)):
    c = m15[i]
    ph = [s for s in m15h if s[0] < i - 4]
    pl = [s for s in m15l if s[0] < i - 4]
    if ph and c["h"] > ph[-1][1] and c["c"] < ph[-1][1] and (c["h"] - ph[-1][1]) >= MIN_PEN:
        sweeps.append({"dir": "سحب سيولة شرائية BSL", "level": ph[-1][1], "idx": i,
                       "t": c["t"], "wick_high": c["h"]})
    elif pl and c["l"] < pl[-1][1] and c["c"] > pl[-1][1] and (pl[-1][1] - c["l"]) >= MIN_PEN:
        sweeps.append({"dir": "سحب سيولة بيعية SSL", "level": pl[-1][1], "idx": i,
                       "t": c["t"], "wick_low": c["l"]})
sweep = sweeps[-1] if sweeps else None

# ---------- الإزاحة بعد السحب ----------
displacement = None
if sweep:
    si = sweep["idx"]
    bearish = "BSL" in sweep["dir"]  # سحب قمم -> الإزاحة المتوقعة هبوط
    for j in range(si + 1, min(si + 12, len(m15))):
        c = m15[j]
        strong = body(c) > 1.2 * a15
        if bearish and c["c"] < c["o"] and strong:
            displacement = {"dir": "هابطة", "idx": j, "t": c["t"],
                            "extreme": max(m15[k]["h"] for k in range(si, j + 1))}
            break
        if not bearish and c["c"] > c["o"] and strong:
            displacement = {"dir": "صاعدة", "idx": j, "t": c["t"],
                            "extreme": min(m15[k]["l"] for k in range(si, j + 1))}
            break

# ---------- كسر الهيكل MSS بعد الإزاحة ----------
mss = None
if displacement:
    di = displacement["idx"]
    bearish = displacement["dir"] == "هابطة"
    for j in range(di + 1, len(m15)):
        c = m15[j]
        pl = [s for s in m15l if s[0] < j - 4]
        ph = [s for s in m15h if s[0] < j - 4]
        if bearish and pl and c["c"] < pl[-1][1] and c["o"] > pl[-1][1]:
            mss = {"dir": "هابط", "level": pl[-1][1], "idx": j, "t": c["t"]}
            break
        if not bearish and ph and c["c"] > ph[-1][1] and c["o"] < ph[-1][1]:
            mss = {"dir": "صاعد", "level": ph[-1][1], "idx": j, "t": c["t"]}
            break

# ---------- الفجوات السعرية FVG (آخر 120 شمعة) ----------
fvgs = []
for i in range(len(m15) - 120, len(m15) - 2):
    c1, c2, c3 = m15[i], m15[i + 1], m15[i + 2]
    z = bullish_fvg(c1, c2, c3)
    if z:
        filled = any(m15[k]["l"] < z[1] for k in range(i + 3, len(m15)))
        fvgs.append({"dir": "صاعدة", "top": z[0], "bot": z[1], "idx": i + 1,
                     "t": c2["t"], "filled": filled})
    z = bearish_fvg(c1, c2, c3)
    if z:
        filled = any(m15[k]["h"] > z[0] for k in range(i + 3, len(m15)))
        fvgs.append({"dir": "هابطة", "top": z[0], "bot": z[1], "idx": i + 1,
                     "t": c2["t"], "filled": filled})
open_fvgs = [f for f in fvgs if not f["filled"]]

# ---------- تقييم النموذج: هل يوجد إعداد مكتمل الأركان؟ ----------
# ---------- تقييم كل السلاسل: سحب -> إزاحة -> MSS -> فجوة غير مملوءة ----------
# (يتتبع كل السحوبات لا الأحدث فقط، حتى لا يمحو سحب جديد سلسلة مكتملة قديمة)
def chain_for(sw):
    si = sw["idx"]
    bearish = "BSL" in sw["dir"]  # سحب قمم -> الإزاحة المتوقعة هبوط
    displacement = None
    for j in range(si + 1, min(si + 12, len(m15))):
        c = m15[j]
        strong = body(c) > 1.2 * a15
        if bearish and c["c"] < c["o"] and strong:
            displacement = {"dir": "هابطة", "idx": j, "t": c["t"],
                            "extreme": max(m15[k]["h"] for k in range(si, j + 1))}
            break
        if not bearish and c["c"] > c["o"] and strong:
            displacement = {"dir": "صاعدة", "idx": j, "t": c["t"],
                            "extreme": min(m15[k]["l"] for k in range(si, j + 1))}
            break
    if not displacement:
        return None
    mss = None
    di = displacement["idx"]
    b2 = displacement["dir"] == "هابطة"
    for j in range(di + 1, len(m15)):
        c = m15[j]
        pl = [s for s in m15l if s[0] < j - 4]
        ph = [s for s in m15h if s[0] < j - 4]
        if b2 and pl and c["c"] < pl[-1][1] and c["o"] > pl[-1][1]:
            mss = {"dir": "هابط", "level": pl[-1][1], "idx": j, "t": c["t"]}
            break
        if not b2 and ph and c["c"] > ph[-1][1] and c["o"] < ph[-1][1]:
            mss = {"dir": "صاعد", "level": ph[-1][1], "idx": j, "t": c["t"]}
            break
    if not mss:
        return None
    # FVG من الإزاحة غير مملوءة بعد — ويجب أن تكون من ساق الإزاحة نفسها
    # (خلال 12 شمعة بعد الإزاحة كحد أقصى، لا فجوة عشوائية بعد ساعات)
    cand = [f for f in open_fvgs
            if (f["dir"] == "هابطة") == b2
            and displacement["idx"] <= f["idx"] <= displacement["idx"] + 12]
    # فجوة الإزاحة نفسها: أول فجوة غير مملوءة بعد الإزاحة وفي المنطقة الصحيحة
    # (علاوة للبيع / خصم للشراء — ممنوع الشراء في العلاوة نهائياً حسب الكورس)
    f = None
    for g in cand:  # cand مرتبة زمنياً: الأقدم أولاً
        in_premium = g["bot"] > eq
        in_discount = g["top"] < eq
        if (b2 and in_premium) or ((not b2) and in_discount):
            f = g
            break
    if not f:
        return None
    entry = (f["top"] + f["bot"]) / 2
    if b2:
        sl = displacement["extreme"] + 0.25 * a15
        tgt_swings = [s[1] for s in m15l if s[0] < len(m15) - 4]
        tp = min(tgt_swings) if tgt_swings else deal_low
    else:
        sl = displacement["extreme"] - 0.25 * a15
        tgt_swings = [s[1] for s in m15h if s[0] < len(m15) - 4]
        tp = max(tgt_swings) if tgt_swings else deal_high
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0
    if rr < 2.0:
        return None
    # هل السعر عاد لداخل الفجوة الآن؟
    inside = (f["bot"] <= price <= f["top"])
    return {
        "key": f"{'sell' if b2 else 'buy'}|{f['t']}|{round(entry, 2)}",
        "dir": "بيع" if b2 else "شراء",
        "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2),
        "rr": round(rr, 2), "inside_now": inside,
        "fvg": {"top": round(f["top"], 2), "bot": round(f["bot"], 2), "t": f["t"]},
        "sweep": {"t": sw["t"], "level": round(sw["level"], 2), "idx": sw["idx"]},
        "disp_t": displacement["t"], "mss_t": mss["t"],
        "disp_idx": displacement["idx"], "mss_idx": mss["idx"],
        "valid": True,
        "note": "مكتمل الأركان" if inside else "بانتظار عودة السعر للفجوة",
    }

chains = []
for sw in sweeps:
    ch = chain_for(sw)
    if ch:
        chains.append(ch)
# إزالة التكرار: نفس المفتاح قد ينتج من سحبين متتاليين
seen_keys = set()
uniq_chains = []
for ch in chains:
    if ch["key"] not in seen_keys:
        seen_keys.add(ch["key"])
        uniq_chains.append(ch)
chains = uniq_chains

ready = [c for c in chains if c["inside_now"]]
forming = [c for c in chains if not c["inside_now"]]
# حارس الحداثة (قرار علاء 2026-10-23): الدخول هنا مستوى فجوة معلّق بتصميم
# النموذج — يُسقَط الإعداد فقط إذا تجاوز السعر الحي هدفه أو وقفه قبل التسجيل
from freshness import filter_fresh
ready, dropped_ready = filter_fresh(ready, mode="levels")
forming, dropped_forming = filter_fresh(forming, mode="levels")
dropped_stale = dropped_ready + dropped_forming
setup = ready[-1] if ready else None  # أحدث إعداد جاهز للدخول الفوري

report = {
    "time": now_t, "price": round(price, 2), "atr_m15": round(a15, 2),
    "dealing_range": {"low": round(deal_low, 2), "high": round(deal_high, 2),
                      "eq_50": round(eq, 2), "zone": zone},
    "sweep": sweep and {**sweep, "level": round(sweep["level"], 2),
                        **({"wick_high": round(sweep["wick_high"], 2)} if "wick_high" in sweep else {}),
                        **({"wick_low": round(sweep["wick_low"], 2)} if "wick_low" in sweep else {})},
    "displacement": displacement and {**displacement, "extreme": round(displacement["extreme"], 2)},
    "mss": mss and {**mss, "level": round(mss["level"], 2)},
    "open_fvgs": [{"dir": f["dir"], "top": round(f["top"], 2), "bot": round(f["bot"], 2), "t": f["t"]}
                  for f in open_fvgs[-5:]],
    "setup": setup,
    "forming": [{k: c[k] for k in ("key", "dir", "entry", "sl", "tp", "rr", "inside_now",
                                   "fvg", "sweep", "disp_t", "mss_t", "note")} for c in forming],
    "dropped_stale": dropped_stale,
}
with open(f"{OUT}/ict_report.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

# ---------- الرسم ----------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

fig, ax = plt.subplots(figsize=(14, 7.5))
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")

data = m15[-150:]
off = len(m15) - len(data)
for i, c in enumerate(data):
    col = "#26a69a" if c["c"] >= c["o"] else "#ef5350"
    ax.plot([i, i], [c["l"], c["h"]], color=col, linewidth=0.8)
    b, t = min(c["o"], c["c"]), max(c["o"], c["c"])
    ax.add_patch(Rectangle((i - 0.35, b), 0.7, max(t - b, 0.05), facecolor=col, edgecolor=col))

# مناطق العلاوة/الخصم
ax.axhspan(eq, deal_high, color="#ef5350", alpha=0.06)
ax.axhspan(deal_low, eq, color="#26a69a", alpha=0.06)
ax.axhline(eq, color="#f0b90b", linestyle="-", linewidth=1, alpha=0.8)
ax.text(len(data) - 1, eq, "  توازن 50%", color="#f0b90b", fontsize=9, va="bottom", ha="right", weight="bold")
ax.text(2, deal_high, "علاوة Premium — البيع فقط", color="#ef5350", fontsize=9, va="top", weight="bold")
ax.text(2, deal_low, "خصم Discount — الشراء فقط", color="#26a69a", fontsize=9, va="bottom", weight="bold")

# الفجوات المفتوحة
for f in open_fvgs[-5:]:
    fi = f["idx"] - off
    col = "#26a69a" if f["dir"] == "صاعدة" else "#ef5350"
    if 0 <= fi < len(data):
        ax.add_patch(Rectangle((fi - 1, f["bot"]), len(data) - fi + 1, f["top"] - f["bot"],
                               facecolor=col, alpha=0.18, edgecolor=col, linestyle="--", linewidth=0.8))
        ax.text(len(data) - 1, f["top"], f" FVG {f['dir']}", color=col, fontsize=8, va="bottom", ha="right")

# السحب والإزاحة وكسر الهيكل
def vline(idx, color, label, y):
    bi = idx - off
    if 0 <= bi < len(data):
        ax.axvline(bi, color=color, linestyle=":", alpha=0.8)
        ax.annotate(label, xy=(bi, y), color=color, fontsize=9, weight="bold")

if sweep:
    y = sweep.get("wick_high", sweep.get("wick_low"))
    vline(sweep["idx"], "#58a6ff", f"سحب سيولة\n{sweep['level']:.1f}", y)
if mss:
    vline(mss["idx"], "#d2a8ff", f"MSS {mss['dir']}\n{mss['level']:.1f}", mss["level"])

# الصفقة
show = setup if (setup and setup["valid"]) else (forming[-1] if forming else None)
if show and show.get("valid", True):
    ls = "-" if (setup and setup["valid"]) else "--"
    tag = "" if (setup and setup["valid"]) else " (بانتظار إعادة الاختبار)"
    for lv, col, lb in [(show["entry"], "#58a6ff", f"دخول {show['entry']}{tag}"),
                        (show["sl"], "#ef5350", f"وقف {show['sl']}"),
                        (show["tp"], "#26a69a", f"هدف {show['tp']}")]:
        ax.axhline(lv, color=col, linestyle=ls, linewidth=1.4)
        ax.text(len(data) - 1, lv, f" {lb}", color=col, fontsize=10, va="bottom", ha="right", weight="bold")
    title = (f"XAUUSD M15 · ICT | {show['dir']}  دخول {show['entry']}  وقف {show['sl']}  "
             f"هدف {show['tp']}  RR {show['rr']} | {show['note']}")
else:
    title = (f"XAUUSD M15 · ICT | السعر {price:.1f} | {zone} | "
             f"لا يوجد إعداد — بانتظار سحب سيولة/إزاحة جديدة")
ax.set_title(title, color="white", fontsize=11, weight="bold")

tick_idx = list(range(0, len(data), 25))
ax.set_xticks(tick_idx)
ax.set_xticklabels([data[i]["t"][5:16].replace(" ", "\n") for i in tick_idx], color="#8b949e", fontsize=7)
ax.tick_params(colors="#8b949e", labelsize=8)
for s in ax.spines.values():
    s.set_color("#30363d")
plt.tight_layout()
plt.savefig(f"{OUT}/ict_chart.png", dpi=130, facecolor="#0d1117")
print("ICT CHART SAVED")
print(json.dumps(report, ensure_ascii=False, indent=1)[:3000])
