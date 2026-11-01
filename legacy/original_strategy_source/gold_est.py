#!/usr/bin/env python3
"""ماسح EST 20:00 الحي — XAUUSD 1H (شراء فقط).
القواعد من: fb-video-extraction/daniel-harper/videos/2492274317932091/2492274317932091-quant.md
المتغير المعتمد: longonly(bias,2R) — باكتست: 14 صفقة، +0.811R/صفقة، PF 3.19 (بيانات نظيفة).
الإدارة: مركز كامل (mgmt=full) — وقف خلف المستوى، هدف 2R، بلا تجزئة ولا تعادل (كما في الباكتست).
"""
import json, os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from market_hours import require_market_open
from candle_db import get_candles
import sys
sys.path.insert(0, os.path.expanduser("~/workspace/gold-station/harper_backtests"))
from est_deep_dive import us_dst, atr_at, ATR_P, SL_BUF_ATR, SCAN_AFTER

TZ = ZoneInfo("Asia/Damascus")
OUT = os.path.expanduser("~/workspace/gold-station")
ATR_MIN = 3.0  # حد أدنى لمخاطرة عقلانية

def anchor_hour(dt):
    return 3 if us_dst(dt.date()) else 2  # تعليمات علاء: صيفاً 03:00-04:00، شتاءً 02:00-03:00

def main():
    require_market_open()
    now = datetime.now(TZ).replace(tzinfo=None)
    h1 = get_candles("1h", 96)
    # إسقاط الشمعة المتشكلة (آخر شمعة لم تغلق بعد)
    if h1:
        last_t = datetime.strptime(h1[-1]["t"], "%Y-%m-%d %H:%M:%S")
        if last_t + timedelta(hours=1) > now:
            h1 = h1[:-1]
    signals = []
    # ابحث عن شمعة التثبيت (anchor) لليوم الحالي والأمس
    for back in (0, 1):
        day = (datetime.now(TZ).date() - timedelta(days=back))
        ah = anchor_hour(datetime(day.year, day.month, day.day))
        anchor = None
        for i, x in enumerate(h1):
            dt = datetime.strptime(x["t"], "%Y-%m-%d %H:%M:%S")
            if dt.date() == day and dt.hour == ah and dt.minute == 0:
                anchor = (i, x)
                break
        if not anchor:
            continue
        ai, a = anchor
        hi, lo = a["h"], a["l"]
        if hi <= lo:
            continue
        a_bull = a["c"] >= a["o"]
        bias = "short" if a_bull else "long"  # عكس اللون [صريح]
        if bias != "long":
            continue  # شراء فقط
        atr = atr_at(h1, ai, ATR_P)
        if not atr:
            continue
        # البحث عن الكنس — الإشارة فقط إذا كانت على آخر شمعة مغلقة (طازجة)
        ji = len(h1) - 1
        if ji <= ai or ji > ai + SCAN_AFTER:
            continue
        x = h1[ji]
        sw_l = x["l"] < lo
        sw_h = x["h"] > hi
        sig = None
        if sw_l and x["c"] >= lo and not (sw_h and x["c"] <= hi):
            sig = ("long", ji, lo)
        if not sig:
            continue
        direction, _, level = sig
        entry = x["c"]
        risk = abs(level - entry) + SL_BUF_ATR * atr
        sl = level - SL_BUF_ATR * atr
        risk = abs(entry - sl)
        if risk < ATR_MIN:
            continue
        tp = entry + 2 * risk
        key = f"EST|{day.isoformat()}|long"
        signals.append({
            "strategy": "EST 20:00", "dir": "شراء", "entry": round(entry, 2),
            "sl": round(sl, 2), "tp1": round(tp, 2), "tp2": round(tp, 2), "tp3": round(tp, 2),
            "rr": 2.0, "key": key, "t": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "mgmt": "full",
            "reason": (f"شمعة 20:00 EST هابطة ({day}) — كنس قاعها {lo:.2f} مع فشل الإغلاق تحته، "
                       f"إغلاق شمعة الكنس {entry:.2f} — انعكاس شرائي بعكس لون الشمعة المثبتة"),
            "assumptions": "A-SL: وقف خلف المستوى + 0.25×ATR؛ هدف 2R؛ مركز كامل بلا تجزئة (كما في الباكتست)",
        })
        break  # إشارة واحدة يومياً كحد أقصى
    with open(os.path.join(OUT, "gold_est.json"), "w") as f:
        json.dump({"signals": signals, "at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=1)
    # الشارت
    try:
        plot(h1, signals)
    except Exception as e:
        print("plot skip:", e)
    print(json.dumps({"signals": signals}, ensure_ascii=False))
    print("EST DONE")

def plot(h1, signals):
    tail = h1[-48:]
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
    xs = list(range(len(tail)))
    for i, c in enumerate(tail):
        col = "#26a69a" if c["c"] >= c["o"] else "#ef5350"
        ax.plot([i, i], [c["l"], c["h"]], color=col, lw=1)
        ax.add_patch(plt.Rectangle((i - .3, min(c["o"], c["c"])), .6, abs(c["c"] - c["o"]) or .01,
                                   color=col, alpha=.9))
    if signals:
        s = signals[0]
        ax.axhline(s["entry"], color="#ffd54f", ls="--", lw=1.2, label=f"دخول {s['entry']}")
        ax.axhline(s["sl"], color="#ef5350", ls="--", lw=1.2, label=f"وقف {s['sl']}")
        ax.axhline(s["tp1"], color="#26a69a", ls="--", lw=1.2, label=f"هدف 2R {s['tp1']}")
        ax.legend(facecolor="#161b22", labelcolor="white", fontsize=8)
    ax.set_title("XAUUSD 1H — EST 20:00 (long only)", color="white")
    ax.tick_params(colors="white", labelsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "gold_est.png"), dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)

if __name__ == "__main__":
    main()
