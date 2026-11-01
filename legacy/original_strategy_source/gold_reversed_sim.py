#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""محاكاة تحقق للاستراتيجيات المعكوسة (هندسة عكسية — قرار علاء 2026-10-21).

لكل صفقة مغلقة بالدفتر من TALARIA_GOLD_BREAKOUT وALAA_SMC_GOLD:
- الاتجاه معكوس، نفس سعر الدخول ووقت الفتح.
- الوقف/الأهداف ليست مرآة الأصلية بل هندسة مدروسة (انظر fade_geometry).
- إدارة secure: ثلث عند كل هدف بقيمته الحقيقية، الوقف للدخول بعد TP1،
  الوقف يُفحص بقيمته من بداية الشمعة، الشمعة الغامضة = وقف أولاً.
- كلف: سبريد 0.30$ + انزلاق 0.10$ تُخصم مرة واحدة من النتيجة (نفس
  اصطلاح adaptive_v2/simulator.py).
- بلا نظر للمستقبل: شموع M15 بعد ts_open فقط، حتى 7 أيام.
قراءة فقط — لا تسجيل بالدفتر ولا إرسال.
"""
import json, os, sqlite3, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qth_strategies import atr, fractal_swings  # noqa: E402

BASE = os.path.expanduser("~/workspace/gold-station")
FMT = "%Y-%m-%d %H:%M:%S"
SPREAD_USD, SLIP_USD = 0.30, 0.10
HORIZON_DAYS = 7
TARGETS = ("QTH_TALARIA_GOLD_BREAKOUT", "QTH_ALAA_SMC_GOLD")


def load_m15():
    """كل شموع M15 من القاعدة: cTrader مفضّل عند كل طابع، TwelveData احتياط."""
    con = sqlite3.connect(os.path.join(BASE, "candles.db"))
    by_ts = {}
    for src in ("twelvedata", "ctrader"):  # الثاني يطغى على الأول
        for ts, o, h, l, c in con.execute(
                "SELECT ts,o,h,l,c FROM candles WHERE interval='15min' AND source=? ORDER BY ts",
                (src,)):
            by_ts[ts] = {"t": ts, "o": o, "h": h, "l": l, "c": c}
    con.close()
    return [by_ts[k] for k in sorted(by_ts)]


def atr_at(cs):
    return atr(cs)  # نفس صيغة qth_strategies (آخر 14 TR)


def fade_geometry(trade, candles_before, signal_candle):
    """هندسة الوقف المدروسة للصفقة المعكوسة. يعيد (sl, risk, flags)."""
    entry = float(trade["entry"])
    orig_dir = trade["dir"]
    orig_risk = abs(entry - float(trade["sl"]))
    a14 = atr_at(candles_before[-60:]) if len(candles_before) >= 15 else None
    flags = []
    if a14 is None:
        return None, None, ["شموع غير كافية لحساب ATR"]
    buf = 0.25 * a14
    if trade["strategy"] == "QTH_TALARIA_GOLD_BREAKOUT":
        if signal_candle is None:
            return None, None, ["شمعة إشارة غير موجودة بالقاعدة"]
        if orig_dir == "شراء":      # الأصلية شراء اختراق ← التلاشي بيع
            sl = signal_candle["h"] + buf
            if sl <= entry:          # فرق فيد: قمة الشمعة المخزّنة تحت دخول الفيد الحي
                sl = entry + buf
                flags.append("وقف معدّل: قمة شمعة الإشارة المخزّنة دون سعر الدخول (فرق فيد) — استُعمل الدخول + 0.25×ATR")
        else:                        # الأصلية بيع كسر ← التلاشي شراء
            sl = signal_candle["l"] - buf
            if sl >= entry:
                sl = entry - buf
                flags.append("وقف معدّل: قاع شمعة الإشارة المخزّنة فوق سعر الدخول (فرق فيد) — استُعمل الدخول − 0.25×ATR")
        risk = abs(entry - sl)
    else:  # ALAA_SMC_GOLD — الأصلية شراء فقط ← المعكوسة بيع
        window = candles_before[-40:]
        highs, _ = fractal_swings(window, 2, 2)
        if not highs:
            return None, None, ["لا قمة فركتلية بنافذة 40 شمعة قبل الدخول"]
        sl = highs[-1][1] + buf
        risk = abs(entry - sl)
        if risk < 0.4 * orig_risk or risk > 2.5 * orig_risk:
            risk = orig_risk
            sl = entry + orig_risk
            flags.append("مسافة الوقف الفركتلية خارج [0.4×، 2.5×] مخاطرة الأصلية — استُعملت مسافة المخاطرة الأصلية")
    if risk <= 0:
        return None, None, ["مخاطرة صفرية"]
    return round(sl, 2), round(risk, 2), flags


def simulate_secure(entry, sl, fwd, sign):
    """إدارة secure على شموع M15 التالية للدخول. sign: +1 شراء / -1 بيع."""
    risk = abs(entry - sl)
    tps = [entry + sign * risk * m for m in (1.0, 2.0, 3.0)]
    parts = [(1.0 / 3.0, tp) for tp in tps]
    stop = sl
    be_armed_next = False
    remaining = list(range(3))
    banked = 0.0
    exit_reason = "open_horizon"

    def hit_stop(c):
        return c["l"] <= stop if sign > 0 else c["h"] >= stop

    def hit_px(c, px):
        return c["h"] >= px if sign > 0 else c["l"] <= px

    for c in fwd:
        if be_armed_next:
            stop = entry
            be_armed_next = False
        if not remaining:
            break
        if hit_stop(c):  # الوقف أولاً — قاعدة الشمعة الغامضة
            for i in remaining:
                banked += parts[i][0] * sign * (stop - entry) / risk
            remaining = []
            exit_reason = "be" if stop == entry else "sl"
            break
        hit_now = []
        for i in list(remaining):
            if hit_px(c, parts[i][1]):
                banked += parts[i][0] * sign * (parts[i][1] - entry) / risk
                hit_now.append(i)
                remaining.remove(i)
        if hit_now:
            if 0 in hit_now:
                be_armed_next = True
            if not remaining:
                exit_reason = "tp_all"
                break
    mtm = 0.0
    if remaining and fwd:
        last_close = fwd[-1]["c"]
        for i in remaining:
            mtm += parts[i][0] * sign * (last_close - entry) / risk
    return banked, mtm, exit_reason


def main():
    candles = load_m15()
    idx = {c["t"]: i for i, c in enumerate(candles)}
    data = json.load(open(os.path.join(BASE, "gold_ledger.json")))
    trades = data if isinstance(data, list) else data.get("trades", [])
    rows, unsimulable = [], []
    totals = {}
    for tr in trades:
        if tr["strategy"] not in TARGETS or not tr.get("ts_close"):
            continue
        ts_open = tr["ts_open"]
        entry = float(tr["entry"])
        # شمعة الإشارة: الشمعة التي تحوي ts_open (بدايتها <= ts_open < نهايتها).
        # ts_open بالدفتر مسجّل من حقل t بالإشارة = بداية شمعة الإشارة نفسها
        # (أو لحظة التسجيل داخلها لصفقات ما بعد إصلاح الصفقة الشبح) — والقراءة
        # الحرفية «آخر شمعة أغلقت قبل ts_open» تُخطئها بشمعة كاملة وتضع طرف
        # الشمعة السابقة خلف الدخول بـ8 من 9 حالات تالاريا بسبب فرق الفيد.
        sig_idx = None
        for i, c in enumerate(candles):
            if c["t"] <= ts_open:
                sig_idx = i
            else:
                break
        if sig_idx is None:
            unsimulable.append((tr["id"], tr["strategy"], "لا شمعة تحوي وقت الفتح"))
            continue
        signal_candle = candles[sig_idx]
        before = candles[:sig_idx + 1]  # حتى شمعة الإشارة شاملةً (لـATR والفركتل)
        # شموع المحاكاة: بعد شمعة الإشارة مباشرة وحتى 7 أيام من الفتح
        end = datetime.strptime(ts_open, FMT) + timedelta(days=HORIZON_DAYS)
        fwd = [c for c in candles[sig_idx + 1:]
               if datetime.strptime(c["t"], FMT) <= end]
        if len(before) < 40 or len(fwd) < 4:
            unsimulable.append((tr["id"], tr["strategy"],
                                f"شموع غير كافية (قبل={len(before)} بعد={len(fwd)})"))
            continue
        sl, risk, flags = fade_geometry(tr, before, signal_candle)
        if sl is None:
            unsimulable.append((tr["id"], tr["strategy"], "; ".join(flags)))
            continue
        sign = -1.0 if tr["dir"] == "شراء" else 1.0  # الاتجاه المعكوس
        banked, mtm, why = simulate_secure(entry, sl, fwd, sign)
        gross_r = banked + mtm
        cost_r = (SPREAD_USD + SLIP_USD) / risk
        net_r = gross_r - cost_r
        net_pips = round(net_r * risk * 10)
        row = {"id": tr["id"], "strategy": tr["strategy"],
               "orig_dir": tr["dir"], "rev_dir": "بيع" if sign < 0 else "شراء",
               "entry": entry, "sl": sl, "risk": risk,
               "net_r": round(net_r, 2), "net_pips": net_pips,
               "exit": why, "flags": flags, "ts_open": ts_open}
        rows.append(row)
        t = totals.setdefault(tr["strategy"], {"n": 0, "r": 0.0, "pips": 0, "w": 0})
        t["n"] += 1
        t["r"] += row["net_r"]
        t["pips"] += net_pips
        if net_r > 0:
            t["w"] += 1
    grand = {"n": sum(t["n"] for t in totals.values()),
             "r": round(sum(t["r"] for t in totals.values()), 2),
             "pips": sum(t["pips"] for t in totals.values()),
             "w": sum(t["w"] for t in totals.values())}
    for v in totals.values():
        v["r"] = round(v["r"], 2)

    names = {"QTH_TALARIA_GOLD_BREAKOUT": "تالاريا — اختراق النطاق (تلاشي الكسر)",
             "QTH_ALAA_SMC_GOLD": "علاء SMC (تلاشي المنطقة الذهبية)"}
    lines = ["# محاكاة الاستراتيجيات المعكوسة — 2026-10-21", "",
             "هندسة عكسية بقرار علاء: الاتجاه معكوس، والوقف/الأهداف مدروسة من جديد",
             "(لا مرآة للأصلية). إدارة secure (ثلث عند كل هدف، الوقف للدخول بعد",
             "الهدف الأول، الوقف أولاً عند الغموض)، كلف 0.30$ سبريد + 0.10$ انزلاق",
             "تُخصم مرة واحدة، شموع M15 من القاعدة (cTrader أولاً)، نافذة 7 أيام.",
             "شمعة الإشارة = الشمعة الحاوية لـts_open (تسجيل الدفتر يأخذ بداية",
             "شمعة الإشارة)، والمحاكاة تبدأ من الشمعة التي بعدها.", "",
             "| الصفقة الأصلية | الاستراتيجية | الاتجاه المعكوس | الدخول | وقف التلاشي | المخاطرة (بيب) | النتيجة R | النتيجة بيب | الإغلاق |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| #{r['id']} | {names[r['strategy']]} | {r['rev_dir']} | {r['entry']:.2f} | "
                     f"{r['sl']:.2f} | {round(r['risk'] * 10)} | {r['net_r']:+.2f} | {r['net_pips']:+d} | {r['exit']} |")
    lines += ["", "## المجاميع", ""]
    for k, v in totals.items():
        lines.append(f"- {names[k]}: {v['n']} صفقات — فوز {v['w']} — المجموع {v['r']:+.2f}R / {v['pips']:+d} بيب")
    lines.append(f"- **المجموع الكلي: {grand['n']} صفقة — فوز {grand['w']} — {grand['r']:+.2f}R / {grand['pips']:+d} بيب**")
    lines.append(f"- الأصلية للمقارنة: 13 صفقة — فوز 0 — ‏−13.0R")
    if unsimulable:
        lines += ["", "## صفقات تعذّرت محاكاتها", ""]
        for tid, strat, why in unsimulable:
            lines.append(f"- #{tid} ({strat}): {why}")
    flagged = [r for r in rows if r["flags"]]
    if flagged:
        lines += ["", "## ملاحظات وقف معدّل (فرق فيد / قواعد احتياطية)", ""]
        for r in flagged:
            lines.append(f"- #{r['id']}: {'; '.join(r['flags'])}")
    report = "\n".join(lines) + "\n"
    path = os.path.join(BASE, "reversed_sim_report_2026-10-21.md")
    open(path, "w").write(report)
    print(json.dumps({"totals": totals, "grand": grand,
                      "unsimulable": unsimulable,
                      "rows": rows, "report": path}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
