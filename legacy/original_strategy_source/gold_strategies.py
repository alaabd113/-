#!/usr/bin/env python3
"""محرك استراتيجيتي الذهب الجديدتين — تكييف من فيديوهات أ ب بورصة (أسهم) إلى XAUUSD.

الاستراتيجية 1: نظام خط الاتجاه (Trendline Swing System) — long-only حسب المصدر.
  القواعد المطبقة حرفياً من الفيديو:
    - خط اتجاه صاعد من قاعين أو أكثر = دعم: شراء عند الارتداد منه.
    - خط اتجاه هابط من قمتين أو أكثر: شراء عند اختراقه.
    - الخروج: كسر الخط الصاعد بإغلاق شمعة تحته.
    - المستهدف: إسقاط عمودي = مسافة أبعد قمة/قاع عن الخط (حد أدنى للمستهدف).
  v2 موحدة (2026-10-17 بقرار علاء — من فيديو إنزو الحلقة 18، تدمج 5 عناصر
  في استراتيجية "كسر خط الاتجاه" واحدة بدل الكسر الفوري):
    1. القناة السعرية: خط موازٍ للترند المكسور يمر بأبعد قمة/قاع مقابلة —
       عرضها هو المستهدف (نفس فكرة "الإسقاط العمودي" في المصدر).
    2. فلتر الزاوية: تقريب رقمي لزاوية 40-45° البصرية (0.04–0.6 ATR/شمعة H4).
    3. تأكيد الفريم اليومي: "الصغير بيحترم الكبير" — إشارة الشراء تُرفض إذا
       الترند اليومي هابط، وإشارة البيع تُرفض إذا الترند اليومي صاعد.
    4. إعادة الاختبار بعد الكسر: لا دخول عند الكسر مباشرة ("ما في بيع أو شراء
       إلا بعد إعادة الاختبار") — الدخول عند أول شمعة H4 تلمس الخط المكسور
       وتغلق على جهة الصفقة، خلال 12 شمعة من الكسر.
    5. الاتجاهين: كسر خط هابط ← شراء، كسر خط صاعد ← بيع.
  فرضيات التكييف للذهب (موثقة هنا وليست من المصدر):
    - الفريم H4 بدل اليومي للأسهم.
    - القيعان/القمم: swing بطول 3 على H4.
    - تسامح اللمس: 0.35 × ATR(H4).
    - الوقف: تحت الخط بـ 0.75 × ATR (المصدر بلا وقف خسارة).
    - تأكيد الارتداد: شمعة H4 مغلقة لمست الخط ثم أغلقت فوقه.
    - تأكيد الاختراق: شمعة H4 مغلقة فوق الخط الهابط.
    - حد أدنى R:R = 2 لقبول التنبيه.

الاستراتيجية 2: MACD + Stochastic — long-only حسب المصدر.
  القواعد المطبقة حرفياً من الفيديو:
    - MACD(12,26,1): خط واحد (signal=1 لإخفاء الخط الأحمر).
    - القوة: خط MACD فوق الصفر وصاعد → مسموح البحث عن شراء فقط.
    - Stochastic(5,9,3): قراءة الفيديو K=5, D=9, تنعيم=3
      (المادة العلمية تكتبه 9,5,3 لكنه يُقرأ 5,9,3 حسب الفيديو).
    - التوقيت: Stochastic ينزل ثم يلتف ويعطي شراء (تقاطع K فوق D).
    - ممنوع الشراء في «مناطق الموت»: MACD تحت الصفر.
  فرضيات التكييف للذهب:
    - «صاعد» = macd[-1] > macd[-2] على H4 (شمعة مغلقة).
    - إشارة الشراء = تقاطع K فوق D خلال آخر شمعتين مغلقتين.
    - الدخول بسعر السوق لحظة التنبيه.
    - الوقف = آخر قاع سوينغ - 0.25×ATR (المصدر بلا وقف).
    - الهدف = 2R (المصدر بلا هدف رقمي ملزم).
    - الخروج (مستنتج من أمثلة الفيديو): تقاطع K تحت D.

المخرجات: gold_strategies.json + gold_strategies.png
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

def ema(vals, p):
    k = 2 / (p + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def sma(vals, p):
    return [sum(vals[i - p + 1:i + 1]) / p if i >= p - 1 else None for i in range(len(vals))]

def atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:period]) / period
    for x in trs[period:]:
        a = (a * (period - 1) + x) / period
    return a

def swings(candles, n=3):
    highs, lows = [], []
    for i in range(n, len(candles) - n):
        h, l = candles[i]["h"], candles[i]["l"]
        if all(h >= candles[j]["h"] for j in range(i - n, i + n + 1) if j != i):
            highs.append((i, h, candles[i]["t"]))
        if all(l <= candles[j]["l"] for j in range(i - n, i + n + 1) if j != i):
            lows.append((i, l, candles[i]["t"]))
    return highs, lows

def multi_targets(entry, sl, tp_strategy):
    """أهداف متعددة: TP1=1R, TP2=2R, TP3=max(3R, هدف الاستراتيجية) — شراء فقط.
    يضمن ترتيباً تصاعدياً دائماً حتى لو تجاوز هدف الاستراتيجية 3R."""
    risk = entry - sl
    if risk <= 0:
        return None
    return {
        "tp1": round(entry + 1 * risk, 2),
        "tp2": round(entry + 2 * risk, 2),
        "tp3": round(max(entry + 3 * risk, tp_strategy), 2),
        "risk": round(risk, 2),
    }

# ---------- البيانات: القاعدة المحلية أساساً، والجلب الحي احتياط ----------
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

h4 = db_candles("4h", 150)
m15 = db_candles("15min", 30)
d1 = db_candles("1day", 80)  # تحيّز v2 اليومي
price = m15[-1]["c"]
now_t = m15[-1]["t"]
a4 = atr(h4)
TOL = 0.35 * a4
closes = [c["c"] for c in h4]
h4h, h4l = swings(h4, 3)

# ---------- خطوط الاتجاه ----------
def ascending_lines():
    lines = []
    L = h4l
    for a in range(len(L)):
        for b in range(a + 1, len(L)):
            i1, p1, _ = L[a]; i2, p2, _ = L[b]
            if p2 <= p1:
                continue
            slope = (p2 - p1) / (i2 - i1)
            touches = 0
            violations = 0
            for (i, p, _) in L:
                if i < i1:
                    continue
                lp = p1 + slope * (i - i1)
                if abs(p - lp) <= TOL:
                    touches += 1
                elif p < lp - TOL:
                    violations += 1
            # فحص الإغلاقات تحت الخط ضمن المدى
            for i in range(i1, min(i2 + 20, len(h4))):
                lp = p1 + slope * (i - i1)
                if h4[i]["c"] < lp - TOL:
                    violations += 1
            if touches >= 2 and violations <= 3:
                lines.append({"i1": i1, "p1": p1, "i2": i2, "p2": p2,
                              "slope": slope, "touches": touches,
                              "span": i2 - i1})
    lines.sort(key=lambda x: (x["touches"], x["span"]), reverse=True)
    return lines

def descending_lines():
    lines = []
    H = h4h
    for a in range(len(H)):
        for b in range(a + 1, len(H)):
            i1, p1, _ = H[a]; i2, p2, _ = H[b]
            if p2 >= p1:
                continue
            slope = (p2 - p1) / (i2 - i1)  # سالب
            touches = 0
            violations = 0
            for (i, p, _) in H:
                if i < i1:
                    continue
                lp = p1 + slope * (i - i1)
                if abs(p - lp) <= TOL:
                    touches += 1
                elif p > lp + TOL:
                    violations += 1
            for i in range(i1, min(i2 + 20, len(h4))):
                lp = p1 + slope * (i - i1)
                if h4[i]["c"] > lp + TOL:
                    violations += 1
            if touches >= 2 and violations <= 3:
                lines.append({"i1": i1, "p1": p1, "i2": i2, "p2": p2,
                              "slope": slope, "touches": touches,
                              "span": i2 - i1})
    lines.sort(key=lambda x: (x["touches"], x["span"]), reverse=True)
    return lines

asc = ascending_lines()
desc = descending_lines()
best_asc = asc[0] if asc else None
best_desc = desc[0] if desc else None

def line_at(line, i):
    return line["p1"] + line["slope"] * (i - line["i1"])

signals = []
sig_idx = len(h4) - 2  # آخر شمعة مغلقة
sc = h4[sig_idx]

# إشارة 1: ارتداد من خط صاعد
tl_reason = None
if best_asc:
    lv = line_at(best_asc, sig_idx)
    touched = sc["l"] <= lv + TOL
    rejected = sc["c"] > lv
    if touched and rejected:
        D = max(h4[i]["h"] - line_at(best_asc, i)
                for i in range(best_asc["i1"], sig_idx + 1))
        entry = price
        sl = lv - 0.75 * a4
        tp = lv + D
        risk = entry - sl
        rr = (tp - entry) / risk if risk > 0 else 0
        if rr >= 2:
            tg = multi_targets(entry, sl, tp)
            signals.append({
                "strategy": "خط الاتجاه — ارتداد",
                "dir": "شراء",
                "entry": round(entry, 2), "sl": round(sl, 2),
                "tp": round(tp, 2), "rr": round(rr, 2),
                "tp1": tg["tp1"], "tp2": tg["tp2"], "tp3": tg["tp3"],
                "risk": tg["risk"],
                "key": f"TL-BOUNCE|{sc['t']}",
                "t": sc["t"],
                "reason": (f"ارتداد من خط اتجاه صاعد ({best_asc['touches']} لمسات) "
                           f"عند {lv:.1f} — إغلاق شمعة H4 فوق الخط"),
                "line": {"kind": "صاعد", "level_now": round(lv, 2),
                         "touches": best_asc["touches"]},
                "assumptions": "وقف 0.75×ATR وR:R≥2 فرضيات تكييف (المصدر بلا وقف)",
            })
    tl_reason = (f"خط صاعد ({best_asc['touches']} لمسات) عند {lv:.1f} — "
                 f"{'السعر لمسه' if touched else 'السعر بعيد عنه'}")

# ---------- استراتيجية كسر خط الاتجاه الموحدة v2 (2026-10-17) ----------
# تدمج 5 عناصر في إشارة واحدة: القناة + فلتر الزاوية + تأكيد اليومي +
# إعادة الاختبار + الاتجاهين. تحل محل "الكسر الفوري" القديم نهائياً.
def detect_lines(candles, pts, tol, rising):
    """كشف خطوط الاتجاه معمّم (نفس منطق ascending/descending الأصلي)."""
    lines = []
    for a in range(len(pts)):
        for b in range(a + 1, len(pts)):
            i1, p1, _ = pts[a]; i2, p2, _ = pts[b]
            if rising and p2 <= p1:
                continue
            if not rising and p2 >= p1:
                continue
            slope = (p2 - p1) / (i2 - i1)
            touches = 0
            violations = 0
            for (i, p, _) in pts:
                if i < i1:
                    continue
                lp = p1 + slope * (i - i1)
                if abs(p - lp) <= tol:
                    touches += 1
                elif rising and p < lp - tol:
                    violations += 1
                elif not rising and p > lp + tol:
                    violations += 1
            for i in range(i1, min(i2 + 20, len(candles))):
                lp = p1 + slope * (i - i1)
                cc = candles[i]["c"]
                if rising and cc < lp - tol:
                    violations += 1
                elif not rising and cc > lp + tol:
                    violations += 1
            if touches >= 2 and violations <= 3:
                lines.append({"i1": i1, "p1": p1, "i2": i2, "p2": p2,
                              "slope": slope, "touches": touches,
                              "span": i2 - i1})
    lines.sort(key=lambda x: (x["touches"], x["span"]), reverse=True)
    return lines

def angle_ok(slope, atr_v, lo=0.008, hi=0.08):
    """فلتر الزاوية: تقريب رقمي لزاوية ~40-45° البصرية (الميل بوحدة ATR/شمعة H4).
    عُيّر تجريبياً 2026-10-17: خطوط H4 الحقيقية تتراوح 0.003–0.06 —
    يُرفض المسطّح (<0.008: مستوى أفقي متنكر) والحاذّ (>0.08: انفجاري)."""
    return lo <= abs(slope) / atr_v <= hi

def build_channel(line, candles, i_from, i_to, side):
    """القناة السعرية: خط موازٍ للترند يمر بأبعد قمة/قاع مقابلة."""
    if side == "buy":  # خط هابط مكسور: القناة تمر بأدنى قاع
        ie, pe = min(((i, candles[i]["l"]) for i in range(i_from, i_to + 1)),
                     key=lambda x: x[1])
    else:  # خط صاعد مكسور: القناة تمر بأعلى قمة
        ie, pe = max(((i, candles[i]["h"]) for i in range(i_from, i_to + 1)),
                     key=lambda x: x[1])
    width = abs(line_at(line, ie) - pe)
    return {"ie": ie, "pe": pe, "slope": line["slope"],
            "width": round(width, 2)}

# تحيّز الفريم اليومي — "الصغير بيحترم الكبير"
d1a = atr(d1)
d1_tol = 0.35 * d1a
d1h, d1l = swings(d1, 3)
d1_asc = detect_lines(d1, d1l, d1_tol, True)
d1_desc = detect_lines(d1, d1h, d1_tol, False)
d1c = d1[-2]  # آخر شمعة يومية مغلقة
daily_bias = "محايد"
if d1_asc and d1c["c"] > line_at(d1_asc[0], len(d1) - 2):
    daily_bias = "صاعد"
elif d1_desc and d1c["c"] < line_at(d1_desc[0], len(d1) - 2):
    daily_bias = "هابط"

# ---------- طور 1: كشف الكسر لحظة حدوثه ----------
# الخطوط تُكتشف على الشموع المغلقة فقط (دون آخر شمعتين) حتى لا يبتلع
# نافذةُ فحص المخالفات شمعةَ الكسر نفسها.
V2_STATE = os.path.join(OUT, "tl_break_pending.json")
h4det = h4[:sig_idx - 1]
det_h, det_l = swings(h4det, 3)
det_desc = detect_lines(h4det, det_h, TOL, False)
det_asc = detect_lines(h4det, det_l, TOL, True)
v2_desc = next((l for l in det_desc if angle_ok(l["slope"], a4)), None)
v2_asc = next((l for l in det_asc if angle_ok(l["slope"], a4)), None)

try:
    pend = json.load(open(V2_STATE, encoding="utf-8"))
    if not isinstance(pend, list):
        pend = []
except Exception:
    pend = []

def _line_id(line):
    return f"{line['i1']}|{round(line['p1'], 2)}|{round(line['slope'], 4)}"

for side, line in (("buy", v2_desc), ("sell", v2_asc)):
    if not line:
        continue
    lid = _line_id(line)
    if any(p.get("line_id") == lid and p["side"] == side for p in pend):
        continue  # كسر معلق مسبقاً لنفس الخط
    for ci in (sig_idx - 1, sig_idx):
        lv = line_at(line, ci)
        c = h4[ci]
        broken = (c["c"] > lv + TOL) if side == "buy" else (c["c"] < lv - TOL)
        if broken:
            pend.append({"key": f"{side}|{c['t']}", "side": side,
                         "line_id": lid, "line": line,
                         "break_i": ci, "break_t": c["t"]})
            break

# ---------- طور 2: انتظار إعادة الاختبار ----------
v2_draw = []  # (line, channel, side) للرسم
keep = []
for p in pend:
    line, side = p["line"], p["side"]
    b = p["break_i"]
    outcome = None
    for j in range(b + 1, sig_idx + 1):
        lj = line_at(line, j)
        cj = h4[j]
        if side == "buy":
            if cj["c"] < lj - TOL:
                outcome = ("fail", j)
                break
            if cj["l"] <= lj + TOL and cj["c"] > lj:
                outcome = ("retest", j)
                break
        else:
            if cj["c"] > lj + TOL:
                outcome = ("fail", j)
                break
            if cj["h"] >= lj - TOL and cj["c"] < lj:
                outcome = ("retest", j)
                break
    if outcome and outcome[0] == "retest":
        j = outcome[1]
        rlv = line_at(line, j)
        go = not ((side == "buy" and daily_bias == "هابط") or
                  (side == "sell" and daily_bias == "صاعد"))
        if go:
            chan = build_channel(line, h4, line["i1"], b, side)
            entry = price
            sl = entry - 0.75 * a4 if side == "buy" else entry + 0.75 * a4
            tp = entry + chan["width"] if side == "buy" else entry - chan["width"]
            risk = abs(entry - sl)
            rr = chan["width"] / risk if risk > 0 else 0
            if rr >= 2 and chan["width"] > 0:
                if side == "buy":
                    tg = {"tp1": round(entry + 1 * risk, 2),
                          "tp2": round(entry + 2 * risk, 2),
                          "tp3": round(max(entry + 3 * risk, tp), 2),
                          "risk": round(risk, 2)}
                    reason = (f"كسر خط هابط ({line['touches']} لمسات) ثم إعادة اختبار "
                              f"عند {rlv:.1f} — تحيّز اليومي: {daily_bias} — "
                              f"عرض القناة {chan['width']:.1f}")
                else:
                    tg = {"tp1": round(entry - 1 * risk, 2),
                          "tp2": round(entry - 2 * risk, 2),
                          "tp3": round(min(entry - 3 * risk, tp), 2),
                          "risk": round(risk, 2)}
                    reason = (f"كسر خط صاعد ({line['touches']} لمسات) ثم إعادة اختبار "
                              f"عند {rlv:.1f} — تحيّز اليومي: {daily_bias} — "
                              f"عرض القناة {chan['width']:.1f}")
                signals.append({
                    "strategy": "خط الاتجاه — اختراق",
                    "dir": "شراء" if side == "buy" else "بيع",
                    "entry": round(entry, 2), "sl": round(sl, 2),
                    "tp": round(tp, 2), "rr": round(rr, 2),
                    "tp1": tg["tp1"], "tp2": tg["tp2"], "tp3": tg["tp3"],
                    "risk": tg["risk"],
                    "key": f"TL-BREAK-V2|{h4[j]['t']}|{side}",
                    "t": h4[j]["t"],
                    "reason": reason,
                    "line": {"kind": "هابط" if side == "buy" else "صاعد",
                             "level_now": round(rlv, 2),
                             "touches": line["touches"]},
                    "channel": {"width": chan["width"]},
                    "assumptions": ("v2 موحدة 2026-10-17 (فيديو إنزو): كسر+إعادة اختبار، "
                                    "فلتر زاوية، تأكيد يومي، قناة سعرية، اتجاهين — "
                                    "وقف 0.75×ATR فرضية تكييف"),
                })
                v2_draw.append((line, chan, side))
        continue  # مستهلكة سواء أُشيرت أم رُفضت بالفلاتر
    if outcome and outcome[0] == "fail":
        continue  # كسر فاشل — تُسقط
    if sig_idx - b > 12 or abs(price - line_at(line, sig_idx)) > 2 * a4:
        continue  # انتهت الصلاحية: لا عودة خلال 12 شمعة أو ابتعد السعر
    keep.append(p)

with open(V2_STATE, "w", encoding="utf-8") as f:
    json.dump(keep, f, ensure_ascii=False)

# ---------- MACD + Stochastic ----------
e12 = ema(closes, 12)
e26 = ema(closes, 26)
macd = [a - b for a, b in zip(e12, e26)]
macd_now, macd_prev = macd[-2], macd[-3]
strength = macd_now > 0 and macd_now > macd_prev

rawk = []
for i in range(len(h4)):
    win = h4[max(0, i - 4):i + 1]
    hh = max(c["h"] for c in win); ll = min(c["l"] for c in win)
    rawk.append(100 * (h4[i]["c"] - ll) / (hh - ll) if hh > ll else 50)
k_s = sma(rawk, 3)
kval = [x for x in k_s if x is not None]
d_s = sma(kval, 9)
K = k_s[-2] if len(k_s) >= 2 else None
Kprev = k_s[-3] if len(k_s) >= 3 else None
Darr = [x for x in d_s if x is not None]
D = Darr[-1] if Darr else None
Dprev = Darr[-2] if len(Darr) >= 2 else None

stoch_buy = False
if None not in (K, Kprev, D, Dprev):
    # تقاطع K فوق D خلال آخر شمعتين مغلقتين (نزول ثم التفاف)
    k2, k3 = k_s[-2], k_s[-3]
    d2 = Darr[-1]
    d3 = Darr[-2] if len(Darr) >= 2 else None
    if d3 is not None and k3 is not None:
        stoch_buy = (k2 > d2 and k3 <= d3)
    # فحص الشمعة السابقة أيضاً
    if not stoch_buy and len(k_s) >= 4 and len(Darr) >= 3:
        k3b, k4b = k_s[-3], k_s[-4]
        d2b, d3b = Darr[-2], Darr[-3]
        if None not in (k3b, k4b, d2b, d3b):
            stoch_buy = (k3b > d2b and k4b <= d3b)

ms_reason = (f"MACD {macd_now:.2f} {'فوق الصفر وصاعد ✓' if strength else 'ليس في قوة شرائية'} | "
             f"Stoch K={K:.1f} D={D:.1f} {'تقاطع شراء ✓' if stoch_buy else 'بلا إشارة شراء'}"
             if None not in (K, D) else "Stoch غير محسوب")

if strength and stoch_buy:
    swing_low = h4l[-1][1] if h4l else min(c["l"] for c in h4[-20:])
    entry = price
    sl = swing_low - 0.25 * a4
    risk = entry - sl
    tp = entry + 2 * risk
    rr = 2.0
    if risk > 0:
        tg = multi_targets(entry, sl, tp)
        signals.append({
            "strategy": "MACD + Stochastic",
            "dir": "شراء",
            "entry": round(entry, 2), "sl": round(sl, 2),
            "tp": round(tp, 2), "rr": round(rr, 2),
            "tp1": tg["tp1"], "tp2": tg["tp2"], "tp3": tg["tp3"],
            "risk": tg["risk"],
            "key": f"MS|{sc['t']}",
            "t": sc["t"],
            "reason": (f"MACD فوق الصفر وصاعد ({macd_now:.2f}) + "
                       f"تقاطع Stochastic شرائي (K={K:.1f} فوق D={D:.1f})"),
            "assumptions": "وقف=قاع سوينغ-0.25×ATR وهدف=2R فرضيات تكييف (المصدر بلا وقف/هدف)",
        })

# ركن «خط الاتجاه — ارتداد» بقرار علاء 2026-10-24 (حزمة الركن): تُسجَّل
# بسجل الظل للقياس فقط — لا دفتر ولا تنبيه ولا مرآة. «خط الاتجاه — اختراق»
# تبقى فعّالة كما هي.
_parked_tl = [s for s in signals if s["strategy"] == "خط الاتجاه — ارتداد"]
if _parked_tl:
    try:
        with open(os.path.join(OUT, "shadow_signals.jsonl"), "a") as _f:
            for _s in _parked_tl:
                _f.write(json.dumps(
                    {"ts": now_t, "reason": "parked",
                     "strategy": _s["strategy"], "dir": _s["dir"],
                     "entry": _s["entry"], "sl": _s["sl"],
                     "tp1": _s.get("tp1"), "tp2": _s.get("tp2"),
                     "tp3": _s.get("tp3"),
                     "risk_usd": round(abs(_s["entry"] - _s["sl"]), 2)},
                    ensure_ascii=False) + "\n")
    except Exception:
        pass
    signals = [s for s in signals if s["strategy"] != "خط الاتجاه — ارتداد"]

# حارس الحداثة (قرار علاء 2026-10-23): إسقاط أي إشارة تجاوز السعر الحي
# هدفها الأول أو وقفها أو ابتعد عن دخولها أكثر من مخاطرة واحدة قبل التسجيل
from freshness import filter_fresh
signals, dropped_stale = filter_fresh(signals, mode="market")

report = {
    "time": now_t, "price": round(price, 2), "atr_h4": round(a4, 2),
    "signals": signals,
    "dropped_stale": dropped_stale,
    "trendline": {
        "asc": bool(best_asc),
        "asc_detail": tl_reason,
        "desc": bool(best_desc),
    },
    "macd_stoch": {
        "macd": round(macd_now, 3), "macd_rising": macd_now > macd_prev,
        "strength": strength,
        "stoch_k": round(K, 1) if K is not None else None,
        "stoch_d": round(D, 1) if D is not None else None,
        "stoch_buy": stoch_buy,
        "detail": ms_reason,
    },
}
with open(f"{OUT}/gold_strategies.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

# ---------- الرسم ----------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

fig, (ax, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 9),
                                   gridspec_kw={"height_ratios": [3, 1, 1]})
fig.patch.set_facecolor("#0d1117")
for a in (ax, ax2, ax3):
    a.set_facecolor("#0d1117")

data = h4[-90:]
off = len(h4) - len(data)
for i, c in enumerate(data):
    col = "#26a69a" if c["c"] >= c["o"] else "#ef5350"
    ax.plot([i, i], [c["l"], c["h"]], color=col, linewidth=0.8)
    b, t = min(c["o"], c["c"]), max(c["o"], c["c"])
    ax.add_patch(Rectangle((i - 0.35, b), 0.7, max(t - b, 0.05),
                           facecolor=col, edgecolor=col))

# خطوط الاتجاه
for line, col, lb in [(best_asc, "#f0b90b", "خط صاعد"),
                      (best_desc, "#d2a8ff", "خط هابط")]:
    if line:
        xs = [line["i1"] - off, len(data) + 8]
        ys = [line_at(line, line["i1"]), line_at(line, len(h4) + 8)]
        ax.plot(xs, ys, color=col, linewidth=1.6, linestyle="--")
        ax.text(xs[1], ys[1], f" {lb} ({line['touches']} لمسات)",
                color=col, fontsize=9, weight="bold", va="center")

# قنوات استراتيجية الكسر الموحدة v2: الخط المكسور + ظله الموازي
for line, chan, side in v2_draw:
    col = "#f0b90b" if side == "buy" else "#d2a8ff"
    xs = [line["i1"] - off, len(data) + 8]
    ys = [line_at(line, line["i1"]), line_at(line, len(h4) + 8)]
    ax.plot(xs, ys, color=col, linewidth=1.5)
    cxs = [chan["ie"] - off, len(data) + 8]
    cys = [chan["pe"], chan["pe"] + chan["slope"] * (len(h4) + 8 - chan["ie"])]
    ax.plot(cxs, cys, color=col, linewidth=1.0, linestyle=":", alpha=0.85)
    ax.text(cxs[1], cys[1], f" قناة v2 (عرض {chan['width']})",
            color=col, fontsize=8, va="center")

# إشارات
for s in signals:
    ax.axhline(s["entry"], color="#58a6ff", linewidth=1.4)
    ax.axhline(s["sl"], color="#ef5350", linewidth=1.2, linestyle=":")
    ax.axhline(s["tp"], color="#26a69a", linewidth=1.2, linestyle=":")
    ax.text(len(data) - 1, s["entry"],
            f" {s['strategy']}: دخول {s['entry']} وقف {s['sl']} هدف {s['tp']}",
            color="#58a6ff", fontsize=9, weight="bold", va="bottom", ha="right")

# MACD
ax2.plot(range(len(data)), macd[off:], color="#58a6ff", linewidth=1.2)
ax2.axhline(0, color="#8b949e", linewidth=0.8)
ax2.set_ylabel("MACD(12,26,1)", color="#8b949e", fontsize=8)
ax2.text(len(data) - 1, macd[-1],
         f" {'قوة شرائية' if strength else 'ليس قوة'}",
         color="#26a69a" if strength else "#ef5350",
         fontsize=9, weight="bold", va="bottom", ha="right")

# Stochastic
kval_full = [x for x in k_s[off:] if x is not None]
d_full = [x for x in d_s[max(0, off - 8):] if x is not None]
ax3.plot(range(len(data) - len(kval_full), len(data)), kval_full,
         color="#f0b90b", linewidth=1.1, label="%K")
if d_full:
    ax3.plot(range(len(data) - len(d_full), len(data)), d_full,
             color="#d2a8ff", linewidth=1.1, label="%D")
ax3.axhline(80, color="#ef5350", linewidth=0.7, linestyle=":")
ax3.axhline(20, color="#26a69a", linewidth=0.7, linestyle=":")
ax3.set_ylabel("Stoch(5,9,3)", color="#8b949e", fontsize=8)
ax3.legend(fontsize=7, loc="upper left", facecolor="#0d1117", labelcolor="white")

if signals:
    title = "XAUUSD H4 · " + " + ".join(
        f"{s['strategy']} {s['dir']} {s['entry']}" for s in signals)
else:
    title = (f"XAUUSD H4 · استراتيجيات جديدة | السعر {price:.1f} | "
             f"لا إشارات جديدة — {tl_reason or ''} | {ms_reason}")
ax.set_title(title, color="white", fontsize=11, weight="bold")

for a in (ax, ax2, ax3):
    a.tick_params(colors="#8b949e", labelsize=8)
    for s in a.spines.values():
        s.set_color("#30363d")
ax.set_xticks(range(0, len(data), 15))
ax.set_xticklabels([data[i]["t"][5:16].replace(" ", "\n")
                    for i in range(0, len(data), 15)],
                   color="#8b949e", fontsize=7)
plt.tight_layout()
plt.savefig(f"{OUT}/gold_strategies.png", dpi=130, facecolor="#0d1117")
print("STRATEGIES DONE")
print(json.dumps(report, ensure_ascii=False)[:2500])
