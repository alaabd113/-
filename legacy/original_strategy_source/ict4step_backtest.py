#!/usr/bin/env python3
"""باكتست ICT 4-Step — محاكاة شمعة-بشمعة على 15M مع سياق 4H (2026-08-26 ← الآن).

المتغيرات A (دخول مباشر من FVG)، A2 (دخول 50% دائماً)، A3 (التعادل عند TP2)،
A4 (كلاهما)، B (CISD) منفصلة.
الإدارة: الوقف أولاً داخل الشمعة (محافظ)؛ TP1=1R → إغلاق ثلث (+تعادل عند TP1 إلا في A3/A4
حيث يتأخر التعادل إلى TP2)؛ TP2=2R → ثلث؛ TP3=3R → الباقي.
سبريد 0.30$؛ صفقة واحدة كل مرة لكل متغير؛ حد أقصى 96 شمعة (24 سا) ثم إغلاق سوقي.
"""
import sys
sys.path.insert(0, '/home/hatch/workspace/gold-station')
from candle_db import read
from gold_ict4step import detect, P

M15 = read(interval="15min", limit=6000)
H4 = read(interval="4h", limit=2000)
SPREAD = P["spread"]
MAX_HOLD = 96   # شمعة 15m
FILL_WINDOW = 12


def simulate_variant(variant):
    trades = []
    open_pos = None
    i = 320
    n = len(M15)
    while i < n:
        # 4H حتى لحظة الشمعة الحالية
        t = M15[i]["t"]
        h4u = [c for c in H4 if c["t"] <= t]
        m15u = M15[:i + 1]
        if open_pos is None and len(h4u) >= 40:
            sigs = detect(h4u, m15u, variant)
            if sigs:
                s = sigs[0]
                is_buy = s["dir"] == "شراء"
                entry = s["entry"] + (SPREAD if is_buy else -SPREAD)
                risk = abs(entry - s["sl"])
                if risk >= 0.5:
                    open_pos = {"sig": s, "is_buy": is_buy, "entry": entry,
                                "sl": s["sl"], "risk": risk, "tp": s["_tp_ext"],
                                "tps": [s["tp1"], s["tp2"], s["tp3"]],
                                "mgmt": s.get("mgmt", "be_tp1"),
                                "i_open": i, "banked": 0.0, "parts": 0, "be": False,
                                "filled": variant == "B", "t_open": s["t"]}
                    if variant == "B":
                        open_pos["t_open"] = t
        if open_pos is not None:
            p = open_pos
            filled = p["filled"]
            j = i if variant == "B" else i + 1
            done = False
            while j < min(i + (1 if variant == "B" else FILL_WINDOW + 1), n):
                c = M15[j]
                if not filled:
                    # أمر حدّ: لمس مستوى الدخول الأصلي
                    lv = p["sig"]["entry"]
                    touch = (c["l"] <= lv) if p["is_buy"] else (c["h"] >= lv)
                    sl_breach = (c["l"] <= p["sl"]) if p["is_buy"] else (c["h"] >= p["sl"])
                    if sl_breach and touch:
                        trades.append(-1.0)  # محافظ: فُتح وضُرب فوراً
                        done = True
                        break
                    if touch:
                        filled = True
                        p["filled"] = True
                        p["i_open"] = j
                        # أكمل لفحص الوقف/الأهداف من هذه الشمعة
                    else:
                        j += 1
                        continue
                # وقف أولاً (محافظ)
                sl_now = p["entry"] if p["be"] else p["sl"]
                hit_sl = (c["l"] <= sl_now) if p["is_buy"] else (c["h"] >= sl_now)
                if hit_sl:
                    r = p["banked"] + (3 - p["parts"]) * (0 if p["be"] else -1) / 3
                    trades.append(round(r, 3))
                    done = True
                    break
                # الأهداف بالترتيب (التعادل عند TP1 أو يتأخر إلى TP2 حسب mgmt)
                be_k = 1 if p["mgmt"] == "be_tp2" else 0
                for k, tp in enumerate(p["tps"]):
                    if k < p["parts"]:
                        continue
                    hit = (c["h"] >= tp) if p["is_buy"] else (c["l"] <= tp)
                    if not hit:
                        continue
                    p["parts"] += 1
                    p["banked"] += (k + 1) / 3
                    if k == be_k:
                        p["be"] = True
                        be_hit = (c["l"] <= p["entry"]) if p["is_buy"] else (c["h"] >= p["entry"])
                        if be_hit:
                            trades.append(round(p["banked"], 3))
                            done = True
                            break
                    if k == 2 or p["parts"] == 3:
                        trades.append(round(p["banked"], 3))
                        done = True
                        break
                if done:
                    break
                # انتهت المهلة؟
                if j - p["i_open"] >= MAX_HOLD:
                    cur = M15[j]["c"]
                    # R المتبقي على الأجزاء المفتوحة فقط
                    r = p["banked"] + (3 - p["parts"]) / 3 * ((cur - p["entry"]) / p["risk"] * (1 if p["is_buy"] else -1))
                    trades.append(round(max(r, -1.0), 3))
                    done = True
                    break
                j += 1
            limit_j = min(i + (1 if variant == "B" else FILL_WINDOW + 1), n)
            data_end = (limit_j == n)
            if not done:
                if data_end and p["filled"]:
                    # انتهت البيانات وصفقة مفتوحة: تُقيَّم على آخر إغلاق
                    cur = M15[-1]["c"]
                    r = p["banked"] + (3 - p["parts"]) / 3 * ((cur - p["entry"]) / p["risk"] * (1 if p["is_buy"] else -1))
                    trades.append(round(max(r, -1.0), 3))
                # وإلا: نافذة الملء انتهت بلا تنفيذ → تُهمل (لا صفقة)
                open_pos = None
                i = j + 1
                continue
            if done:
                open_pos = None
                i = j + 1
                continue
        i += 1
    return trades


def stats(trades):
    n = len(trades)
    if not n:
        return {"n": 0}
    wins = [r for r in trades if r > 0]
    losses = [r for r in trades if r <= 0]
    avg = sum(trades) / n
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")
    # أقصى تراجع تراكمي
    eq, peak, mdd = 0, 0, 0
    for r in trades:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return {"n": n, "win": round(100 * len(wins) / n, 1), "avg_r": round(avg, 3),
            "total_r": round(sum(trades), 2), "pf": round(pf, 2) if pf != float("inf") else "inf",
            "mdd_r": round(mdd, 2)}


if __name__ == "__main__":
    import json
    out = {}
    for v in ("A", "A2", "A3", "A4", "B"):
        tr = simulate_variant(v)
        out[v] = {**stats(tr), "trades": tr}
        print(v, stats(tr), flush=True)
    with open("/home/hatch/workspace/gold-station/ict4step_backtest.json", "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print("BT DONE")
