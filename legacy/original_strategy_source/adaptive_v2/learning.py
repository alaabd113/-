"""
Learning Loop + Versioning — Adaptive V2, Step 6

حلقة التعلم الظلية: تجمع مخرجات المراقب (3) والمحاكي (4) والحالات
المشابهة (5) في تقرير دوري واحد مرقّم الإصدار، مع تقييم Walk-Forward
زمني (طيّات متتابعة — لا خلط عشوائياً) ومقارنة بخط الأساس المجمّد.

قواعد:
- التقرير يصف ولا يقرر: بوابة الترقية للحي تبقى موافقة علاء الصريحة
  + عيّنة ظل أمامية 30–50 صفقة (تُقاس من إطلاق V2 لا رجعياً).
- أي رقم في التقرير محسوب من ملفات shadow/ والدفتر المقروء فقط.

التشغيل: python3 learning.py
المخرجات: reports/learning_<date>.md + versions.json + VERSIONS.md
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import shadow_observer as so

BASE = Path(__file__).resolve().parent
SHADOW = BASE / "shadow"
REPORTS = BASE / "reports"
VERSION = "0.1.0"
BASELINE = {"closed": 109, "total_r": -12.70, "win_rate": 0.330,
            "at": "2026-10-20 17:32:00"}
FORWARD_FROM = "2026-10-20 17:32:00"  # لحظة تجميد خط الأساس
TZ = ZoneInfo("Asia/Damascus")


def _stats(rs):
    n = len(rs)
    if not n:
        return {"n": 0, "win": None, "avg": None, "total": 0.0}
    return {"n": n,
            "win": round(sum(1 for r in rs if r > 0) / n, 3),
            "avg": round(sum(rs) / n, 3),
            "total": round(sum(rs), 2)}


def _register_version():
    reg_f = BASE / "versions.json"
    reg = json.loads(reg_f.read_text()) if reg_f.exists() else []
    if not any(v["version"] == VERSION for v in reg):
        reg.append({
            "version": VERSION,
            "date": datetime.now(TZ).strftime("%Y-%m-%d"),
            "components": ["market_data", "shadow_observer", "simulator",
                           "similarity", "learning"],
            "note": "اكتمال طبقة الظل (خطوات 3–6) بقرار علاء 2026-10-21 — "
                    "قراءة فقط، لا أثر على المحرك الحي.",
        })
        reg_f.write_text(json.dumps(reg, ensure_ascii=False, indent=1))
        md = BASE / "VERSIONS.md"
        with md.open("a") as f:
            f.write(f"\n## v{VERSION} — {reg[-1]['date']}\n\n"
                    f"- المكونات: {', '.join(reg[-1]['components'])}\n"
                    f"- {reg[-1]['note']}\n")
    return reg


def run():
    _register_version()
    snaps = so.load_snapshots()
    outs = so.load_outcomes()
    joined = []
    for tid, o in outs.items():
        if tid in snaps and isinstance(o.get("r_multiple"), (int, float)):
            joined.append({"id": tid, "strategy": snaps[tid]["strategy"],
                           "ts_open": snaps[tid]["ts_open"],
                           "r": o["r_multiple"]})
    joined.sort(key=lambda x: x["ts_open"])

    overall = _stats([j["r"] for j in joined])
    forward = [j for j in joined if j["ts_open"] > FORWARD_FROM]
    fwd = _stats([j["r"] for j in forward])

    by_strat = defaultdict(list)
    for j in joined:
        by_strat[j["strategy"]].append(j["r"])
    strat_rows = sorted(((s, _stats(rs)) for s, rs in by_strat.items()),
                        key=lambda x: -x[1]["n"])

    # Walk-Forward: 3 طيّات زمنية متتابعة على كل الصفقات المغلقة
    folds = []
    if len(joined) >= 9:
        k = len(joined) // 3
        for i in range(3):
            part = joined[i * k:(i + 1) * k] if i < 2 else joined[2 * k:]
            st = _stats([j["r"] for j in part])
            st["window"] = f"{part[0]['ts_open'][:10]} → {part[-1]['ts_open'][:10]}"
            folds.append(st)

    sim = {}
    sim_f = SHADOW / "sim_report.json"
    if sim_f.exists():
        sim = json.loads(sim_f.read_text()).get("summary", {})
    simi = {}
    simi_f = SHADOW / "similarity_ICT_4-Step.json"
    if simi_f.exists():
        simi = json.loads(simi_f.read_text()).get("summary", {})

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    gate_met = 30 <= fwd["n"]
    gate_txt = ("مستوفاة عددياً — القرار لعلاء" if gate_met
                else f"غير مستوفاة بعد ({fwd['n']}/30)")
    lines = [
        f"# تقرير تعلم Adaptive V2 — v{VERSION} — {today}",
        "",
        f"- لقطات الخصائص: {len(snaps)} — نتائج مربوطة: {len(joined)}",
        f"- الكل: {overall['n']} مغلقة — فوز {overall['win']} — "
        f"متوسط {overall['avg']}R — مجموع {overall['total']}R",
        f"- خط الأساس المجمّد (2026-10-20): {BASELINE['closed']} مغلقة — "
        f"مجموع {BASELINE['total_r']}R — فوز {BASELINE['win_rate']}",
        f"- العيّنة الأمامية منذ التجميد: {fwd['n']} صفقة — مجموع {fwd['total']}R",
        f"- بوابة الترقية (عيّنة أمامية 30–50): {gate_txt}",
        "",
        "## حسب الاستراتيجية (كل المغلقات)",
        "",
        "| الاستراتيجية | عدد | فوز | متوسط R | مجموع R |",
        "|---|---|---|---|---|",
    ]
    for s, st in strat_rows:
        lines.append(f"| {s} | {st['n']} | {st['win']} | {st['avg']} | {st['total']} |")
    if folds:
        lines += ["", "## Walk-Forward — 3 طيّات زمنية", "",
                  "| الطيّة | النافذة | عدد | فوز | متوسط R |", "|---|---|---|---|---|"]
        for i, fd in enumerate(folds, 1):
            lines.append(f"| {i} | {fd['window']} | {fd['n']} | {fd['win']} | {fd['avg']} |")
    if sim:
        lines += ["", "## مطابقة المحاكي مع الدفتر الفعلي", "",
                  f"- أُعيد تشغيل {sim.get('simulated')} صفقة — مطابقة ضمن "
                  f"±0.15R: {sim.get('match_rate')} — متوسط الانحراف المطلق "
                  f"{sim.get('mean_abs_delta')}R",
                  f"- مجموع المحاكاة (أساسي/×1.5/×2): {sim.get('sim_total_base')} / "
                  f"{sim.get('sim_total_x15')} / {sim.get('sim_total_x2')} مقابل فعلي "
                  f"{sim.get('actual_total')}R لنفس الصفقات",
                  "- الفجوة لا تعني خطأ بأي طرف: المحاكي على فيدنا المخزّن "
                  "والدفتر على فيد البروكر/المزود وقتها — الفروقات موثقة "
                  "ومركّزة بصفقات الحركة السريعة والمسجلة باصطلاحات قديمة."]
    if simi:
        b = simi.get("buckets", {})
        lines += ["", "## الحالات المشابهة — ICT 4-Step", "",
                  f"- استعلامات قُيّمت: {simi.get('queries_evaluated')} من "
                  f"{simi.get('closed_trades')} مغلقة — ارتباط الجيران بالنتيجة "
                  f"الفعلية: {simi.get('correlation_neighbor_vs_actual')}",
                  f"- «داعمة» (n={b.get('supportive', {}).get('n')}): نتيجة فعلية "
                  f"بمتوسط {b.get('supportive', {}).get('actual_avg_r')}R — "
                  "الأداة بشكلها الحالي **لا قيمة تنبؤية لها** على هذه العيّنة "
                  "ولا تُستخدم بأي قرار."]
    lines += ["", "## قرار", "",
              "لا ترقية ولا تعديل على المحرك الحي — هذا التقرير للعرض على "
              "علاء فقط، وأي خطوة نحو الحي تحتاج موافقته الصريحة."]
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"learning_{today}.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"learning v{VERSION}: closed={overall['n']} total={overall['total']}R "
          f"forward={fwd['n']} gate={'met' if gate_met else 'not yet'} -> {out.name}")
    return {"overall": overall, "forward": fwd, "report": str(out)}


if __name__ == "__main__":
    run()
