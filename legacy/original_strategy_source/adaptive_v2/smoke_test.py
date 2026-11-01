"""
اختبار دخان لطبقة البيانات — يتحقق من:
1. منع Look-Ahead: لا شمعة «مغلقة» يتجاوز إغلاقها لحظة as_of.
2. فصل الجارية: الشمعة الجارية منفصلة ولا تظهر ضمن المغلقة.
3. خاصية البادئة: تقليص as_of يعطي بادئة من النتيجة الأكبر (لا مستقبل يتسلل).
4. العزل: بصمة الدفتر الحقيقي لا تتغير بسبب تشغيل هذا الاختبار.

تشغيل: python3 smoke_test.py
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import market_data as md

LEDGER = Path(__file__).resolve().parent.parent / "gold_ledger.json"
FMT = "%Y-%m-%d %H:%M:%S"


def ledger_md5():
    return hashlib.md5(LEDGER.read_bytes()).hexdigest()


def main():
    before = ledger_md5()
    failures = []

    as_of = "2026-10-20 12:00:00"
    t = datetime.strptime(as_of, FMT)

    for interval in ("1min", "5min", "15min", "1h", "4h"):
        dur = timedelta(minutes=md.INTERVAL_MINUTES[interval])
        rows = md.closed_candles_asof(interval, as_of, limit=300)
        if not rows:
            failures.append(f"{interval}: no candles returned")
            continue
        for r in rows:
            close_t = datetime.strptime(r["ts"], FMT) + dur
            if close_t > t:
                failures.append(
                    f"{interval}: LOOK-AHEAD leak {r['ts']} closes {close_t} > {as_of}")
                break
        # خاصية البادئة (صيغة صحيحة مع نوافذ محدودة): عند as_of أبكر،
        # كل شمعة مشتركة مع النتيجة الأكبر يجب أن تكون مطابقة القيم،
        # وآخر شمعة أبكر لا تتجاوز آخر شمعة عند as_of.
        earlier = (t - timedelta(hours=1)).strftime(FMT)
        rows_e = md.closed_candles_asof(interval, earlier, limit=300)
        by_ts = {r["ts"]: r for r in rows}
        for r in rows_e:
            close_e = datetime.strptime(r["ts"], FMT) + dur
            if close_e > t - timedelta(hours=1):
                failures.append(f"{interval}: earlier query leaked future {r['ts']}")
                break
            if r["ts"] in by_ts:
                o = by_ts[r["ts"]]
                if (o["o"], o["h"], o["l"], o["c"]) != (r["o"], r["h"], r["l"], r["c"]):
                    failures.append(f"{interval}: candle {r['ts']} changed between queries")
                    break
        if rows_e and rows_e[-1]["ts"] > rows[-1]["ts"]:
            failures.append(f"{interval}: earlier result ends after full result")
        print(f"{interval}: closed={len(rows)} last={rows[-1]['ts']} "
              f"src={rows[-1]['source']} prefix_ok")

    # فصل الشمعة الجارية على M15 عند 12:07 — الجارية تبدأ 12:00
    fc = md.forming_candle("15min", "2026-10-20 12:07:00")
    closed = md.closed_candles_asof("15min", "2026-10-20 12:07:00", limit=300)
    if fc is None:
        failures.append("forming candle missing at 12:07")
    else:
        if any(r["ts"] == fc["ts"] for r in closed):
            failures.append("forming candle leaked into closed set")
        print(f"forming M15 @12:07 -> {fc['ts']} (separate from closed)")

    # الدفتر الحقيقي لم يُمس
    after = ledger_md5()
    if before != after:
        failures.append(f"LEDGER CHANGED by test: {before} -> {after}")
    else:
        print(f"ledger untouched: md5 {after}")

    # دفتر حقيقي مقروء فقط — عدد الصفقات للتوثيق
    data = json.loads(LEDGER.read_text())
    trades = data if isinstance(data, list) else data.get("trades", [])
    print(f"ledger trades visible read-only: {len(trades)}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        raise SystemExit(1)
    print("\nSMOKE TEST PASSED — no look-ahead, forming separated, ledger untouched.")


if __name__ == "__main__":
    main()
