#!/usr/bin/env python3
"""حلقة التعلم — تحليل أداء استراتيجيات الذهب وتوصيات التطوير.

يحلل الصفقات المغلقة في الدفتر ويستخرج:
  - معدلات تحقق كل هدف (TP1, TP2|TP1, TP3|TP2)
  - MFE/MAE لكل استراتيجية
  - توصيات تطوير مبنية على قواعد احترافية

الاستخدام:
  python gold_learn.py          — تقرير JSON
  python gold_learn.py report   — تقرير عربي منسق للتنبيه
"""
import json, os, sys
from datetime import datetime

OUT = os.path.expanduser("~/workspace/gold-station")
LEDGER = f"{OUT}/gold_ledger.json"
LEARN_LOG = f"{OUT}/gold_learn_log.json"

def load_ledger():
    with open(LEDGER) as f:
        return json.load(f)

def analyze():
    d = load_ledger()
    closed = [t for t in d["trades"]
              if t.get("status") in ("tp", "sl", "be", "tp3", "trail")]
    by = {}
    for t in closed:
        s = by.setdefault(t["strategy"], {
            "n": 0, "r_sum": 0.0, "wins": 0,
            "tp1": 0, "tp2": 0, "tp3": 0,
            "mfe_sum": 0.0, "mae_sum": 0.0,
            "mae_winners_max": 0.0, "mfe_losers_sum": 0.0, "losers": 0,
        })
        r = t.get("r_multiple") or 0
        s["n"] += 1
        s["r_sum"] += r
        if r > 0:
            s["wins"] += 1
            s["mae_winners_max"] = max(s["mae_winners_max"], t.get("mae_r", 0))
        else:
            s["losers"] += 1
            s["mfe_losers_sum"] += t.get("mfe_r", 0)
        if t.get("tp1_hit"):
            s["tp1"] += 1
        if t.get("tp2_hit"):
            s["tp2"] += 1
        if t.get("tp3_hit"):
            s["tp3"] += 1
        s["mfe_sum"] += t.get("mfe_r", 0)
        s["mae_sum"] += t.get("mae_r", 0)

    strategies = {}
    for name, s in by.items():
        n = s["n"]
        recs = []
        tp1_rate = s["tp1"] / n if n else 0
        tp2_given_tp1 = s["tp2"] / s["tp1"] if s["tp1"] else 0
        tp3_given_tp2 = s["tp3"] / s["tp2"] if s["tp2"] else 0
        avg_r = s["r_sum"] / n if n else 0
        win_rate = s["wins"] / n if n else 0
        avg_mfe = s["mfe_sum"] / n if n else 0
        avg_mae = s["mae_sum"] / n if n else 0
        avg_mfe_losers = s["mfe_losers_sum"] / s["losers"] if s["losers"] else 0

        # --- قواعد التوصيات ---
        if n >= 5:
            if s["tp3"] / n < 0.15 and s["tp1"] > 0:
                recs.append("TP3 يتحقق نادراً (<15%) — ادرس جعل TP2 الهدف النهائي مع تحريك الوقف تحت TP1 بعد تحققه.")
            if tp1_rate < 0.4:
                recs.append(f"فقط {tp1_rate:.0%} يصل للهدف الأول — راجع فلتر الدخول أو قارن توقيت H4 مع M15.")
            if s["mae_winners_max"] < 0.5:
                recs.append(f"الرابحة لا تتراجع أكثر من {s['mae_winners_max']:.1f}R — الوقف الحالي واسع نسبياً، يمكن اختبار تشديده.")
            if avg_mfe_losers > 0.7:
                recs.append(f"الخاسرة تصل بالمتوسط إلى {avg_mfe_losers:.1f}R قبل الوقف — هدف أول أقرب (0.75R) كان سيلتقط جزءاً منها.")
            if win_rate < 0.35 and avg_r < 0 and n >= 8:
                recs.append("توقع سلبي مستمر — أوقف التنبيهات لهذه الاستراتيجية مؤقتاً وراجع شروط الدخول.")
            if tp2_given_tp1 > 0.6:
                recs.append(f"من يصل TP1 يكمل لـ TP2 بنسبة {tp2_given_tp1:.0%} — إبقاء المركز بعد الأول مبرر إحصائياً.")
            if avg_r > 0.3 and n >= 10:
                recs.append("أداء إيجابي مستقر — حافظ على القواعد ولا تغيّر المعاملات.")
        else:
            recs.append(f"عينة صغيرة ({n} صفقات) — لا استنتاجات بعد؛ التوصيات تبدأ من 5 صفقات مغلقة.")

        strategies[name] = {
            "n": n, "win_rate": round(100 * win_rate, 1),
            "avg_r": round(avg_r, 2), "total_r": round(s["r_sum"], 2),
            "tp1_rate": round(100 * tp1_rate, 1),
            "tp2_given_tp1": round(100 * tp2_given_tp1, 1),
            "tp3_given_tp2": round(100 * tp3_given_tp2, 1),
            "avg_mfe_r": round(avg_mfe, 2), "avg_mae_r": round(avg_mae, 2),
            "max_mae_winners_r": round(s["mae_winners_max"], 2),
            "avg_mfe_losers_r": round(avg_mfe_losers, 2),
            "recommendations": recs,
        }

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_closed": len(closed),
        "open_count": len([t for t in d["trades"] if t.get("status") == "open"]),
        "strategies": strategies,
    }

def format_report(a):
    lines = ["📊 تقرير التعلم الأسبوعي — استراتيجيات الذهب",
             f"الصفقات المغلقة: {a['total_closed']} | المفتوحة: {a['open_count']}", ""]
    if not a["strategies"]:
        lines.append("لا صفقات مغلقة بعد — التقرير يبدأ مع أول إغلاق.")
        return "\n".join(lines)
    for name, s in a["strategies"].items():
        lines += [
            f"▪️ {name}: {s['n']} صفقات",
            f"   الفوز: {s['win_rate']}% | متوسط R: {s['avg_r']} | المجموع: {s['total_r']}R",
            f"   TP1: {s['tp1_rate']}% → TP2: {s['tp2_given_tp1']}% → TP3: {s['tp3_given_tp2']}%",
            f"   متوسط MFE: {s['avg_mfe_r']}R | متوسط MAE: {s['avg_mae_r']}R",
        ]
        for r in s["recommendations"]:
            lines.append(f"   💡 {r}")
        lines.append("")
    lines.append("التنبيه للمراقبة والدراسة وليس توصية مالية.")
    return "\n".join(lines)

if __name__ == "__main__":
    a = analyze()
    # سجل تراكمي
    log = []
    if os.path.exists(LEARN_LOG):
        with open(LEARN_LOG) as f:
            log = json.load(f)
    log.append(a)
    with open(LEARN_LOG, "w") as f:
        json.dump(log[-52:], f, ensure_ascii=False, indent=1)  # آخر سنة
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        print(format_report(a))
    else:
        print(json.dumps(a, ensure_ascii=False, indent=1))
