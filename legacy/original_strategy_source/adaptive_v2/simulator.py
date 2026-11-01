"""
Realistic Paper Simulator — Adaptive V2, Step 4

يعيد تشغيل كل صفقة مغلقة من الدفتر على شموع الدقيقة المخزّنة، بنفس
قواعد إدارتها المسجلة (mgmt / be_after / be_trigger_r)، ويقارن الناتج
مع نتيجة الدفتر الفعلية — الفروقات تقيس أثر اختلاف الفيد وسياسة الغموض،
لأن مرجع الحقيقة يبقى بروكر علاء لا فيدنا.

قواعد معلنة (لا تُخفى):
- قاعدة الشمعة الغامضة: إذا لامست شمعة واحدة الوقف وهدفاً معاً،
  يُحتسب الوقف أولاً (الخيار المتحفظ).
- الوقف يُفحص بقيمته كما كانت عند بداية الشمعة — أي تسليح تعادل
  داخل الشمعة يسري من الشمعة التالية (نفس قاعدة الدفتر الحي).
- نموذج التكلفة المعلن: سبريد 0.30$ + انزلاق 0.10$ ذهاباً وإياباً
  لكل صفقة، تُخصم مرة واحدة كنسبة من مخاطرة الصفقة، مع سيناريوهي
  ضغط ×1.5 و×2. هذه أرقام مُنمذجة معلنة — لا سبريد حقيقياً مخزّناً.
- صفقات LIMIT تُحاكى كأنها امتلأت عند ts_open بسعر الدخول
  (تقريب معلن — الامتلاء الحقيقي عند البروكر).

التشغيل: python3 simulator.py
المخرجات: shadow/sim_report.json + ملخص مطبوع.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import market_data as md
import shadow_observer as so

BASE = Path(__file__).resolve().parent
LEDGER = BASE.parent / "gold_ledger.json"
REPORT = BASE / "shadow" / "sim_report.json"
FMT = "%Y-%m-%d %H:%M:%S"

SPREAD_USD = 0.30
SLIP_USD = 0.10


def _sign(d):
    return 1.0 if str(d) in ("buy", "شراء", "long") else -1.0


def _candles_1min(ts_open, ts_end):
    rows = md.closed_candles_asof("1min", ts_end, limit=9000)
    rows = [c for c in rows if c["ts"] >= ts_open]
    # فجوة صيانة cTrader اليومية (~00:00–01:00) قد تجعل نافذته تبدأ بعد
    # فتح الصفقة — عندها جرّب TwelveData صراحة واختر التغطية الأبكر.
    deadline = (datetime.strptime(ts_open, FMT)
                + timedelta(minutes=10)).strftime(FMT)
    if not rows or rows[0]["ts"] > deadline:
        alt = md.closed_candles_asof("1min", ts_end, limit=9000,
                                     source="twelvedata")
        alt = [c for c in alt if c["ts"] >= ts_open]
        if alt and (not rows or alt[0]["ts"] < rows[0]["ts"]):
            rows = alt
    return rows


def simulate(trade, candles):
    """إعادة تشغيل صفقة واحدة. يعيد dict بالنواتج أو سبب التعذر."""
    entry = float(trade["entry"])
    sl0 = float(trade["sl"])
    sign = _sign(trade.get("dir"))
    risk = abs(entry - sl0)
    if risk <= 0 or not candles:
        return {"ok": False, "reason": "no risk or no candles"}
    if candles[0]["ts"] > (datetime.strptime(trade["ts_open"], FMT)
                           + timedelta(minutes=10)).strftime(FMT):
        return {"ok": False, "reason": "candles start too late"}

    mgmt = trade.get("mgmt") or "thirds"
    tps = [trade.get("tp1"), trade.get("tp2"), trade.get("tp3")]
    tps = [float(x) if x is not None else None for x in tps]
    if mgmt == "full":
        tgt = tps[2] if tps[2] is not None else tps[0]
        if tgt is None:
            return {"ok": False, "reason": "full without target"}
        parts = [(1.0, tgt)]
    else:
        last = None
        parts = []
        for tp in tps:
            if tp is not None:
                last = tp
            parts.append((1.0 / 3.0, last))
        if last is None:
            return {"ok": False, "reason": "no targets"}

    be_after = trade.get("be_after")  # 'tp1' / 'tp2' / None
    be_trig = trade.get("be_trigger_r")  # مثل 0.2 لصفقات النقاط
    stop = sl0
    be_armed_next = False
    remaining = list(range(len(parts)))
    banked = 0.0
    closed_parts = set()
    exit_reason = "horizon"

    def hit_stop(c):
        return c["l"] <= stop if sign > 0 else c["h"] >= stop

    def hit_px(c, px):
        return c["h"] >= px if sign > 0 else c["l"] <= px

    for c in candles:
        if be_armed_next:
            stop = entry
            be_armed_next = False
        if not remaining:
            break
        # 1) الوقف أولاً (قاعدة الغموض المتحفظة)
        if hit_stop(c):
            for i in remaining:
                banked += parts[i][0] * sign * (stop - entry) / risk
                closed_parts.add(i)
            remaining = []
            exit_reason = "be" if stop == entry else "sl"
            break
        # 2) الأهداف بالترتيب
        hit_now = []
        for i in list(remaining):
            tp = parts[i][1]
            if tp is not None and hit_px(c, tp):
                banked += parts[i][0] * sign * (tp - entry) / risk
                closed_parts.add(i)
                hit_now.append(i)
                remaining.remove(i)
        if hit_now:
            if be_after == "tp1" and 0 in hit_now:
                be_armed_next = True
            if be_after == "tp2" and 1 in hit_now:
                be_armed_next = True
            if not remaining:
                exit_reason = "tp_all"
                break
        # 3) تسليح التعادل المبكر بعتبة R (يسري من الشمعة التالية)
        if be_trig is not None and remaining:
            trig_px = entry + sign * float(be_trig) * risk
            if hit_px(c, trig_px):
                be_armed_next = True

    mtm = 0.0
    if remaining:
        last_close = candles[-1]["c"]
        for i in remaining:
            mtm += parts[i][0] * sign * (last_close - entry) / risk

    cost_r = (SPREAD_USD + SLIP_USD) / risk
    return {
        "ok": True,
        "sim_r_gross": round(banked + mtm, 3),
        "sim_r_base": round(banked + mtm - cost_r, 3),
        "sim_r_x15": round(banked + mtm - cost_r * 1.5, 3),
        "sim_r_x2": round(banked + mtm - cost_r * 2.0, 3),
        "exit_reason": exit_reason,
        "open_remainder": bool(remaining),
    }


def run():
    data = json.loads(LEDGER.read_text())
    trades = data if isinstance(data, list) else data.get("trades", [])
    outcomes = so.load_outcomes()
    results, skipped = {}, []
    for tr in trades:
        tid = tr.get("id")
        if tid is None or tid not in outcomes:
            continue
        ts_close = outcomes[tid].get("ts_close")
        if not ts_close:
            skipped.append((tid, "no ts_close"))
            continue
        end = (datetime.strptime(ts_close, FMT)
               + timedelta(hours=2)).strftime(FMT)
        candles = _candles_1min(tr["ts_open"], end)
        r = simulate(tr, candles)
        if not r["ok"]:
            skipped.append((tid, r["reason"]))
            continue
        actual = outcomes[tid].get("r_multiple")
        r["actual_r"] = actual
        if isinstance(actual, (int, float)):
            r["delta"] = round(r["sim_r_base"] - actual, 3)
        results[tid] = r

    deltas = [abs(r["delta"]) for r in results.values() if "delta" in r]
    matched = sum(1 for d in deltas if d <= 0.15)
    worst = sorted((r for r in results.values() if "delta" in r),
                   key=lambda r: -abs(r["delta"]))[:5]
    summary = {
        "simulated": len(results),
        "skipped": len(skipped),
        "matched_within_0.15R": matched,
        "match_rate": round(matched / len(deltas), 3) if deltas else None,
        "mean_abs_delta": round(sum(deltas) / len(deltas), 3) if deltas else None,
        "sim_total_base": round(sum(r["sim_r_base"] for r in results.values()), 2),
        "sim_total_x15": round(sum(r["sim_r_x15"] for r in results.values()), 2),
        "sim_total_x2": round(sum(r["sim_r_x2"] for r in results.values()), 2),
        "actual_total": round(sum(r["actual_r"] for r in results.values()
                                   if isinstance(r.get("actual_r"), (int, float))), 2),
        "worst": [{"delta": r["delta"], "sim": r["sim_r_base"],
                   "actual": r["actual_r"]} for r in worst],
        "cost_model": {"spread_usd": SPREAD_USD, "slip_usd": SLIP_USD},
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"summary": summary, "results": results,
                                  "skipped": skipped},
                                 ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


if __name__ == "__main__":
    run()
