#!/usr/bin/env python3
"""باكتست شمعة-بشمعة لاستراتيجية سكالبينج FVG (15M+1M) — نسخة فلتر الجلسات.

نفس قواعد gold_fvg_scalp.py ومنطق fvg_scalp_backtest.py حرفياً، مع اختلاف
واحد فقط (موثق أدناه): فلتر جلسات لندن+نيويورك على شمعة الإشارة.

القرار (بطلب علاء 2026-10-18): تُقبل الإشارة فقط إذا كانت شمعة الإشارة
(FVG على فريم الدقيقة) ضمن نافذة لندن+نيويورك بتوقيت دمشق:
  - لندن 08:00–17:00 BST = 10:00–19:00 دمشق (دمشق UTC+3، لندن الصيفية UTC+1)
  - نيويورك 08:00–17:00 EDT = 15:00–24:00 دمشق (نيويورك الصيفية UTC-4)
  - النافذة المشتركة: 10:00 ← 23:59 بتوقيت دمشق
الطوابع في candles.db مخزنة بتوقيت دمشق naive، فيُقرأ الـ hour مباشرة.

ملاحظة تصميمية: الفلتر على شمعة الإشارة فقط (وليس على الملء أو إدارة
الصفقة) — هذا هو التطبيق المعياري لفلتر الجلسات: تُؤخذ الإشارات أثناء
الجلسة، وإدارة الصفقة تتبعها حتى لو تجاوزت النافذة.

الإدارة: TP1 → إغلاق 50% + وقف للتعادل، TP2 → إغلاق الباقي.
الوقف أولاً داخل الشمعة (محافظ). سبريد 0.30$.

افتراضات الباكتست (B):
  B1. صفقة واحدة فقط في كل مرة — إشارات أثناء صفقة مفتوحة تُتجاهل.
  B2. الدخول: أمر حدّ عند حافة الفجوة؛ يُملأ إذا لامس أي من الشموع الثلاث
      التالية مستوى الدخول، وإلا تُهمل الإشارة (فرصة ضائعة).
  B3. حد أقصى للاحتجاز 1440 شمعة (24h) — خروج بسعر السوق عندها.
  B4. فلتر الجلسات: لندن+نيويورك فقط (10:00–23:59 دمشق) — بدل «لا فلتر» بالأصلي.
"""
import bisect
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_fvg_scalp as S
from candle_db import read

OUT = os.path.dirname(os.path.abspath(__file__))
INF = float("inf")

# نافذة الجلسات بتوقيت دمشق (شاملة): 10:00 ← 23:59
SESSION_H0, SESSION_H1 = 10, 23


def in_session(t_str):
    """هل الطابع (دمشق naive بصيغة YYYY-MM-DD HH:MM:SS) ضمن نافذة الجلسات؟"""
    h = int(t_str[11:13])
    return SESSION_H0 <= h <= SESSION_H1


def run_session(max_hold=1440, tp_cap_r=None, tag="session"):
    """تشغيل واحد للباكتست مع فلتر الجلسات. يُرجع (trades, stats).
    tp_cap_r: سقف لهدف TP2 بوحدة R (None = بلا سقف)."""
    m1 = read(interval="1min", limit=30000)
    m15 = read(interval="15min", limit=3000)
    t15 = [k["t"] for k in m15]

    # TR مسبق لـ ATR15
    tr15 = [0.0]
    for i in range(1, len(m15)):
        h, l, pc = m15[i]["h"], m15[i]["l"], m15[i - 1]["c"]
        tr15.append(max(h - l, abs(h - pc), abs(l - pc)))

    def atr15_upto(u):
        seg = tr15[max(1, u - S.ATR_P):u]
        return sum(seg) / len(seg) if seg else 0.0

    # OBs على 15m + مؤشر الاستهلاك وأول ارتداد (محسوبة مرة واحدة)
    obs = S.find_obs(m15)
    for z in obs:
        mit, bnc = INF, INF
        for j in range(z["i"] + 1, len(m15)):
            k = m15[j]
            if z["dir"] == "buy":
                if mit is INF and k["c"] < z["bot"]:
                    mit = j
                if bnc is INF and k["l"] < z["top"] and k["c"] > z["top"]:
                    bnc = j
            else:
                if mit is INF and k["c"] > z["top"]:
                    mit = j
                if bnc is INF and k["h"] > z["bot"] and k["c"] < z["bot"]:
                    bnc = j
            if mit is not INF and bnc is not INF:
                break
        z["mit"], z["bnc"] = mit, bnc

    fvgs = S.find_fvgs(m1)
    print(f"FVGs on 1m: {len(fvgs)}", flush=True)

    trades = []
    in_pos_until = -1
    WARM = 300
    n_fvg_total = 0
    n_fvg_session = 0

    for f in fvgs:
        i = f["i"]
        if i < WARM or i <= in_pos_until:
            continue
        # ===== فلتر الجلسات — الاختلاف الوحيد عن fvg_scalp_backtest.py =====
        n_fvg_total += 1
        if not in_session(m1[i]["t"]):
            continue
        n_fvg_session += 1
        # ==================================================================
        side = f["dir"]
        sgn = 1 if side == "buy" else -1
        u = bisect.bisect_right(t15, m1[i]["t"])
        if u < 60:
            continue
        a15 = atr15_upto(u)
        if a15 <= 0:
            continue
        # منطقة 15M: الأحدث المؤهلة
        zones = [z for z in obs if z["dir"] == side and z["i"] < u
                 and z["mit"] >= u and z["bnc"] < u]
        if not zones:
            continue
        zone = zones[-1]
        if not S.near_zone(m1[i]["c"], zone, a15):
            continue
        # الدخول والوقف
        if side == "buy":
            entry = f["bot"] - S.SPREAD
            sl = min(k["l"] for k in m1[i - 2:i + 1])
        else:
            entry = f["top"] + S.SPREAD
            sl = max(k["h"] for k in m1[i - 2:i + 1])
        risk = sgn * (entry - sl)
        if risk < S.MIN_RISK:
            continue
        if sgn * (m1[i]["c"] - entry) > S.STALE_K * risk:
            continue
        # الهدف: أبعد OB معاكس غير مستهلك ضمن 8×ATR15 (A9 معدّلة per الفيديو:
        # «الهدف لآخر حاجة فوق» والبلوكات الوسيطة أهداف مرحلية)
        opp = "sell" if side == "buy" else "buy"
        cands = []
        for z in obs:
            if z["dir"] != opp or z["i"] >= u or z["mit"] < u:
                continue
            lv = z["bot"] if side == "buy" else z["top"]
            d = sgn * (lv - entry)
            if 0 < d <= 8 * a15:
                cands.append((d, lv))
        if not cands:
            continue
        cands.sort(key=lambda x: x[0])
        tp2 = cands[-1][1]                        # الأبعد
        if tp_cap_r is not None:                   # سقف R:R للهدف
            cap = entry + sgn * tp_cap_r * risk
            if sgn * (tp2 - entry) > sgn * (cap - entry):
                tp2 = cap
        if sgn * (tp2 - entry) < S.MIN_TP_RR * risk:
            continue
        tp1 = None
        for d, lv in cands[:-1]:                   # أول وسيط >= 1R
            if sgn * (lv - entry) >= risk:
                tp1 = lv
                break
        # B2: الملء خلال 3 شموع
        filled, jf = False, None
        for j in range(i + 1, min(i + 4, len(m1))):
            k = m1[j]
            if (side == "buy" and k["l"] <= entry) or (side == "sell" and k["h"] >= entry):
                filled, jf = True, j
                break
        if not filled:
            continue
        # المحاكاة — صريحة لكل اتجاه (الوقف أولاً داخل الشمعة: محافظ)
        r1 = sgn * (tp1 - entry) / risk if tp1 else 0.0
        r2 = sgn * (tp2 - entry) / risk
        cur_sl, half = sl, False
        res, exit_t, dur, why = None, None, 0, ""
        for j in range(jf + 1, min(jf + max_hold + 1, len(m1))):
            k = m1[j]
            dur = j - jf
            if side == "buy":
                if k["l"] <= cur_sl:                  # الوقف أولاً
                    res = (-1.0 if not half else 0.5 * r1)
                    exit_t, why = k["t"], ("SL" if not half else "BE بعد TP1")
                    break
                if tp1 and not half and k["h"] >= tp1:
                    half, cur_sl = True, entry       # إغلاق 50% + تعادل
                    continue
                if k["h"] >= tp2:
                    res = (r2 if not half else 0.5 * r1 + 0.5 * r2)
                    exit_t, why = k["t"], "TP2"
                    break
            else:
                if k["h"] >= cur_sl:                  # الوقف أولاً
                    res = (-1.0 if not half else 0.5 * r1)
                    exit_t, why = k["t"], ("SL" if not half else "BE بعد TP1")
                    break
                if tp1 and not half and k["l"] <= tp1:
                    half, cur_sl = True, entry
                    continue
                if k["l"] <= tp2:
                    res = (r2 if not half else 0.5 * r1 + 0.5 * r2)
                    exit_t, why = k["t"], "TP2"
                    break
        else:
            j = min(jf + max_hold, len(m1) - 1)
            px = m1[j]["c"]
            rr_exit = sgn * (px - entry) / risk
            res = (rr_exit if not half else 0.5 * r1 + 0.5 * rr_exit)
            exit_t, why = m1[j]["t"], f"مهلة {max_hold//60}h"
            dur = j - jf
        in_pos_until = j
        trades.append({"side": side, "entry": round(entry, 2), "sl": round(sl, 2),
                       "tp1": round(tp1, 2) if tp1 else None,
                       "tp2": round(tp2, 2), "r": round(res, 3),
                       "t_in": m1[jf]["t"], "t_out": exit_t, "dur": dur, "why": why,
                       "risk": round(risk, 2)})

    # الإحصائيات
    n = len(trades)
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    winrate = len(wins) / n if n else 0
    avg_r = sum(rs) / n if n else 0
    gp = sum(wins)
    gl = -sum(r for r in rs if r < 0)
    pf = gp / gl if gl > 0 else float("inf")
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    avg_dur = sum(t["dur"] for t in trades) / n if n else 0
    longs = sum(1 for t in trades if t["side"] == "buy")
    shorts = n - longs
    why_c = {}
    for t in trades:
        why_c[t["why"]] = why_c.get(t["why"], 0) + 1
    return trades, {"tag": tag, "n": n, "longs": longs, "shorts": shorts,
                    "winrate": winrate, "avg_r": avg_r, "total_r": sum(rs),
                    "pf": pf, "mdd": mdd, "avg_dur": avg_dur, "why": why_c,
                    "rs": rs,
                    "n_fvg_total": n_fvg_total, "n_fvg_session": n_fvg_session}


def main():
    variants = [
        (1440, None, "A: الأساس (مهلة 24h، بلا سقف هدف) + فلتر الجلسات"),
        (60, None, "B: سكالبينج حقيقي (مهلة 60 دقيقة) + فلتر الجلسات"),
        (60, 4.0, "C: مهلة 60 دقيقة + سقف الهدف 4R + فلتر الجلسات"),
    ]
    all_stats = []
    base_trades = None
    for mh, cap, tag in variants:
        trades, st = run_session(max_hold=mh, tp_cap_r=cap, tag=tag)
        all_stats.append(st)
        if base_trades is None:
            base_trades = trades
        print(f"{tag}: n={st['n']} win={st['winrate']:.0%} avgR={st['avg_r']:+.3f} "
              f"total={st['total_r']:+.1f}R pf={st['pf']:.2f} mdd={st['mdd']:.1f}R "
              f"(FVG بالجلسة {st['n_fvg_session']}/{st['n_fvg_total']})",
              flush=True)

    m1 = read(interval="1min", limit=30000)
    md = f"""# باكتست سكالبينج FVG — 15M+1M (XAUUSD) — فلتر جلسات لندن+نيويورك
الفترة: {m1[0]['t']} ← {m1[-1]['t']} (شموع 1m: {len(m1)} — ~19 يوم تداول)
القواعد: نفس gold_fvg_scalp.py (A1-A11) + افتراضات B1-B3 + فلتر الجلسات (B4 معدّلة) | سبريد 0.30$

فلتر الجلسات: تُقبل الإشارة فقط إذا كانت شمعة الإشارة (FVG على الدقيقة)
ضمن 10:00 ← 23:59 بتوقيت دمشق — لندن 08:00–17:00 BST (10:00–19:00 دمشق)
ونيويورك 08:00–17:00 EDT (15:00–24:00 دمشق). الطوابع في القاعدة بتوقيت دمشق.

## النتائج (3 سيناريوهات — مع فلتر الجلسات)
| السيناريو | الصفقات | شراء/بيع | الفوز | متوسط R | مجموع R | PF | MDD | متوسط المدة |
|---|---|---|---|---|---|---|---|---|
"""
    for st in all_stats:
        md += (f"| {st['tag']} | {st['n']} | {st['longs']}/{st['shorts']} | "
               f"{st['winrate']:.1%} | {st['avg_r']:+.3f}R | {st['total_r']:+.1f}R | "
               f"{st['pf']:.2f} | {st['mdd']:.1f}R | {st['avg_dur']:.0f} د |\n")
    md += (f"\n## تغطية الفلتر\n- FVGs مفحوصة: {all_stats[0]['n_fvg_session']} ضمن الجلسة من أصل "
           f"{all_stats[0]['n_fvg_total']} (بعد WARM وقاعدة الصفقة الواحدة)\n")
    md += "\n## أسباب الخروج (السيناريو A)\n"
    for w, c in sorted(all_stats[0]["why"].items()):
        md += f"- {w}: {c}\n"
    rs = sorted(all_stats[0]["rs"])
    md += "\n## توزيع R (السيناريو A، مرتب)\n`" + ", ".join(f"{r:+.2f}" for r in rs) + "`\n"
    no_out = [r for r in rs if r < 5]
    if no_out:
        md += (f"\n## بدون الصفقات الشاذة (≥5R)\n"
               f"n={len(no_out)} | مجموع {sum(no_out):+.2f}R | متوسط {sum(no_out)/len(no_out):+.3f}R | "
               f"فوز {sum(1 for r in no_out if r>0)/len(no_out):.0%}\n")
    else:
        md += "\n## بدون الصفقات الشاذة (≥5R)\nلا صفقات شاذة ≥5R في هذه النسخة.\n"
    md += """
## ملاحظات
- الدخول: أمر حدّ عند حافة الفجوة يُملأ إذا لامسها السعر خلال 3 شموع (B2)؛ الفرص الضائعة غير محسوبة.
- الوقف يُفحص قبل الأهداف داخل الشمعة (محافظ).
- صفقة واحدة في كل مرة (B1)؛ الفلتر على شمعة الإشارة فقط — إدارة الصفقة تتبعها حتى لو تجاوزت النافذة.
- المقارنة المرجعية (بدون فلتر): A ‏27 صفقة +0.98R (وهمي — صفقتان شاذتان 11R و27R)، B ‏+0.22R، C ‏-0.06R.
"""
    with open(os.path.join(OUT, "fvg_scalp_backtest_session.md"), "w") as fo:
        fo.write(md)
    with open(os.path.join(OUT, "fvg_scalp_backtest_session.json"), "w") as fo:
        json.dump({"trades": base_trades,
                   "variants": [{k: (round(v, 4) if isinstance(v, float) else v)
                                 for k, v in st.items() if k != "rs"}
                                for st in all_stats]},
                  fo, ensure_ascii=False)
    print("كُتب fvg_scalp_backtest_session.md")


if __name__ == "__main__":
    main()
