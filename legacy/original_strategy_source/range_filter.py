#!/usr/bin/env python3
"""Range Filter — B&S Signals (تحويل حرفي من Pine Script v4 إلى بايثون).

المصدر: Range Filter - B&S Signals (مبني على Range Filter DonovanWall).
الإعدادات الافتراضية: period=20, mult=3.5, المصدر=الإغلاق.

ملاحظات التحويل:
1. ema: بتعريف TradingView (alpha=2/(p+1)، التهيئة بأول قيمة). Pine يستخدم
   SMA لأول length شمعة — الفرق يتلاشى مع الـ warmup، والدوال هنا تتوقع
   تمرير warmup كافٍ (الباكتست يسقط أول 200 شمعة).
2. rng_filt: منطق rfilt التكراري حرفياً — تُنسخ الحالة السابقة أولاً ثم يُختبر
   الشرطان (x-r > prev → x-r) و (x+r < prev → x+r). الشرطان متنافيان
   رياضياً (r>0) فلا تعارض.
3. longCond/shortCond: الشقان في كل OR متكافئان تقريباً — يُختزلان إلى
   (close > filt and fdir==1) إلا في حالة التساوي التام close==close[1]
   (نادرة ببيانات حقيقية). الكود يطبّق الصيغة الحرفية، ودالة التحقق أدناه
   تقيس أي انحراف عن الصيغة المختزلة.
4. CondIni يبدأ 0 — أول إشارة فعلية تتطلب حالة معاكسة سابقة (تناوب صارم).
5. القاعدة الذهبية: كل قيمة عند الفهرس i تُحسب من إغلاقات 0..i فقط —
   لا lookahead. إشارة الشمعة i صالحة للتنفيذ عند إغلاقها.
"""

PERIOD = 20
MULT = 3.5
WARMUP = 200


def ema(vals, p):
    """EMA بتعريف TradingView: alpha=2/(p+1)، التهيئة بأول قيمة."""
    alpha = 2.0 / (p + 1)
    out = [0.0] * len(vals)
    e = vals[0]
    for i, v in enumerate(vals):
        e = v if i == 0 else alpha * v + (1.0 - alpha) * e
        out[i] = e
    return out


def range_size(closes, qty=MULT, n=PERIOD):
    """rng_size: متوسط المدى المطلق مزدوج التمهيد × المضاعف."""
    wper = (n * 2) - 1
    diffs = [0.0] * len(closes)
    for i in range(1, len(closes)):
        diffs[i] = abs(closes[i] - closes[i - 1])
    avrng = ema(diffs, n)
    return [v * qty for v in ema(avrng, wper)]


def range_filter(closes, period=PERIOD, mult=MULT):
    """تُرجع (filt, fdir) لكل شمعة — منطق rfilt التكراري حرفياً."""
    rng = range_size(closes, mult, period)
    filt = [0.0] * len(closes)
    fdir = [0.0] * len(closes)
    prev = closes[0]
    for i, x in enumerate(closes):
        r = rng[i]
        if i == 0:
            f = x  # تهيئة var rfilt = [x, x]
        else:
            f = prev  # نسخ الحالة السابقة أولاً
            if x - r > prev:
                f = x - r
            if x + r < prev:
                f = x + r
        filt[i] = f
        if i > 0:
            if f > filt[i - 1]:
                fdir[i] = 1.0
            elif f < filt[i - 1]:
                fdir[i] = -1.0
            else:
                fdir[i] = fdir[i - 1]
        prev = f
    return filt, fdir


def signals(closes, period=PERIOD, mult=MULT):
    """إشارات الانعكاس فقط: قائمة من (index, 'long'|'short')."""
    filt, fdir = range_filter(closes, period, mult)
    out = []
    cond_ini = 0.0
    prev_cond = 0.0
    for i in range(1, len(closes)):
        c, c1 = closes[i], closes[i - 1]
        f = filt[i]
        up = fdir[i] == 1.0
        dn = fdir[i] == -1.0
        # الصيغة الحرفية من Pine (الشقان كما وردا)
        long_cond = (c > f and c > c1 and up) or (c > f and c < c1 and up)
        short_cond = (c < f and c < c1 and dn) or (c < f and c > c1 and dn)
        if long_cond:
            cond_ini = 1.0
        elif short_cond:
            cond_ini = -1.0
        else:
            cond_ini = prev_cond
        if long_cond and prev_cond == -1.0:
            out.append((i, "long"))
        elif short_cond and prev_cond == 1.0:
            out.append((i, "short"))
        prev_cond = cond_ini
    return out


def check_or_equivalence(closes, period=PERIOD, mult=MULT):
    """تحقق: هل (A∧B∧C)∨(A∧¬B∧C) == (A∧C) على هذه البيانات؟"""
    filt, fdir = range_filter(closes, period, mult)
    div_long = div_short = 0
    for i in range(1, len(closes)):
        c, c1 = closes[i], closes[i - 1]
        f = filt[i]
        up = fdir[i] == 1.0
        dn = fdir[i] == -1.0
        lit_long = (c > f and c > c1 and up) or (c > f and c < c1 and up)
        sim_long = (c > f and up)
        lit_short = (c < f and c < c1 and dn) or (c < f and c > c1 and dn)
        sim_short = (c < f and dn)
        div_long += lit_long != sim_long
        div_short += lit_short != sim_short
    return div_long, div_short


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from candle_db import read
    cs = [r["c"] for r in read(interval="15min", limit=5000)]
    dl, ds = check_or_equivalence(cs)
    print(f"closes={len(cs)} divergences: long={dl} short={ds}")
    sg = signals(cs)
    print(f"signals={len(sg)} first={sg[0] if sg else None} last={sg[-1] if sg else None}")
