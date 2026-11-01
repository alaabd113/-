#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ماسح الاستراتيجيات المعكوسة (هندسة عكسية — قرار علاء 2026-10-21).

يراقب إشارات استراتيجيتين خاسرتين بلا أي فوز بالدفتر
(TALARIA_GOLD_BREAKOUT وALAA_SMC_GOLD) ويعكس كل إشارة ناجية من بوابة
v31_gate بهندسة وقف/أهداف مدروسة من جديد — لا مرآة للأصلية:
- تلاشي الكسر (TALARIA): الوقف خلف طرف شمعة الإشارة ± 0.25×ATR14.
- تلاشي المنطقة (ALAA_SMC، أصلية شراء فقط ← بيع): الوقف خلف آخر قمة
  فركتلية بنافذة 40 شمعة + 0.25×ATR، مع قاعدة الاحتياط [0.4×، 2.5×]
  من مخاطرة الإشارة الأصلية.
- الأهداف سلم 1R/2R/3R من مخاطرة التلاشي. إدارة الدفتر: secure.

المخرجات: gold_reversed.json + طباعة JSON. لا تسجيل بالدفتر ولا إرسال —
التسجيل والإرسال شغل الكرون والمساعد الرئيسي.
"""
import json, os, sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_hours import require_market_open  # noqa: E402
from candle_db import get_candles  # noqa: E402
from qth_strategies import (atr, enrich_inplace, eval_alaa_smc_gold,  # noqa: E402
                            eval_talaria_gold_breakout, fractal_swings,
                            td, v31_gate)

OUT = os.path.expanduser("~/workspace/gold-station")
MIN_RISK = 0.5  # حد أدنى لمخاطرة التلاشي بالدولار — دونها تُهمل الإشارة

NAMES = {"QTH_TALARIA_BREAKOUT_FADE": "تالاريا — تلاشي الكسر (معكوسة)",
         "QTH_ALAA_SMC_FADE": "علاء SMC — تلاشي المنطقة (معكوسة)"}


def _ladder(entry, sl, sign):
    risk = abs(entry - sl)
    return risk, [round(entry + sign * risk * m, 2) for m in (1.0, 2.0, 3.0)]


def fade_talaria(sig, m15, a14):
    """عكس إشارة اختراق/كسر تالاريا: تلاشي الحركة عند طرف شمعة الإشارة."""
    entry = float(sig["entry"])
    candle = m15[-1]
    buf = 0.25 * a14
    if sig["dir"] == "شراء":      # اختراق صاعد ← تلاشي بيع
        sl = candle["h"] + buf
        if sl <= entry:
            sl = entry + buf
        sign, direction = -1.0, "بيع"
        why = (f"تلاشي اختراق صاعد: الكسر فوق {candle['h']:.2f} مرشّح للفشل — "
               f"بيع عند الدخول ووقف التلاشي خلف قمة شمعة الإشارة + 0.25×ATR")
    else:                          # كسر هابط ← تلاشي شراء
        sl = candle["l"] - buf
        if sl >= entry:
            sl = entry - buf
        sign, direction = 1.0, "شراء"
        why = (f"تلاشي كسر هابط: الكسر تحت {candle['l']:.2f} مرشّح للفشل — "
               f"شراء عند الدخول ووقف التلاشي خلف قاع شمعة الإشارة − 0.25×ATR")
    risk, tps = _ladder(entry, round(sl, 2), sign)
    if risk < MIN_RISK:
        return None
    return {"strategy": "QTH_TALARIA_BREAKOUT_FADE",
            "name": NAMES["QTH_TALARIA_BREAKOUT_FADE"], "dir": direction,
            "entry": entry, "sl": round(sl, 2),
            "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
            "rr": 3.0, "risk": round(risk, 2), "t": sig["t"],
            "reason": why + f" | الإشارة الأصلية: {sig['reason']}",
            "note": "استراتيجية معكوسة (هندسة عكسية بقرار علاء 2026-10-21) — دخول فوري عند سعر الإشارة الأصلية",
            "key": sig["key"] + "|REV"}


def fade_alaa_smc(sig, m15, a14):
    """عكس علاء SMC (شراء فقط أصلاً): بيع تلاشي الارتداد من المنطقة الذهبية."""
    entry = float(sig["entry"])
    orig_risk = abs(entry - float(sig["sl"]))
    highs, _ = fractal_swings(m15[-40:], 2, 2)
    if not highs:
        return None
    sl = highs[-1][1] + 0.25 * a14
    risk = abs(entry - sl)
    extra = ""
    if risk < 0.4 * orig_risk or risk > 2.5 * orig_risk:
        risk = orig_risk
        sl = entry + orig_risk
        extra = " (مسافة الفركتل خارج النطاق المدروس — استُعملت مخاطرة الأصلية)"
    risk, tps = _ladder(entry, round(sl, 2), -1.0)
    if risk < MIN_RISK:
        return None
    why = (f"تلاشي ارتداد المنطقة الذهبية: الشراء الأصلي من المنطقة مرشّح "
           f"للفشل — بيع عند الدخول ووقف التلاشي خلف آخر قمة فركتلية "
           f"{highs[-1][1]:.2f} + 0.25×ATR{extra}")
    return {"strategy": "QTH_ALAA_SMC_FADE",
            "name": NAMES["QTH_ALAA_SMC_FADE"], "dir": "بيع",
            "entry": entry, "sl": round(sl, 2),
            "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
            "rr": 3.0, "risk": round(risk, 2), "t": sig["t"],
            "reason": why + f" | الإشارة الأصلية: {sig['reason']}",
            "note": "استراتيجية معكوسة (هندسة عكسية بقرار علاء 2026-10-21) — دخول فوري عند سعر الإشارة الأصلية",
            "key": sig["key"] + "|REV"}


def main():
    require_market_open()  # خروج صامت عند إغلاق السوق
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("Asia/Damascus")).strftime("%Y-%m-%d %H:%M:%S")
    m15 = enrich_inplace(get_candles("15min", 150, live=lambda: td("15min", 150)))
    h4 = enrich_inplace(get_candles("4h", 100, live=lambda: td("4h", 100)))
    price = m15[-1]["c"]
    a14 = atr(m15)
    signals = []
    orig = eval_talaria_gold_breakout(m15)
    if orig and v31_gate(orig, price, a14):
        rev = fade_talaria(orig, m15, a14)
        if rev:
            signals.append(rev)
    orig = eval_alaa_smc_gold(m15, h4)
    if orig and v31_gate(orig, price, a14):
        rev = fade_alaa_smc(orig, m15, a14)
        if rev:
            signals.append(rev)
    # حارس الحداثة (قرار علاء 2026-10-23): إسقاط أي إشارة تجاوز السعر الحي
    # هدفها الأول أو ابتعد عن دخولها أكثر من مخاطرة واحدة قبل التسجيل
    from freshness import filter_fresh
    signals, dropped_stale = filter_fresh(signals, mode="market")
    payload = {"time": now, "price": round(price, 2), "signals": signals,
               "dropped_stale": dropped_stale}
    json.dump(payload, open(os.path.join(OUT, "gold_reversed.json"), "w"),
              ensure_ascii=False)
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
