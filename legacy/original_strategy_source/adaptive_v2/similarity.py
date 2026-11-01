"""
Similar-Cases Evaluation — Adaptive V2, Step 5

تقييم «الحالات المشابهة» على استراتيجية واحدة أولاً: ICT 4-Step.

لكل صفقة مغلقة من الاستراتيجية (بترتيب زمني) نبحث عن أقرب K حالات
سابقة مشابهة بخصائص لحظة الفتح، بانضباط Point-in-Time صارم:
- الحالة المرشحة يجب أن تكون قد أُغلقت فعلاً قبل فتح الصفقة موضوع
  البحث (ts_close <= ts_open) — نتيجتها كانت «معروفة» نظرياً وقتها.
- التقييس (mean/std) يُحسب من الماضي فقط ويتوسع زمنياً.

الهدف قياس قيمة الأداة لا صنع إشارات: هل كان متوسط نتائج الجيران
سيحذّر من الخاسرات ويدعم الرابحات؟ لا أثر على المحرك الحي إطلاقاً.

التشغيل: python3 similarity.py [strategy]
المخرجات: shadow/similarity_<strategy>.json + ملخص مطبوع.
"""

import json
import math
import sys
from pathlib import Path

import shadow_observer as so

BASE = Path(__file__).resolve().parent
FEATS = ["atr15_r", "rsi15", "mom5_dir_r", "trend_align_h1",
         "trend_align_h4", "room_r", "hour_sin", "hour_cos", "rr_planned"]
K = 8
MIN_NEIGHBORS = 5


def _vec(f):
    return [f.get(k) for k in FEATS]


def _dist(a, b, mu, sd):
    s, n = 0.0, 0
    for x, y, m, d in zip(a, b, mu, sd):
        if x is None or y is None or not d:
            continue
        s += ((x - y) / d) ** 2
        n += 1
    if n < 4:  # حد أدنى من الخصائص المشتركة لقبول المسافة
        return None
    return math.sqrt(s / n)


def evaluate(strategy="ICT 4-Step"):
    snaps = so.load_snapshots()
    outs = so.load_outcomes()
    rows = []
    for tid, s in snaps.items():
        if s["strategy"] != strategy or tid not in outs:
            continue
        o = outs[tid]
        if not isinstance(o.get("r_multiple"), (int, float)):
            continue
        rows.append({"id": tid, "ts_open": s["ts_open"],
                     "ts_close": o.get("ts_close"),
                     "r": o["r_multiple"], "f": s["features"]})
    rows.sort(key=lambda r: r["ts_open"])

    queries = []
    for q in rows:
        past = [r for r in rows
                if r["id"] != q["id"] and r["ts_close"] and q["ts_close"]
                and r["ts_close"] <= q["ts_open"]]
        if len(past) < MIN_NEIGHBORS:
            continue
        mu, sd = [], []
        for k in FEATS:
            vals = [r["f"].get(k) for r in past if r["f"].get(k) is not None]
            m = sum(vals) / len(vals) if vals else 0.0
            v = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5 if vals else 0.0
            mu.append(m)
            sd.append(v if v > 1e-9 else 1.0)
        scored = []
        for r in past:
            d = _dist(_vec(q["f"]), _vec(r["f"]), mu, sd)
            if d is not None:
                scored.append((d, r))
        if len(scored) < MIN_NEIGHBORS:
            continue
        scored.sort(key=lambda x: x[0])
        neigh = [r for _, r in scored[:K]]
        n_avg = sum(r["r"] for r in neigh) / len(neigh)
        n_win = sum(1 for r in neigh if r["r"] > 0) / len(neigh)
        base = sum(r["r"] for r in past) / len(past)
        flag = ("supportive" if n_avg >= 0.2
                else "warning" if n_avg <= -0.2 else "neutral")
        queries.append({"id": q["id"], "ts_open": q["ts_open"],
                        "actual_r": q["r"], "neighbors": len(neigh),
                        "neighbor_avg_r": round(n_avg, 3),
                        "neighbor_win": round(n_win, 3),
                        "base_avg_r": round(base, 3), "flag": flag})

    def bucket(name):
        b = [q for q in queries if q["flag"] == name]
        if not b:
            return {"n": 0}
        return {"n": len(b),
                "actual_avg_r": round(sum(q["actual_r"] for q in b) / len(b), 3),
                "actual_win_rate": round(
                    sum(1 for q in b if q["actual_r"] > 0) / len(b), 3)}

    corr = None
    if len(queries) >= 5:
        xs = [q["neighbor_avg_r"] for q in queries]
        ys = [q["actual_r"] for q in queries]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs) ** 0.5
        vy = sum((y - my) ** 2 for y in ys) ** 0.5
        corr = round(cov / (vx * vy), 3) if vx and vy else None

    summary = {
        "strategy": strategy,
        "closed_trades": len(rows),
        "queries_evaluated": len(queries),
        "correlation_neighbor_vs_actual": corr,
        "buckets": {n: bucket(n) for n in ("supportive", "neutral", "warning")},
    }
    out = BASE / "shadow" / f"similarity_{strategy.replace(' ', '_')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "queries": queries},
                              ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


if __name__ == "__main__":
    evaluate(sys.argv[1] if len(sys.argv) > 1 else "ICT 4-Step")
