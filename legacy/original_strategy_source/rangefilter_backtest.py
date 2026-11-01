#!/usr/bin/env python3
"""باكتست Range Filter B&S على XAUUSD فريم 15m — قراءة فقط من candles.db.

القواعد:
- الدخول عند إغلاق شمعة الإشارة (إشارات ما بعد الـ warmup فقط).
- الوقف = خط filt عند الدخول (ثابت).
- الهدف = 2R (ومتغير 3R) — يُحسب كلاهما في تمريرة واحدة.
- تُتخطى الإشارة إذا risk <= 0 أو risk < 0.5$.
- صفقة واحدة كل مرة؛ داخل الشمعة: الوقف أولاً (محافظ).
"""
import sys
sys.path.insert(0, ".")
from candle_db import read
from range_filter import range_filter, signals, WARMUP

MIN_RISK = 0.5


def run(tp_mult):
    rows = read(interval="15min", limit=5000)
    closes = [r["c"] for r in rows]
    filt, _ = range_filter(closes)
    sigs = [(i, d) for (i, d) in signals(closes) if i >= WARMUP]
    trades = []
    i = 0
    while i < len(sigs):
        si, direction = sigs[i]
        entry = closes[si]
        sl = filt[si]
        risk = (entry - sl) if direction == "long" else (sl - entry)
        if risk <= 0 or risk < MIN_RISK:
            i += 1
            continue
        tp = entry + tp_mult * risk if direction == "long" else entry - tp_mult * risk
        exit_px, ej = None, None
        for j in range(si + 1, len(rows)):
            lo, hi = rows[j]["l"], rows[j]["h"]
            if direction == "long":
                if lo <= sl:
                    exit_px, ej = sl, j
                    break
                if hi >= tp:
                    exit_px, ej = tp, j
                    break
            else:
                if hi >= sl:
                    exit_px, ej = sl, j
                    break
                if lo <= tp:
                    exit_px, ej = tp, j
                    break
        if exit_px is None:
            i += 1
            continue  # صفقة معلقة بنهاية البيانات — تُستبعد
        r = ((exit_px - entry) / risk) if direction == "long" else ((entry - exit_px) / risk)
        trades.append({"dir": direction, "entry": entry, "sl": sl, "tp": tp,
                       "exit": exit_px, "r": round(r, 4),
                       "dur_min": (ej - si) * 15,
                       "t_in": rows[si]["t"], "t_out": rows[ej]["t"],
                       "win": r > 0})
        # تخطي أي إشارات حدثت أثناء الصفقة
        while i < len(sigs) and sigs[i][0] <= ej:
            i += 1
    return trades


def stats(trades):
    n = len(trades)
    if not n:
        return {}
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_p = sum(wins)
    gross_l = abs(sum(losses))
    cum, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return {
        "n": n,
        "win_rate": round(100 * len(wins) / n, 1),
        "avg_r": round(sum(rs) / n, 3),
        "expectancy": round(sum(rs) / n, 3),
        "pf": round(gross_p / gross_l, 2) if gross_l else float("inf"),
        "max_dd_r": round(mdd, 2),
        "avg_dur_min": round(sum(t["dur_min"] for t in trades) / n, 1),
        "total_r": round(sum(rs), 2),
        "longs": sum(1 for t in trades if t["dir"] == "long"),
        "shorts": sum(1 for t in trades if t["dir"] == "short"),
    }


if __name__ == "__main__":
    import json
    out = {}
    for m in (2, 3):
        tr = run(m)
        out[m] = {"trades": tr, "stats": stats(tr)}
    with open("rangefilter_trades.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for m in (2, 3):
        print(f"=== TP {m}R ===")
        for k, v in out[m]["stats"].items():
            print(f"  {k}: {v}")
