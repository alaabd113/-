#!/usr/bin/env python3
"""تحليل GSR مبسّط على بيانات حقيقية: هيكل H4/H1 + كشف BOS/Retest على M15 + رسم الشارت."""
import json, urllib.request, os
from datetime import datetime

KEY = open(os.path.expanduser("~/.config/goldstation/twelvedata_key")).read().strip()
OUT = os.path.expanduser("~/workspace/gold-station")
os.makedirs(OUT, exist_ok=True)

def td(interval, outputsize):
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}"
           f"&outputsize={outputsize}&order=ASC&timezone=Asia/Damascus&apikey={KEY}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "values" not in data:
        raise RuntimeError(str(data)[:200])
    out = []
    for v in data["values"]:
        out.append({"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
                    "l": float(v["low"]), "c": float(v["close"])})
    return out

def swings(candles, n=3):
    """قمم/قيعان فركتلية."""
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

def trend_from_swings(highs, lows):
    if len(highs) < 2 or len(lows) < 2:
        return "غير واضح"
    hh = highs[-1][1] > highs[-2][1]
    hl = lows[-1][1] > lows[-2][1]
    lh = highs[-1][1] < highs[-2][1]
    ll = lows[-1][1] < lows[-2][1]
    if hh and hl: return "صاعد (HH/HL)"
    if lh and ll: return "هابط (LH/LL)"
    return "عرضي/مختلط"

from market_hours import require_market_open
require_market_open()  # السوق مغلق = خروج صامت بلا أي طلب API (بأمر علاء 2026-10-17)
from candle_db import get_candles
h4 = get_candles("4h", 80, live=lambda: td("4h", 80))
h1 = get_candles("1h", 120, live=lambda: td("1h", 120))
m15 = get_candles("15min", 220, live=lambda: td("15min", 220))

h4h, h4l = swings(h4, 2)
h1h, h1l = swings(h1, 3)
m15h, m15l = swings(m15, 4)

t_h4 = trend_from_swings(h4h, h4l)
t_h1 = trend_from_swings(h1h, h1l)

last_h4_high = h4h[-1][1] if h4h else None
last_h4_low = h4l[-1][1] if h4l else None
last_m15_high = m15h[-1][1] if m15h else None
last_m15_low = m15l[-1][1] if m15l else None

a_m15 = atr(m15)
price = m15[-1]["c"]

# كشف BOS على M15: إغلاق خارج آخر سوينغ خلال آخر 40 شمعة
bos = None
lookback = 40
for i in range(len(m15) - lookback, len(m15)):
    c = m15[i]
    # آخر سوينغ قبل الشمعة i
    ph = [s for s in m15h if s[0] < i - 4]
    pl = [s for s in m15l if s[0] < i - 4]
    if ph and c["c"] > ph[-1][1] and c["o"] < ph[-1][1]:
        bos = {"dir": "صاعد", "level": ph[-1][1], "idx": i, "t": c["t"]}
    elif pl and c["c"] < pl[-1][1] and c["o"] > pl[-1][1]:
        bos = {"dir": "هابط", "level": pl[-1][1], "idx": i, "t": c["t"]}

retest = None
signal = None
if bos:
    lvl = bos["level"]
    # إعادة اختبار: عودة السعر لمنطقة الكسر (ضمن 0.25%) بعد الكسر
    for j in range(bos["idx"] + 1, len(m15)):
        c = m15[j]
        touched = (c["l"] <= lvl * 1.0025 and c["h"] >= lvl * 0.9975)
        if touched:
            held = (c["c"] > lvl) if bos["dir"] == "صاعد" else (c["c"] < lvl)
            retest = {"idx": j, "t": c["t"], "held": held, "low": c["l"], "high": c["h"]}
            break
    if retest and retest["held"]:
        entry = lvl
        if bos["dir"] == "صاعد":
            prot = min(retest["low"], last_m15_low or retest["low"])
            sl = prot - 0.25 * a_m15
            tp = last_h4_high
        else:
            prot = max(retest["high"], last_m15_high or retest["high"])
            sl = prot + 0.25 * a_m15
            tp = last_h4_low
        risk = abs(entry - sl)
        reward = abs((tp or entry) - entry)
        rr = reward / risk if risk > 0 else 0
        grade = "A+" if rr >= 2.0 else ("A" if rr >= 1.6 else "مرفوضة RR ضعيف")
        signal = {"dir": "شراء" if bos["dir"] == "صاعد" else "بيع",
                  "entry": entry, "sl": sl, "tp": tp, "rr": rr, "grade": grade}

# ثوابت GoldRider — من آخر تحليل مستلم (الأسبوعي 2026-10-26، استُلم 2026-10-24). عند وصول تحليل جديد حدّثها هنا فقط.
GR = {"buy_trigger": 4026, "buy_early": 4012, "sell_early": 3977, "sell_trigger": 3966}

report = {
    "price": round(price, 2),
    "atr_m15": round(a_m15, 2),
    "trend": {"H4": t_h4, "H1": t_h1},
    "h4_levels": {"last_high": last_h4_high and round(last_h4_high, 2),
                  "last_low": last_h4_low and round(last_h4_low, 2)},
    "m15_levels": {"last_high": last_m15_high and round(last_m15_high, 2),
                   "last_low": last_m15_low and round(last_m15_low, 2)},
    "bos": ({k: (round(v, 2) if isinstance(v, float) else v) for k, v in bos.items()} if bos else None),
    "retest": ({k: (round(v, 2) if isinstance(v, float) else v) for k, v in retest.items()} if retest else None),
    "signal": ({k: (round(v, 2) if isinstance(v, float) else v) for k, v in signal.items()} if signal else None),
    "goldrider": GR,
}
with open(f"{OUT}/gsr_report.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))

# ---------- الرسم ----------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

fig, ax = plt.subplots(figsize=(14, 7))
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")

data = m15[-150:]
xs = list(range(len(data)))
for i, c in enumerate(data):
    col = "#26a69a" if c["c"] >= c["o"] else "#ef5350"
    ax.plot([i, i], [c["l"], c["h"]], color=col, linewidth=0.8)
    b, t = min(c["o"], c["c"]), max(c["o"], c["c"])
    ax.add_patch(Rectangle((i - 0.35, b), 0.7, max(t - b, 0.05), facecolor=col, edgecolor=col))

def hline(level, color, label, ls="-", alpha=0.9):
    if level:
        ax.axhline(level, color=color, linestyle=ls, linewidth=1.2, alpha=alpha)
        ax.text(len(data) - 1, level, f" {label}", color=color, fontsize=9,
                va="bottom", ha="right", weight="bold")

# مستويات H4 الهيكلية
hline(last_h4_high, "#f0b90b", f"H4 High {last_h4_high:.1f}")
hline(last_h4_low, "#f0b90b", f"H4 Low {last_h4_low:.1f}")
# مستويات GoldRider
for lv, lb in [(GR["buy_trigger"], f"GR Buy {GR['buy_trigger']}"),
               (GR["buy_early"], f"GR EarlyBuy {GR['buy_early']}"),
               (GR["sell_early"], f"GR EarlySell {GR['sell_early']}"),
               (GR["sell_trigger"], f"GR Sell {GR['sell_trigger']}")]:
    hline(lv, "#8b949e", lb, ls="--", alpha=0.6)
# BOS / Retest
if bos:
    bi = bos["idx"] - (len(m15) - len(data))
    if 0 <= bi < len(data):
        ax.axvline(bi, color="#58a6ff", linestyle=":", alpha=0.7)
        ax.annotate(f"BOS {bos['dir']}\n{bos['level']:.1f}", xy=(bi, bos["level"]),
                    color="#58a6ff", fontsize=9, weight="bold")
if retest:
    ri = retest["idx"] - (len(m15) - len(data))
    if 0 <= ri < len(data):
        ax.axvline(ri, color="#d2a8ff", linestyle=":", alpha=0.7)
        ax.annotate("Retest", xy=(ri, m15[retest["idx"]]["c"]),
                    color="#d2a8ff", fontsize=9, weight="bold")
if signal:
    ax.set_title(f"XAUUSD M15 + H4 Structure | {signal['dir']} {signal['grade']}  Entry {signal['entry']:.1f}  SL {signal['sl']:.1f}  TP {signal['tp']:.1f}  RR {signal['rr']:.2f}",
                 color="white", fontsize=11, weight="bold")
else:
    ax.set_title(f"XAUUSD M15 + H4 Structure | Price {price:.1f} | H4: {t_h4} | H1: {t_h1} | No confirmed setup",
                 color="white", fontsize=11, weight="bold")

ax.tick_params(colors="#8b949e", labelsize=8)
# محور زمني بتوقيت دمشق حتى يبان أن البيانات حديثة
tick_idx = list(range(0, len(data), 25))
ax.set_xticks(tick_idx)
ax.set_xticklabels([data[i]["t"][5:16].replace(" ", "\n") for i in tick_idx],
                   color="#8b949e", fontsize=7)
for s in ax.spines.values():
    s.set_color("#30363d")
plt.tight_layout()
plt.savefig(f"{OUT}/gsr_chart.png", dpi=130, facecolor="#0d1117")
print("CHART SAVED")
