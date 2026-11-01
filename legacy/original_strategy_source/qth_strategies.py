#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""محركات QIMMA × TALARIA × HERMES للذهب — XAUUSD عبر TwelveData حصراً.
20 استراتيجية: 16 الأصلية + 4 من الأرشيف (نسخة 2026-10-15 المرحلة الأولى):
TURTLE_SOUP_XAU + SECOND_FVG_ENTRY_GOLD + BLACKGOLD_EAT_8AM + GOLD_VIDEO6_SPATIAL_CONFLUENCE،
مع فلتر اتجاه Wilder ADX14 وطبقة تأكيد أنماط علاء الدين.
المفتاح يُقرأ من ~/.config/goldstation/twelvedata_key — لا يُكتب في الكود.
المخرجات: qth_strategies.json + qth_strategies.png
ملاحظات أمانة:
- V31_PRECISION_SCALP يعمل بوضع M15 تقريبي (الأصل M5/M1 للدخول).
- PAT_ORB وBLACKGOLD_EAT_8AM: بلاك غولد أصبح منفذاً (صندوق = الشمعة [-4] حسب صيغة المصدر).
- حوكمة قاطع الدائرة/سقف الصفقات تحتاج قاعدة بيانات حية — غير مفعّلة هنا (الدفتر الورقي يتولى التتبع).
- فلتر ADX يرفض فقط الإشارات المعاكسة لترند قوي (ADX>=25) — لا يمنع إشارات جديدة بحد ذاته.
"""
import json, os, urllib.request, datetime as dt
from zoneinfo import ZoneInfo

KEY = open(os.path.expanduser("~/.config/goldstation/twelvedata_key")).read().strip()
DAM = ZoneInfo("Asia/Damascus")
NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
OUT = os.path.expanduser("~/workspace/gold-station")

FAMILY_RR = {"SCALP_INTRADAY": 1.5, "STRUCTURAL_SMC": 2.0, "CORE_HERMES_TALARIA": 2.5,
             "MACRO_KNOCKOUT_TRAP": 3.0, "PROP_FIRM_CHALLENGE": 4.0}

def td(interval, outputsize):
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}"
           f"&outputsize={outputsize}&order=ASC&timezone=Asia/Damascus&apikey={KEY}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "values" not in data:
        raise RuntimeError(str(data)[:200])
    out = []
    for v in data["values"]:
        o, h, l, c = float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])
        rng = h - l
        bd = abs(c - o)
        ts_raw = v["datetime"]
        if len(ts_raw) == 10:  # D1 returns date-only ("YYYY-MM-DD")
            ts_raw = ts_raw + " 00:00:00"
        ts = int(dt.datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=DAM).timestamp())
        out.append({"t": ts_raw, "ts": ts, "o": o, "h": h, "l": l, "c": c,
                    "range": rng, "body": bd, "body_ratio": bd / rng if rng > 0 else 0.0,
                    "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
                    "bull": c > o, "bear": c < o})
    return out


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

def get_d1():
    return db_candles("1day", 80)

# ---------- نواة الخوارزميات (نفس صيغ المصدر حرفياً) ----------
def atr(cs, p=14):
    if len(cs) < 2:
        return cs[-1]["range"] if cs else 1.0
    trs = [max(cs[i]["h"] - cs[i]["l"], abs(cs[i]["h"] - cs[i-1]["c"]),
               abs(cs[i]["l"] - cs[i-1]["c"])) for i in range(1, len(cs))]
    window = trs[-p:] if len(trs) >= p else trs
    return max(sum(window) / len(window), 1e-6)

def ema_last(vals, p):
    k = 2 / (p + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e

def fractal_swings(cs, left=1, right=1):
    highs, lows = [], []
    n = len(cs)
    for i in range(left, n - right):
        h, l = cs[i]["h"], cs[i]["l"]
        if all(h > cs[j]["h"] for j in range(i - left, i + right + 1) if j != i):
            highs.append((i, h))
        if all(l < cs[j]["l"] for j in range(i - left, i + right + 1) if j != i):
            lows.append((i, l))
    return highs, lows

def four_point_ms(cs):
    highs, lows = fractal_swings(cs, 1, 1)
    pts = sorted([(i, "H", p) for i, p in highs] + [(i, "L", p) for i, p in lows])
    if len(pts) < 4:
        return "UNDEFINED"
    for end in range(len(pts), 3, -1):
        seq = pts[end-4:end]
        kinds = [x[1] for x in seq]
        if kinds == ["L", "H", "L", "H"]:
            p1, p2, p3, p4 = seq
            if p3[2] > p1[2] and p4[2] > p2[2]:
                return "BULLISH"
        elif kinds == ["H", "L", "H", "L"]:
            p1, p2, p3, p4 = seq
            if p3[2] < p1[2] and p4[2] < p2[2]:
                return "BEARISH"
    return "CONSOLIDATION"

def detect_cisd_level(cs, sweep_idx, direction):
    if sweep_idx < 0 or sweep_idx >= len(cs):
        return None
    run = []
    for c in reversed(cs[:sweep_idx + 1]):
        if direction == "BUY" and c["bear"]:
            run.append(c)
        elif direction == "SELL" and c["bull"]:
            run.append(c)
        else:
            break
    return run[-1]["o"] if run else None

def ipda_20_40_60(d1):
    if len(d1) < 20:
        return None
    s20, s40 = d1[-20:], d1[-40:] if len(d1) >= 40 else d1[-20:]
    s60 = d1[-60:] if len(d1) >= 60 else s40
    h20, l20 = max(c["h"] for c in s20), min(c["l"] for c in s20)
    h60, l60 = max(c["h"] for c in s60), min(c["l"] for c in s60)
    eq20 = l20 + 0.5 * (h20 - l20)
    dol_dir = "SELL" if d1[-1]["c"] < eq20 else "BUY"
    return {"h20": h20, "l20": l20, "eq20": eq20, "h60": h60, "l60": l60,
            "dol_direction": dol_dir, "dol_target": l60 if dol_dir == "SELL" else h60}

def dynamic_quadrant(price, low, high):
    if high <= low:
        return "Q_INVALID"
    pos = (price - low) / (high - low)
    if pos <= 0.25: return "Q1_DEEP_DISCOUNT"
    if pos <= 0.50: return "Q2_EQUILIBRIUM_DISCOUNT"
    if pos <= 0.75: return "Q3_EQUILIBRIUM_PREMIUM"
    return "Q4_DEEP_PREMIUM"

def check_killzone(ts):
    t = dt.datetime.fromtimestamp(ts, tz=NY).time()
    if dt.time(2, 0) <= t <= dt.time(5, 0): return True, "LONDON_KILLZONE"
    if dt.time(7, 0) <= t <= dt.time(10, 0): return True, "NY_KILLZONE"
    if dt.time(20, 0) <= t <= dt.time(22, 30): return True, "ASIA_KILLZONE"
    return False, "OUT_OF_KILLZONE"

def ha_confirm(cs, direction, doji_max=0.18):
    if len(cs) < 3:
        return {"aligned": False}
    bars = []
    for c in cs:
        hc = (c["o"] + c["h"] + c["l"] + c["c"]) / 4.0
        ho = (c["o"] + c["c"]) / 2.0 if not bars else (bars[-1][0] + bars[-1][3]) / 2.0
        color = "GREEN" if hc > ho else ("RED" if hc < ho else "NEUTRAL")
        bars.append((ho, max(c["h"], ho, hc), min(c["l"], ho, hc), hc, color))
    expected = "GREEN" if direction == "BUY" else "RED"
    return {"aligned": bars[-1][4] == expected,
            "exhaustion": cs[-2]["body_ratio"] <= doji_max,
            "color": bars[-1][4]}

def mk(sid, fam, direction, entry, sl, tp1, tp2, rr, t, reason, note="", etype=""):
    risk = abs(entry - sl)
    return {"strategy": sid, "family": fam, "dir": direction, "entry": round(entry, 2),
            "sl": round(sl, 2), "tp1": round(tp1, 2), "tp2": round(tp2, 2),
            "tp3": round(tp2, 2), "rr": round(rr, 2), "risk": round(risk, 2),
            "r1": round(abs(tp1 - entry) / risk, 1) if risk > 0 else 0.0,
            "r2": round(abs(tp2 - entry) / risk, 1) if risk > 0 else 0.0,
            "entry_type": etype, "key": f"{sid}|{t}|{round(entry, 2)}", "t": t,
            "reason": reason, "note": note}

# ================= محركات Hermes (الصيغ الأصلية) =================
def eval_hermes_pcr(d1, m15):
    if len(d1) < 4:
        return None
    b1, b2, b3, b4 = d1[-4], d1[-3], d1[-2], d1[-1]
    if (b2["h"] > b1["h"] and b2["l"] < b1["l"]) or (b3["h"] > b2["h"] and b3["l"] < b2["l"]):
        return None
    ltf_close = m15[-1]["c"]
    if b2["h"] > b1["h"] and b2["h"] > b3["h"]:
        if b4["h"] > b2["h"]:
            return None
        dol = round(b3["l"], 2)
        stop = round(b2["h"] + 0.30, 2)
        rng = max(b2["h"] - dol, 1.0)
        entry = round(dol + 0.72 * rng, 2)
        risk = max(stop - entry, 0.4)
        rr = round((entry - dol) / risk, 2)
        if rr >= 2.5 and abs(ltf_close - entry) <= rng * 0.25:
            return mk("HERMES_PCR", "CORE_HERMES_TALARIA", "بيع", entry, stop, dol,
                      round(dol - risk, 2), rr, b4["t"],
                      f"سوينغ D1 هابط عند {b2['h']:.1f} — الدخول المحسّن {entry:.1f} والهدف سيولة {dol:.1f}",
                      "LIMIT — دخول معلق محسّن", "LIMIT")
    if b2["l"] < b1["l"] and b2["l"] < b3["l"]:
        if b4["l"] < b2["l"]:
            return None
        dol = round(b3["h"], 2)
        stop = round(b2["l"] - 0.30, 2)
        rng = max(dol - b2["l"], 1.0)
        entry = round(dol - 0.72 * rng, 2)
        risk = max(entry - stop, 0.4)
        rr = round((dol - entry) / risk, 2)
        if rr >= 2.5 and abs(ltf_close - entry) <= rng * 0.25:
            return mk("HERMES_PCR", "CORE_HERMES_TALARIA", "شراء", entry, stop, dol,
                      round(dol + risk, 2), rr, b4["t"],
                      f"سوينغ D1 صاعد عند {b2['l']:.1f} — الدخول المحسّن {entry:.1f} والهدف سيولة {dol:.1f}",
                      "LIMIT — دخول معلق محسّن", "LIMIT")
    return None

def eval_hermes_sac(m15):
    if len(m15) < 6:
        return None
    c1, c2, last = m15[-3], m15[-2], m15[-1]
    if c2["l"] < c1["l"] and c2["c"] > c1["h"] and c2["body_ratio"] >= 0.45:
        if last["l"] < c2["l"]:
            return None
        cisd = detect_cisd_level(m15, len(m15) - 2, "BUY")
        cisd_ok = True if cisd is None else (last["c"] > cisd)
        target = round(max(c2["h"], c1["h"] + c2["range"] * 0.8), 2)
        stop = round(c2["l"] - 0.20, 2)
        entry = round(min(c1["h"], c2["l"] + c2["range"] * 0.28), 2)
        risk = max(entry - stop, 0.3)
        rr = round((target - entry) / risk, 2)
        if cisd_ok and rr >= 2.5:
            return mk("HERMES_SAC", "CORE_HERMES_TALARIA", "شراء", entry, stop, target,
                      round(entry + risk * 3.5, 2), rr, c2["t"],
                      f"سحب قاع {c1['l']:.1f} وإغلاق فوق {c1['h']:.1f} بجسم قوي — الدخول المحسّن {entry:.1f}",
                      "LIMIT — عند إعادة الاختبار", "LIMIT")
    if c2["h"] > c1["h"] and c2["c"] < c1["l"] and c2["body_ratio"] >= 0.45:
        if last["h"] > c2["h"]:
            return None
        cisd = detect_cisd_level(m15, len(m15) - 2, "SELL")
        cisd_ok = True if cisd is None else (last["c"] < cisd)
        target = round(min(c2["l"], c1["l"] - c2["range"] * 0.8), 2)
        stop = round(c2["h"] + 0.20, 2)
        entry = round(max(c1["l"], c2["h"] - c2["range"] * 0.28), 2)
        risk = max(stop - entry, 0.3)
        rr = round((entry - target) / risk, 2)
        if cisd_ok and rr >= 2.5:
            return mk("HERMES_SAC", "CORE_HERMES_TALARIA", "بيع", entry, stop, target,
                      round(entry - risk * 3.5, 2), rr, c2["t"],
                      f"سحب قمة {c1['h']:.1f} وإغلاق تحت {c1['l']:.1f} بجسم قوي — الدخول المحسّن {entry:.1f}",
                      "LIMIT — عند إعادة الاختبار", "LIMIT")
    return None

def eval_hermes_snake(m15):
    if len(m15) < 3:
        return None
    prev_bar, curr = m15[-2], m15[-1]
    elapsed = 0.25
    if elapsed > 0.3333:
        return None
    if curr["h"] > prev_bar["h"] and curr["c"] <= prev_bar["h"] and curr["o"] < curr["c"]:
        entry, stop, target = round(curr["c"], 2), round(curr["h"] + 0.20, 2), round(curr["o"], 2)
        risk = max(stop - entry, 0.2)
        rr = round((entry - target) / risk, 2)
        if rr >= 1.5:
            return mk("HERMES_SNAKE", "SCALP_INTRADAY", "بيع", entry, stop, target,
                      round(target - risk * 0.5, 2), rr, curr["t"],
                      f"سحب قمة {prev_bar['h']:.1f} بالثلث الأول والعودة تحتها — الهدف الافتتاح {target:.1f}",
                      "", "MARKET_ON_CLOSE")
    if curr["l"] < prev_bar["l"] and curr["c"] >= prev_bar["l"] and curr["o"] > curr["c"]:
        entry, stop, target = round(curr["c"], 2), round(curr["l"] - 0.20, 2), round(curr["o"], 2)
        risk = max(entry - stop, 0.2)
        rr = round((target - entry) / risk, 2)
        if rr >= 1.5:
            return mk("HERMES_SNAKE", "SCALP_INTRADAY", "شراء", entry, stop, target,
                      round(target + risk * 0.5, 2), rr, curr["t"],
                      f"سحب قاع {prev_bar['l']:.1f} بالثلث الأول والعودة فوقه — الهدف الافتتاح {target:.1f}",
                      "", "MARKET_ON_CLOSE")
    return None

def eval_hermes_wick(m15):
    if len(m15) < 16:
        return None
    a = atr(m15)
    pre, disp, retest = m15[-3], m15[-2], m15[-1]
    is_disp = disp["body_ratio"] >= 0.65 and disp["range"] >= 1.3 * a
    if pre["upper_wick"] >= pre["range"] * 0.45 and pre["upper_wick"] >= 0.6 * a and is_disp and disp["bear"]:
        wick_mid = round(max(pre["o"], pre["c"]) + pre["upper_wick"] * 0.50, 2)
        if disp["c"] < wick_mid:
            if retest["c"] > pre["h"] and retest["bull"]:
                entry, sl = round(retest["c"], 2), round(wick_mid - 0.30, 2)
                risk = max(entry - sl, 0.5)
                return mk("HERMES_WICK", "CORE_HERMES_TALARIA", "شراء", entry, sl,
                          round(entry + risk * 2.5, 2), round(entry + risk * 3.5, 2),
                          2.5, retest["t"],
                          f"انقلاب حتمي: إغلاق كامل فوق ذيل {pre['h']:.1f} — نقطة انطلاق صاعدة",
                          "", "MARKET_ON_CLOSE")
            if retest["h"] >= wick_mid and retest["c"] <= wick_mid:
                entry, sl = wick_mid, round(pre["h"] + 0.30, 2)
                risk = max(sl - entry, 0.4)
                return mk("HERMES_WICK", "CORE_HERMES_TALARIA", "بيع", entry, sl,
                          round(entry - risk * 2.5, 2), round(entry - risk * 3.5, 2),
                          2.5, retest["t"],
                          f"ذيل علوي بارز {pre['h']:.1f} خلف إزاحة هابطة — ارتداد بيعي من المنتصف {wick_mid:.1f}",
                          "LIMIT — منتصف الذيل", "LIMIT")
    if pre["lower_wick"] >= pre["range"] * 0.45 and pre["lower_wick"] >= 0.6 * a and is_disp and disp["bull"]:
        wick_mid = round(pre["l"] + pre["lower_wick"] * 0.50, 2)
        if disp["c"] > wick_mid:
            if retest["c"] < pre["l"] and retest["bear"]:
                entry, sl = round(retest["c"], 2), round(wick_mid + 0.30, 2)
                risk = max(sl - entry, 0.5)
                return mk("HERMES_WICK", "CORE_HERMES_TALARIA", "بيع", entry, sl,
                          round(entry - risk * 2.5, 2), round(entry - risk * 3.5, 2),
                          2.5, retest["t"],
                          f"انقلاب حتمي: إغلاق كامل تحت ذيل {pre['l']:.1f} — انعكاس للبيع",
                          "", "MARKET_ON_CLOSE")
            if retest["l"] <= wick_mid and retest["c"] >= wick_mid:
                entry, sl = wick_mid, round(pre["l"] - 0.30, 2)
                risk = max(entry - sl, 0.4)
                return mk("HERMES_WICK", "CORE_HERMES_TALARIA", "شراء", entry, sl,
                          round(entry + risk * 2.5, 2), round(entry + risk * 3.5, 2),
                          2.5, retest["t"],
                          f"ذيل سفلي بارز {pre['l']:.1f} خلف إزاحة صاعدة — ارتداد شرائي من المنتصف {wick_mid:.1f}",
                          "LIMIT — منتصف الذيل", "LIMIT")
    return None

def eval_hermes_siren(m15, h1):
    if len(m15) < 30 or len(h1) < 20:
        return None
    if four_point_ms(h1[-25:]) != "BEARISH":
        return None
    highs, lows = fractal_swings(m15[-25:], 1, 1)
    if len(lows) < 2 or len(highs) < 1:
        return None
    last = m15[-1]
    a = atr(m15)
    retail_low, poi_high = lows[-1][1], highs[-1][1]
    if last["c"] < retail_low and last["bear"] and (poi_high - last["c"]) > a * 0.8:
        entry, sl = round(last["c"], 2), round(poi_high + 0.25, 2)
        risk = max(sl - entry, 0.5)
        return mk("HERMES_SIREN", "MACRO_KNOCKOUT_TRAP", "بيع", entry, sl,
                  round(entry - risk * 3.0, 2), round(entry - risk * 4.0, 2),
                  3.0, last["t"],
                  f"كسر قاع تجزئي {retail_low:.1f} بإغلاق هابط بهيكل H1 هابط — فخ السيولة",
                  "", "LIMIT")
    return None

# ================= محركات Talaria (الصيغ الأصلية) =================
def eval_talaria_l6_unicorn(m15, h1, d1):
    if len(m15) < 35 or len(h1) < 25:
        return None
    ipda = ipda_20_40_60(d1 if len(d1) >= 20 else h1)
    last = m15[-1]
    if ipda:
        dol_dir, dol_target = ipda["dol_direction"], ipda["dol_target"]
    else:
        dol_dir = "BUY" if four_point_ms(h1[-25:]) == "BULLISH" else "SELL"
        dol_target = last["c"] + atr(m15) * 5.0 if dol_dir == "BUY" else last["c"] - atr(m15) * 5.0
    highs, lows = fractal_swings(m15[-30:], 2, 2)
    if dol_dir == "BUY" and len(highs) >= 2 and len(lows) >= 2:
        breaker_lvl, sweep_low, prev_low = highs[-1][1], lows[-1][1], lows[-2][1]
        c1, c2, c3 = m15[-3], m15[-2], m15[-1]
        fvg_bull = c2["bull"] and c3["l"] > c1["h"]
        if sweep_low < prev_low and fvg_bull and c1["h"] <= breaker_lvl <= c3["l"] * 1.002:
            entry = round(breaker_lvl, 2)
            sl = round(min(c1["l"], sweep_low) - 0.30, 2)
            risk = max(entry - sl, 0.5)
            tp1 = round(entry + risk * 2.5, 2)
            tp2 = round(max(dol_target, entry + risk * 4.0), 2)
            return mk("TALARIA_L6_UNICORN", "CORE_HERMES_TALARIA", "شراء", entry, sl, tp1, tp2,
                      2.5, c3["t"],
                      f"سحب {sweep_low:.1f} ثم كسر {breaker_lvl:.1f} مع فجوة — باتجاه سيولة IPDA {dol_target:.1f}",
                      "LIMIT — عند القمة المكسورة", "LIMIT")
    return None

def eval_talaria_l7_osok(h1, weekly_taken):
    if weekly_taken or len(h1) < 50:
        return None
    last = h1[-1]
    h_week = max(c["h"] for c in h1[-50:])
    l_week = min(c["l"] for c in h1[-50:])
    quad = dynamic_quadrant(last["c"], l_week, h_week)
    in_kz, kz_name = check_killzone(last["ts"])
    cbdr = h1[-12:-6]
    cbdr_high = max(c["h"] for c in cbdr)
    cbdr_low = min(c["l"] for c in cbdr)
    if quad in ("Q1_DEEP_DISCOUNT", "Q2_EQUILIBRIUM_DISCOUNT") and last["bull"] and last["c"] > cbdr_high:
        entry = round(last["c"], 2)
        sl = round(min(cbdr_low, l_week) - 0.50, 2)
        risk = max(entry - sl, 1.0)
        sym127 = round(l_week + 1.27 * (h_week - l_week), 2)
        sym162 = round(l_week + 1.62 * (h_week - l_week), 2)
        tp1 = max(sym127, round(entry + risk * 3.0, 2))
        tp2 = max(sym162, round(entry + risk * 4.5, 2))
        rr = round((tp1 - entry) / risk, 2)
        if rr >= 3.0 and in_kz:
            return mk("TALARIA_L7_OSOK", "MACRO_KNOCKOUT_TRAP", "شراء", entry, sl, tp1, tp2,
                      rr, last["t"],
                      f"إغلاق صاعد فوق CBDR {cbdr_high:.1f} من {quad} داخل {kz_name} — الضربة الأسبوعية",
                      "", "LIMIT")
    return None

def eval_talaria_v31_scalp(m15):
    if len(m15) < 25:
        return None
    trend = four_point_ms(m15[-25:])
    if trend not in ("BULLISH", "BEARISH"):
        return None
    direction = "BUY" if trend == "BULLISH" else "SELL"
    ha = ha_confirm(m15[-10:], direction)
    last = m15[-1]
    a = atr(m15)
    highs, lows = fractal_swings(m15[-15:], 1, 1)
    if direction == "BUY" and ha["aligned"] and highs and lows:
        if last["c"] > highs[-1][1]:
            entry = round(last["c"], 2)
            sl = round(lows[-1][1] - max(0.20, a * 0.10), 2)
            risk = max(entry - sl, 0.3)
            return mk("TALARIA_V31_SCALP", "SCALP_INTRADAY", "شراء", entry, sl,
                      round(entry + risk * 1.5, 2), round(entry + risk * 2.0, 2),
                      1.5, last["t"],
                      f"هيكل M15 صاعد + كسر فراكتل {highs[-1][1]:.1f} مع Heikin Ashi {ha['color']} — سكالبينغ",
                      "وضع M15 تقريبي (الأصل M5/M1)", "MARKET_ON_CLOSE")
    if direction == "SELL" and ha["aligned"] and highs and lows:
        if last["c"] < lows[-1][1]:
            entry = round(last["c"], 2)
            sl = round(highs[-1][1] + max(0.20, a * 0.10), 2)
            risk = max(sl - entry, 0.3)
            return mk("TALARIA_V31_SCALP", "SCALP_INTRADAY", "بيع", entry, sl,
                      round(entry - risk * 1.5, 2), round(entry - risk * 2.0, 2),
                      1.5, last["t"],
                      f"هيكل M15 هابط + كسر فراكتل {lows[-1][1]:.1f} مع Heikin Ashi {ha['color']} — سكالبينغ",
                      "وضع M15 تقريبي (الأصل M5/M1)", "MARKET_ON_CLOSE")
    return None

def eval_talaria_gold_breakout(m15):
    if len(m15) < 55:
        return None
    last = m15[-1]
    prev20 = m15[-21:-1]
    high20 = max(c["h"] for c in prev20)
    low20 = min(c["l"] for c in prev20)
    e50 = ema_last([c["c"] for c in m15], 50)
    a14 = atr(m15)
    if last["c"] > high20 and last["c"] > e50 and last["body"] > 0.5 * a14:
        entry = round(last["c"], 2)
        sl = round(max(last["l"], entry - 1.5 * a14), 2)
        risk = entry - sl
        if 1.0 * a14 <= risk <= 4.0 * a14:
            return mk("TALARIA_GOLD_BREAKOUT", "CORE_HERMES_TALARIA", "شراء", entry, sl,
                      round(entry + risk * 2.5, 2), round(entry + risk * 3.5, 2),
                      2.5, last["t"],
                      f"اختراق أعلى 20 شمعة {high20:.1f} فوق EMA50 {e50:.1f} بجسم قوي",
                      "", "MARKET_ON_CLOSE")
    if last["c"] < low20 and last["c"] < e50 and last["body"] > 0.5 * a14:
        entry = round(last["c"], 2)
        sl = round(min(last["h"], entry + 1.5 * a14), 2)
        risk = sl - entry
        if 1.0 * a14 <= risk <= 4.0 * a14:
            return mk("TALARIA_GOLD_BREAKOUT", "CORE_HERMES_TALARIA", "بيع", entry, sl,
                      round(entry - risk * 2.5, 2), round(entry - risk * 3.5, 2),
                      2.5, last["t"],
                      f"كسر أدنى 20 شمعة {low20:.1f} تحت EMA50 {e50:.1f} بجسم قوي",
                      "", "MARKET_ON_CLOSE")
    return None

# ================= محركات QIMMA Core (الصيغ الأصلية) =================
def eval_prop_firm_breakout(m15, h4):
    if len(m15) < 40:
        return None
    last = m15[-1]
    window = m15[-35:]
    sh_arr, sl_arr = fractal_swings(window[:-3], 2, 2)
    if len(sl_arr) >= 2 and len(sh_arr) >= 1:
        (pli, plp), (sli, slp) = sl_arr[-2], sl_arr[-1]
        if slp < plp and sli > pli:
            after = [sh for sh in sh_arr if sh[0] > sli]
            if after:
                sh_idx, shv = after[-1]
                wave = shv - slp
                if wave > 0.5:
                    ztop = shv - wave * 0.50
                    zbot = shv - wave * 0.618
                    fstop = shv - wave * 0.786
                    brk_ok, wick_sweep = False, False
                    for k in range(sh_idx + 1, len(window) - 1):
                        ck, pk = window[k], window[k - 1]
                        if ck["h"] > shv and ck["c"] <= shv:
                            wick_sweep = True
                        if ck["c"] > shv and ck["h"] > pk["h"] and ck["bull"]:
                            brk_ok = True
                            break
                    if brk_ok and not wick_sweep and zbot <= last["l"] <= ztop and last["c"] >= zbot:
                        entry = round(last["c"], 2)
                        sl = round(min(fstop, entry - 1.5), 2)
                        risk = max(entry - sl, 0.5)
                        return mk("PROP_FIRM_BREAKOUT", "PROP_FIRM_CHALLENGE", "شراء", entry, sl,
                                  round(entry + risk * 4.0, 2), round(entry + risk * 5.0, 2),
                                  5.0, last["t"],
                                  f"سحب {slp:.1f} ثم كسر {shv:.1f} بإغلاق نظيف — إعادة اختبار فيبو 50-61.8%",
                                  "", "MARKET_ON_CLOSE")
    return None

def eval_fvg_four_rules(m15, h4):
    if len(m15) < 40 or len(h4) < 20:
        return None
    last = m15[-1]
    a = atr(m15)
    ms = four_point_ms(h4[-25:])
    htf_dir = "BUY" if ms == "BULLISH" else ("SELL" if ms == "BEARISH" else "NEUTRAL")
    for i in range(len(m15) - 3, max(len(m15) - 18, 2), -1):
        c1, c2, c3 = m15[i - 2], m15[i - 1], m15[i]
        if htf_dir == "BUY" and c2["bull"] and c3["l"] > c1["h"] and c2["body"] >= 0.45 * a:
            third_ok = not (c3["bear"] and c3["body"] > c2["body"] * 0.8)
            mitigated = any(m15[k]["l"] <= c1["h"] for k in range(i + 1, len(m15)))
            if third_ok and not mitigated and c1["h"] <= last["c"] <= c3["l"] * 1.001:
                entry = round((c1["h"] + c3["l"]) * 0.5, 2)
                sl = round(c1["l"] - a * 0.3, 2)
                risk = max(entry - sl, 0.5)
                return mk("FVG_FOUR_RULES", "CORE_HERMES_TALARIA", "شراء", entry, sl,
                          round(entry + risk * 2.5, 2), round(entry + risk * 4.0, 2),
                          2.5, last["t"],
                          f"فجوة صاعدة {c1['h']:.1f}-{c3['l']:.1f} بمحاذاة H4 الصاعد — الدخول منتصف الفجوة",
                          "LIMIT — منتصف الفجوة", "LIMIT")
    return None

def eval_alaa_smc_gold(m15, h4):
    if len(m15) < 40:
        return None
    if four_point_ms(m15[-40:]) != "BULLISH":
        return None
    a = atr(m15)
    highs, lows = fractal_swings(m15[-40:], 2, 2)
    if not highs or not lows:
        return None
    sh, slp = highs[-1][1], lows[-1][1]
    wave = abs(sh - slp)
    last, prev = m15[-1], m15[-2]
    bull_eng = last["bull"] and prev["bear"] and last["c"] >= prev["o"] and last["body"] > prev["body"]
    hammer = last["lower_wick"] >= last["body"] * 1.8 and last["upper_wick"] <= last["body"] * 0.6
    if wave > a * 1.5:
        f50 = sh - wave * 0.50
        f786 = sh - wave * 0.786
        if f786 <= last["l"] <= f50 and (bull_eng or hammer):
            entry = round(last["c"], 2)
            stop = round(min(slp, f786 - a * 0.25), 2)
            risk = max(entry - stop, 0.5)
            return mk("ALAA_SMC_GOLD", "STRUCTURAL_SMC", "شراء", entry, stop,
                      round(entry + risk * 2.0, 2), round(entry + risk * 3.5, 2),
                      2.0, last["t"],
                      f"هيكل صاعد + المنطقة الذهبية {f786:.1f}-{f50:.1f} مع شمعة تأكيد انعكاسية",
                      "", "MARKET_ON_CLOSE")
    return None

def eval_crt_cisd_gold(m15):
    if len(m15) < 20:
        return None
    c1, c2, c3 = m15[-3], m15[-2], m15[-1]
    sw_low, sw_high = c2["l"] < c1["l"], c2["h"] > c1["h"]
    if sw_low and sw_high:
        return None
    if sw_low and c1["l"] <= c2["c"] <= c1["h"] and c3["c"] > max(c2["o"], c2["c"]):
        cisd = round(max(c2["o"], c2["c"]), 2)
        sl = round(c2["l"] - 0.20, 2)
        risk = max(cisd - sl, 0.4)
        tp1 = round(max(c1["h"], cisd + risk * 2.0), 2)
        rr = round((tp1 - cisd) / risk, 2)
        return mk("CRT_CISD_GOLD", "STRUCTURAL_SMC", "شراء", cisd, sl, tp1,
                  round(cisd + risk * 3.5, 2), rr, c3["t"],
                  f"سحب نطاق {c1['l']:.1f} وإغلاق تسليم فوق {cisd:.1f} — الدخول معلق عند CISD",
                  "LIMIT — عند مستوى CISD", "LIMIT")
    if sw_high and c1["l"] <= c2["c"] <= c1["h"] and c3["c"] < min(c2["o"], c2["c"]):
        cisd = round(min(c2["o"], c2["c"]), 2)
        sl = round(c2["h"] + 0.20, 2)
        risk = max(sl - cisd, 0.4)
        tp1 = round(min(c1["l"], cisd - risk * 2.0), 2)
        rr = round((cisd - tp1) / risk, 2)
        return mk("CRT_CISD_GOLD", "STRUCTURAL_SMC", "بيع", cisd, sl, tp1,
                  round(cisd - risk * 3.5, 2), rr, c3["t"],
                  f"سحب نطاق {c1['h']:.1f} وإغلاق تسليم تحت {cisd:.1f} — الدخول معلق عند CISD",
                  "LIMIT — عند مستوى CISD", "LIMIT")
    return None

def eval_htf_fib50_weekly(h1, h4):
    if len(h1) < 25 or len(h4) < 20:
        return None
    last = h1[-1]
    e50 = ema_last([c["c"] for c in h1], 50)
    hh, ll = fractal_swings(h4[-25:], 1, 1)
    if not hh or not ll:
        return None
    h4h, h4l = hh[-1][1], ll[-1][1]
    rng = max(h4h - h4l, 1.0)
    fib50 = h4l + rng * 0.50
    if last["c"] > e50 and abs(last["l"] - fib50) <= rng * 0.15 and last["bull"]:
        entry = round(last["c"], 2)
        sl = round(min(last["l"] - 1.5, h4l + rng * 0.30), 2)
        risk = max(entry - sl, 1.0)
        return mk("HTF_FIB50_WEEKLY", "STRUCTURAL_SMC", "شراء", entry, sl,
                  round(max(h4h, entry + risk * 2.0), 2), round(entry + risk * 3.5, 2),
                  2.0, last["t"],
                  f"إغلاق H1 فوق EMA50 {e50:.1f} عند فيبو 50% لسوينغ H4 ({fib50:.1f})",
                  "", "MARKET_ON_CLOSE")
    return None

# ================= بروفايلات الجلسات (الصيغ الأصلية) =================
def eval_silver_bullet(m15):
    if len(m15) < 30:
        return None
    last = m15[-1]
    nyh = dt.datetime.fromtimestamp(last["ts"], tz=NY).hour
    c1, c2, c3 = m15[-3], m15[-2], m15[-1]
    if (nyh == 10 or nyh == 14) and c2["bull"] and c3["l"] > c1["h"]:
        entry = round((c1["h"] + c3["l"]) * 0.5, 2)
        sl = round(c1["l"] - 0.30, 2)
        risk = max(entry - sl, 0.4)
        return mk("SILVER_BULLET", "STRUCTURAL_SMC", "شراء", entry, sl,
                  round(entry + risk * 2.0, 2), round(entry + risk * 3.0, 2),
                  2.0, last["t"],
                  f"فجوة صاعدة {c1['h']:.1f}-{c3['l']:.1f} داخل نافذة سيلفر بوليت (نيويورك)",
                  "LIMIT — منتصف الفجوة", "LIMIT")
    return None

def eval_asia_sweep(m15):
    if len(m15) < 30:
        return None
    last = m15[-1]
    asia = [c for c in m15[-30:]
            if 0 <= dt.datetime.fromtimestamp(c["ts"], tz=UTC).hour < 7]
    if not asia:
        return None
    ah = max(c["h"] for c in asia)
    al = min(c["l"] for c in asia)
    if al > 0 and last["l"] < al and last["c"] >= al and last["bull"]:
        entry = round(last["c"], 2)
        sl = round(last["l"] - 0.30, 2)
        risk = max(entry - sl, 0.5)
        return mk("ASIA_SWEEP", "STRUCTURAL_SMC", "شراء", entry, sl,
                  round(max(ah, entry + risk * 2.5), 2), round(entry + risk * 3.5, 2),
                  2.5, last["t"],
                  f"سحب قاع آسيا {al:.1f} والإغلاق داخله — الهدف قمة آسيا {ah:.1f}",
                  "", "MARKET_ON_CLOSE")
    return None

# ================= محركات الأرشيف الجديدة (نسخة 2026-10-15 — المرحلة الأولى) =================
def eval_turtle_soup_xau(m15):
    """TURTLE_SOUP_XAU: سحب سيولة فركتلية بالذيل دون إغلاق خلفها + فلتر Killzone.
    المصدر: MasterHermesAndSourceDispatcher._evaluate_turtle_soup_xau (حزمة علاء)."""
    if len(m15) < 20:
        return None
    last = m15[-1]
    highs, lows = fractal_swings(m15[:-1], 1, 1)
    if not highs or not lows:
        return None
    pool_high, pool_low = highs[-1][1], lows[-1][1]
    a = atr(m15)
    in_kz, session = check_killzone(last["ts"])
    if not in_kz:
        return None
    tick = 0.01
    swept_low = last["l"] < pool_low and last["c"] > pool_low
    swept_high = last["h"] > pool_high and last["c"] < pool_high
    if swept_low:
        entry = round(last["c"], 2)
        sl = round(last["l"] - max(tick * 3, a * 0.15), 2)
        risk = max(entry - sl, tick * 10)
        return mk("TURTLE_SOUP_XAU", "MACRO_KNOCKOUT_TRAP", "شراء", entry, sl,
                  round(entry + risk * 3.0, 2), round(entry + risk * 3.0, 2),
                  3.0, last["t"],
                  f"سحب سيولة قاع فركتلي {pool_low:.1f} بالذيل دون إغلاق تحته داخل {session}",
                  "", "MARKET_ON_CLOSE")
    if swept_high:
        entry = round(last["c"], 2)
        sl = round(last["h"] + max(tick * 3, a * 0.15), 2)
        risk = max(sl - entry, tick * 10)
        return mk("TURTLE_SOUP_XAU", "MACRO_KNOCKOUT_TRAP", "بيع", entry, sl,
                  round(entry - risk * 3.0, 2), round(entry - risk * 3.0, 2),
                  3.0, last["t"],
                  f"سحب سيولة قمة فركتلية {pool_high:.1f} بالذيل دون إغلاق فوقها داخل {session}",
                  "", "MARKET_ON_CLOSE")
    return None

def _find_aligned_fvgs(m15, h4):
    """فجوات غير مُخففة بمحاذاة اتجاه H4 — مشتركة بين FVG_FOUR_RULES والثانية."""
    ms = four_point_ms(h4[-25:])
    htf_dir = "BUY" if ms == "BULLISH" else ("SELL" if ms == "BEARISH" else None)
    if not htf_dir:
        return [], None
    a = atr(m15)
    out = []
    for i in range(len(m15) - 3, max(len(m15) - 35, 2), -1):
        c1, c2, c3 = m15[i - 2], m15[i - 1], m15[i]
        if htf_dir == "BUY" and c2["bull"] and c3["l"] > c1["h"] and c2["body"] >= 0.45 * a:
            mitigated = any(m15[k]["l"] <= c1["h"] for k in range(i + 1, len(m15)))
            if not mitigated:
                out.append({"i": i, "top": c3["l"], "bot": c1["h"], "dir": "BUY"})
        elif htf_dir == "SELL" and c2["bear"] and c1["l"] > c3["h"] and c2["body"] >= 0.45 * a:
            mitigated = any(m15[k]["h"] >= c1["l"] for k in range(i + 1, len(m15)))
            if not mitigated:
                out.append({"i": i, "top": c1["l"], "bot": c3["h"], "dir": "SELL"})
    return out, htf_dir

def eval_second_fvg_entry(m15, h4):
    """SECOND_FVG_ENTRY_GOLD: الدخول على الفجوة الثانية بعد احترام الأولى.
    المصدر: _evaluate_fvg_four_rules_and_second (حزمة علاء) — منطق حتمي كامل."""
    if len(m15) < 40 or len(h4) < 20:
        return None
    last = m15[-1]
    a = atr(m15)
    fvgs, htf_dir = _find_aligned_fvgs(m15, h4)
    if len(fvgs) < 2:
        return None
    z = fvgs[-2]
    if htf_dir == "BUY":
        third_ok = not (last["bear"] and last["body"] > a * 0.8)
        if not third_ok:
            return None
        entry = round((z["top"] + z["bot"]) * 0.5, 2)
        sl = round(z["bot"] - a * 0.35, 2)
        risk = max(entry - sl, 0.5)
        return mk("SECOND_FVG_ENTRY_GOLD", "STRUCTURAL_SMC", "شراء", entry, sl,
                  round(entry + risk * 2.5, 2), round(entry + risk * 2.5, 2),
                  2.5, last["t"],
                  f"الفجوة الثانية الصاعدة {z['bot']:.1f}-{z['top']:.1f} بعد احترام الأولى بمحاذاة H4",
                  "LIMIT — منتصف الفجوة الثانية", "LIMIT")
    else:
        third_ok = not (last["bull"] and last["body"] > a * 0.8)
        if not third_ok:
            return None
        entry = round((z["top"] + z["bot"]) * 0.5, 2)
        sl = round(z["top"] + a * 0.35, 2)
        risk = max(sl - entry, 0.5)
        return mk("SECOND_FVG_ENTRY_GOLD", "STRUCTURAL_SMC", "بيع", entry, sl,
                  round(entry - risk * 2.5, 2), round(entry - risk * 2.5, 2),
                  2.5, last["t"],
                  f"الفجوة الثانية الهابطة {z['bot']:.1f}-{z['top']:.1f} بعد احترام الأولى بمحاذاة H4",
                  "LIMIT — منتصف الفجوة الثانية", "LIMIT")

def eval_blackgold_eat_8am(m15):
    """BLACKGOLD_EAT_8AM: كسر صندوق ORB (الشمعة [-4] كصندوق مرجعي — صيغة المصدر).
    المصدر: QimmaArchiveEnginesV4 — الهندسة (دخول/وقف/هدف) مكتملة هندسياً هنا لأن
    المصدر يعطي الاتجاه فقط."""
    if len(m15) < 15:
        return None
    last = m15[-1]
    a = atr(m15)
    box = m15[-4]
    box_w = box["range"]
    if box_w > a * 2.0:
        return None
    if last["c"] > box["h"]:
        entry = round(last["c"], 2)
        sl = round(box["l"] - 0.30, 2)
        risk = max(entry - sl, 0.5)
        # تشديد بقرار علاء 2026-10-17: TP1=1.5R وTP2=2.5R نهائي (إغلاق كامل عنده)
        return mk("BLACKGOLD_EAT_8AM", "STRUCTURAL_SMC", "شراء", entry, sl,
                  round(entry + risk * 1.5, 2), round(entry + risk * 2.5, 2),
                  1.5, last["t"],
                  f"كسر صندوق ORB {box['l']:.1f}-{box['h']:.1f} للأعلى وإغلاق فوقه",
                  "", "MARKET_ON_CLOSE")
    if last["c"] < box["l"]:
        entry = round(last["c"], 2)
        sl = round(box["h"] + 0.30, 2)
        risk = max(sl - entry, 0.5)
        # تشديد بقرار علاء 2026-10-17: TP1=1.5R وTP2=2.5R نهائي (إغلاق كامل عنده)
        return mk("BLACKGOLD_EAT_8AM", "STRUCTURAL_SMC", "بيع", entry, sl,
                  round(entry - risk * 1.5, 2), round(entry - risk * 2.5, 2),
                  1.5, last["t"],
                  f"كسر صندوق ORB {box['l']:.1f}-{box['h']:.1f} للأسفل وإغلاق تحته",
                  "", "MARKET_ON_CLOSE")
    return None

def eval_video6_spatial_confluence(h1, m15):
    """GOLD_VIDEO6_SPATIAL_CONFLUENCE: تقاطع فيبو 61.8% + مستوى أفقي + منطقة أصل 35%.
    المصدر: نسخة الـ extensions (تشترط spatial_overlap) — أدق من نسخة الماستر."""
    if len(h1) < 25 or len(m15) < 25:
        return None
    last = m15[-1]
    seg = h1[-25:]
    sh = max(c["h"] for c in seg)
    wlow = min(c["l"] for c in seg)
    wave = max(sh - wlow, 1.0)
    fib50 = sh - wave * 0.50
    fib618 = sh - wave * 0.618
    fib65 = sh - wave * 0.65
    zone_35_ok = wave >= atr(h1) * 1.35
    horiz = (fib50 + fib618) * 0.5
    spatial_overlap = abs(fib618 - horiz) <= max(wave * 0.12, 2.5)
    if not (zone_35_ok and spatial_overlap):
        return None
    direction = "BUY" if last["c"] >= fib65 else "SELL"
    if direction == "BUY":
        entry = round(fib618, 2)
        sl = round(wlow - max(wave * 0.15, 1.5), 2)
        risk = max(entry - sl, 0.5)
        tp = round(sh + wave * 0.272, 2)
        rr = round(abs(tp - entry) / risk, 2)
        return mk("GOLD_VIDEO6_SPATIAL_CONFLUENCE", "STRUCTURAL_SMC", "شراء", entry, sl,
                  tp, round(tp + risk, 2), rr, last["t"],
                  f"تقاطع فيبو 61.8% ({fib618:.1f}) مع المستوى الأفقي ومنطقة الأصل على H1",
                  "LIMIT — عند 61.8%", "LIMIT")
    else:
        entry = round(fib618, 2)
        sl = round(sh + max(wave * 0.15, 1.5), 2)
        risk = max(sl - entry, 0.5)
        tp = round(wlow - wave * 0.272, 2)
        rr = round(abs(tp - entry) / risk, 2)
        return mk("GOLD_VIDEO6_SPATIAL_CONFLUENCE", "STRUCTURAL_SMC", "بيع", entry, sl,
                  tp, round(tp - risk, 2), rr, last["t"],
                  f"تقاطع فيبو 61.8% ({fib618:.1f}) مع المستوى الأفقي ومنطقة الأصل على H1",
                  "LIMIT — عند 61.8%", "LIMIT")

def wilder_dmi_adx(cs, p=14):
    """Wilder DMI/ADX14 بالتنعيم الأصلي — المصدر: QimmaArchiveEnginesV4.wilder_dmi_adx.
    يُستخدم كفلتر اتجاه (لا كمحرك مستقل)."""
    n = len(cs)
    if n < p * 2 + 1:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0, "bias": "NEUTRAL_DI"}
    trs, pdm, mdm = [], [], []
    for i in range(1, n):
        curr, prev = cs[i], cs[i - 1]
        up, down = curr["h"] - prev["h"], prev["l"] - curr["l"]
        trs.append(max(curr["h"] - curr["l"], abs(curr["h"] - prev["c"]), abs(curr["l"] - prev["c"])))
        pdm.append(up if (up > down and up > 0) else 0.0)
        mdm.append(down if (down > up and down > 0) else 0.0)
    tr_s = sum(trs[:p]); p_s = sum(pdm[:p]); m_s = sum(mdm[:p])
    dxs = []
    p_di = m_di = 0.0
    for idx in range(p, len(trs)):
        if idx > p:
            tr_s = tr_s - tr_s / p + trs[idx]
            p_s = p_s - p_s / p + pdm[idx]
            m_s = m_s - m_s / p + mdm[idx]
        p_di = 100.0 * p_s / max(tr_s, 1e-9)
        m_di = 100.0 * m_s / max(tr_s, 1e-9)
        denom = p_di + m_di
        dxs.append(0.0 if denom <= 1e-9 else 100.0 * abs(p_di - m_di) / denom)
    adx = sum(dxs[:p]) / p
    for d in dxs[p:]:
        adx = (adx * (p - 1) + d) / p
    bias = "BULLISH_DI" if p_di > m_di else ("BEARISH_DI" if m_di > p_di else "NEUTRAL_DI")
    return {"adx": round(adx, 2), "plus_di": round(p_di, 2), "minus_di": round(m_di, 2), "bias": bias}

def detect_alaa_chart_patterns(m15):
    """أنماط علاء الدين (قمة/قاع مزدوج، H&S معكوس، Flip Zone) — طبقة تأكيد فقط.
    المصدر: CompleteForensicExtensions.detect_alaa_chart_patterns_and_flip_zones."""
    if len(m15) < 45:
        return {}
    seg = m15[-45:]
    highs, lows = fractal_swings(seg, 2, 2)
    a = atr(m15)
    last = m15[-1]
    out = {}
    if len(lows) >= 2 and len(highs) >= 1:
        l1, l2 = lows[-2][1], lows[-1][1]
        if abs(l1 - l2) <= a * 0.35 and last["c"] > highs[-1][1]:
            out["double_bottom"] = True
    if len(highs) >= 2 and len(lows) >= 1:
        h1, h2 = highs[-2][1], highs[-1][1]
        if abs(h1 - h2) <= a * 0.35 and last["c"] < lows[-1][1]:
            out["double_top"] = True
    if len(lows) >= 3:
        ls, head, rs = lows[-3][1], lows[-2][1], lows[-1][1]
        if head < ls and head < rs and abs(ls - rs) <= a * 0.6:
            out["inv_hs"] = True
    if len(highs) >= 2:
        old_res = highs[-2][1]
        if last["c"] > old_res and abs(last["l"] - old_res) <= a * 0.3:
            out["flip_support"] = round(old_res, 2)
    return out

# ================= التشغيل: نفس توصيلات المنسق الأصلي =================
def v31_gate(sig, cur_close, a14):
    if sig["rr"] < FAMILY_RR.get(sig["family"], 2.0):
        return False
    if abs(sig["entry"] - cur_close) / max(a14, 1e-6) > 3.0:
        return False
    if abs(sig["tp1"] - sig["entry"]) < 3.0:
        return False
    return True

def enrich_inplace(raw):
    """توحيد صيغة الشموع: القاعدة تعطي خاماً (t/o/h/l/c) بينما td()‎ يعطي
    مُثرى — نضيف نفس الحقول المشتقة لكليهما."""
    for v in raw:
        if "body_ratio" in v:
            continue
        o, h, l, c = v["o"], v["h"], v["l"], v["c"]
        rng = h - l
        bd = abs(c - o)
        ts_raw = v["t"]
        v["ts"] = int(dt.datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=DAM).timestamp())
        v["range"] = rng
        v["body"] = bd
        v["body_ratio"] = bd / rng if rng > 0 else 0.0
        v["upper_wick"] = h - max(o, c)
        v["lower_wick"] = min(o, c) - l
        v["bull"] = c > o
        v["bear"] = c < o
    return raw

def main():
    from market_hours import require_market_open
    require_market_open()  # السوق مغلق = خروج صامت بلا أي طلب API (بأمر علاء 2026-10-17)
    now = dt.datetime.now(DAM).strftime("%Y-%m-%d %H:%M:%S")
    m15 = enrich_inplace(db_candles("15min", 150))
    h1 = enrich_inplace(db_candles("1h", 120))
    h4 = enrich_inplace(db_candles("4h", 100))
    d1 = enrich_inplace(get_d1())
    C = {"m15": m15, "h1": h1, "h4": h4, "d1": d1}
    price = m15[-1]["c"]
    a14 = atr(m15)
    state_path = os.path.join(OUT, "qth-state.json")
    try:
        state = json.load(open(state_path))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    week = dt.datetime.now(DAM).strftime("%Y-W%V")
    raw = [
        eval_hermes_pcr(d1, m15),
        eval_hermes_sac(m15),
        eval_hermes_snake(m15),
        eval_hermes_wick(m15),
        eval_hermes_siren(m15, h1),
        eval_talaria_l6_unicorn(m15, h1, d1),
        eval_talaria_l7_osok(h1, state.get("osok_week") == week),
        eval_talaria_v31_scalp(m15),
        eval_talaria_gold_breakout(m15),
        eval_prop_firm_breakout(m15, h4),
        eval_fvg_four_rules(m15, h4),
        eval_alaa_smc_gold(m15, h4),
        eval_crt_cisd_gold(m15),
        eval_htf_fib50_weekly(h1, h4),
        eval_silver_bullet(m15),
        eval_asia_sweep(m15),
        # --- المرحلة الأولى: محركات الأرشيف الجديدة (نسخة 2026-10-15) ---
        eval_turtle_soup_xau(m15),
        eval_second_fvg_entry(m15, h4),
        eval_blackgold_eat_8am(m15),
        eval_video6_spatial_confluence(h1, m15),
    ]
    sigs = [s for s in raw if s and v31_gate(s, price, a14)]
    # إيقاف مؤقت بقرار علاء 2026-10-17: استراتيجيات خاسرة باستمرار لا تُنبَّه
    # (الصفقات المفتوحة منها تبقى قيد التتبع في الدفتر — الإيقاف للإشارات الجديدة فقط)
    # 2026-10-20 بقرار علاء: أُضيفت BLACKGOLD_EAT_8AM (13 صفقة، -7.68R تراكمي)
    # 2026-10-24 بقرار علاء (حزمة الركن): أُضيفت ALAA_SMC_GOLD وHTF_FIB50_WEEKLY
    DISABLED_STRATEGIES = {"TALARIA_GOLD_BREAKOUT", "BLACKGOLD_EAT_8AM",
                           "ALAA_SMC_GOLD", "HTF_FIB50_WEEKLY"}
    _parked = [s for s in sigs if s["strategy"] in DISABLED_STRATEGIES]
    if _parked:
        # سجل الظل: قياس صامت لأثر الركن — لا دفتر ولا تنبيه ولا مرآة
        try:
            with open(os.path.join(OUT, "shadow_signals.jsonl"), "a") as _f:
                for _s in _parked:
                    _f.write(json.dumps(
                        {"ts": dt.datetime.now(DAM).strftime("%Y-%m-%d %H:%M:%S"),
                         "reason": "parked", "strategy": _s["strategy"],
                         "dir": _s["dir"], "entry": _s["entry"], "sl": _s["sl"],
                         "tp1": _s.get("tp1"), "tp2": _s.get("tp2"),
                         "tp3": _s.get("tp3"),
                         "risk_usd": round(abs(_s["entry"] - _s["sl"]), 2)},
                        ensure_ascii=False) + "\n")
        except Exception:
            pass
    sigs = [s for s in sigs if s["strategy"] not in DISABLED_STRATEGIES]
    # فلتر ADX: في الترند القوي (ADX>=25) نرفض الإشارات المعاكسة لانحياز DI
    adx = wilder_dmi_adx(m15)
    if adx["adx"] >= 25.0:
        kept = []
        for s in sigs:
            opposing = (s["dir"] == "شراء" and adx["bias"] == "BEARISH_DI") or \
                       (s["dir"] == "بيع" and adx["bias"] == "BULLISH_DI")
            if opposing:
                print(f"  x ADX veto: {s['strategy']} {s['dir']} (ADX {adx['adx']} {adx['bias']})")
            else:
                kept.append(s)
        sigs = kept
    # طبقة تأكيد أنماط علاء: تُلحق بالملاحظة دون تغيير المنطق
    pats = detect_alaa_chart_patterns(m15)
    if pats:
        for s in sigs:
            conf = []
            if s["dir"] == "شراء" and (pats.get("double_bottom") or pats.get("inv_hs")):
                conf.append("تأكيد نموذج انعكاسي صاعد")
            if s["dir"] == "بيع" and pats.get("double_top"):
                conf.append("تأكيد قمة مزدوجة")
            if pats.get("flip_support") and s["dir"] == "شراء":
                conf.append(f"دعم Flip Zone {pats['flip_support']}")
            if conf:
                s["note"] = (s["note"] + " | " if s["note"] else "") + " + ".join(conf)
                s["reason"] = s["reason"] + " — " + " + ".join(conf)
    if any(s["strategy"] == "TALARIA_L7_OSOK" for s in sigs):
        state["osok_week"] = week
    # منع التضارب: شراء+بيع معاً → نبقي الموافق لاتجاه سيولة IPDA
    buys = [s for s in sigs if s["dir"] == "شراء"]
    sells = [s for s in sigs if s["dir"] == "بيع"]
    if buys and sells:
        ipda = ipda_20_40_60(d1)
        pref = ipda["dol_direction"] if ipda else ("BUY" if four_point_ms(m15[-40:]) == "BULLISH" else "SELL")
        want = "شراء" if pref == "BUY" else "بيع"
        sigs = [s for s in sigs if s["dir"] == want]
    # حارس الحداثة (قرار علاء 2026-10-23): إسقاط أي إشارة تجاوز السعر الحي
    # هدفها الأول أو وقفها أو ابتعد عن دخولها أكثر من مخاطرة واحدة
    from freshness import filter_fresh
    sigs, dropped_stale = filter_fresh(sigs, mode="market")
    for d in dropped_stale:
        print(f"  x freshness: {d['strategy']} {d['dir']} @{d['entry']} — {d['why']}")
    # تسليح مسبق (قرار علاء 2026-10-27): إشارات الدخول المعلّق تعرف مستواها
    # الآن والسعر لم يلمسه بعد — اكتب نية لمنفّذ المرآة فيعلّق الأوامر عند
    # البروكر قبل الوصول. كتلة جانبية صامتة: فشلها لا يعطّل الماسح أبداً.
    try:
        import mirror_intents as _mi
        for _s in sigs:
            if _s.get("entry_type") == "LIMIT":
                _mi.append_intent(
                    "QTH_" + _s["strategy"], _s["dir"], _s["entry"],
                    _s["sl"], tp1=_s.get("tp1"), tp2=_s.get("tp2"),
                    tp3=_s.get("tp3"), expiry_min=120, mgmt="secure",
                    note="نية تسليح من ماسح QTH عند تشكّل الإشارة",
                    key=_s.get("key"))
    except Exception:
        pass
    json.dump({"time": now, "price": round(price, 2), "signals": sigs,
               "dropped_stale": dropped_stale},
              open(os.path.join(OUT, "qth_strategies.json"), "w"))
    json.dump(state, open(state_path, "w"))
    draw_chart(m15, sigs)
    print(f"QTH scan {now}: price={price:.2f} signals={len(sigs)}")
    for s in sigs:
        print(f"  - {s['strategy']} {s['dir']} @{s['entry']} SL {s['sl']} TP {s['tp1']}/{s['tp2']} RR {s['rr']}")

def draw_chart(m15, sigs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cs = m15[-120:]
    xs = list(range(len(cs)))
    o = [c["o"] for c in cs]; h = [c["h"] for c in cs]
    l = [c["l"] for c in cs]; cl = [c["c"] for c in cs]
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_facecolor("#0d1117"); fig.patch.set_facecolor("#0d1117")
    for i in xs:
        col = "#26a69a" if cl[i] >= o[i] else "#ef5350"
        ax.plot([i, i], [l[i], h[i]], color=col, lw=1)
        ax.plot([i, i], [o[i], cl[i]], color=col, lw=3)
    if sigs:
        s = sigs[0]
        for lv, cc, ls in [(s["entry"], "#ffd54f", "--"), (s["sl"], "#ef5350", ":"),
                           (s["tp1"], "#26a69a", "-."), (s["tp2"], "#26a69a", "-.")]:
            ax.axhline(lv, color=cc, ls=ls, lw=1.2)
        ax.set_title(f"QTH {s['strategy']} {s['dir']} @ {s['entry']}", color="white", fontsize=11)
    else:
        ax.set_title("QTH scan — no signals", color="white", fontsize=11)
    ax.tick_params(colors="gray", labelsize=8)
    for sp in ax.spines.values():
        sp.set_color("#333")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "qth_strategies.png"), dpi=90)
    plt.close(fig)

if __name__ == "__main__":
    main()
