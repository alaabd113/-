#!/usr/bin/env python3
"""ماسح Range Filter — XAUUSD 15m — استراتيجية مستقلة.

المنطق: إشارات انعكاس range_filter.signals على الشموع المغلقة المؤكدة فقط.
إدارة المخاطر (المعتمدة لدينا): الوقف = خط الفلتر عند الدخول،
TP1=1R وTP2=2R وTP3=3R — الدفتر يغلق ثلث المركز عند كل هدف وينقل الوقف للتعادل بعد TP1.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from market_hours import require_market_open
from candle_db import get_candles
from range_filter import signals as rf_signals, range_filter as rf_values

OUT = os.path.expanduser("~/workspace/gold-station")
TZ = "Asia/Damascus"
_TZD = ZoneInfo(TZ)
KEY = open(os.path.expanduser("~/.config/goldstation/twelvedata_key")).read().strip()
STATE = os.path.join(OUT, "rangefilter_state.json")
MIN_RISK = 0.5  # $ — فلتر ضجيج


def td_live(interval, outputsize):
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}"
           f"&outputsize={outputsize}&order=ASC&timezone={TZ}&apikey={KEY}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "values" not in data:
        raise RuntimeError(str(data)[:200])
    return [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
             "l": float(v["low"]), "c": float(v["close"])} for v in data["values"]]


def main():
    require_market_open()
    candles = get_candles("15min", 400, live=lambda: td_live("15min", 400))
    if len(candles) < 250:
        print(json.dumps({"signals": [], "note": "بيانات غير كافية"}))
        return
    # إسقاط الشمعة المتشكلة — التقييم على المغلقة المؤكدة فقط (منع إعادة الرسم)
    now = datetime.now(_TZD)
    closed = [c for c in candles
              if datetime.strptime(c["t"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZD)
              <= now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)]
    if len(closed) < 250:
        closed = candles[:-1]
    closes = [c["c"] for c in closed]
    filt, fdir = rf_values(closes)
    sigs = rf_signals(closes)

    out_sigs = []
    if sigs:
        idx, side = sigs[-1]
        # الإشارة تُعتمد فقط إذا تشكلت على آخر شمعة مغلقة
        if idx == len(closed) - 1:
            c = closed[idx]
            entry = round(c["c"], 2)
            f = filt[idx]
            is_long = side == "long"
            risk = (entry - f) if is_long else (f - entry)
            if risk >= MIN_RISK and ((is_long and f < entry) or (not is_long and f > entry)):
                risk = round(risk, 2)
                s = 1 if is_long else -1
                sig = {
                    "strategy": "Range Filter",
                    "dir": "شراء" if is_long else "بيع",
                    "entry": entry,
                    "sl": round(f, 2),
                    "tp1": round(entry + s * risk, 2),
                    "tp2": round(entry + s * 2 * risk, 2),
                    "tp3": round(entry + s * 3 * risk, 2),
                    "rr": 3.0,
                    "key": f"RF|{c['t']}|{side}",
                    "t": c["t"],
                    "reason": (f"انعكاس Range Filter على 15m: الفلتر تحوّل {'صاعداً' if is_long else 'هابطاً'} "
                               f"وأغلقت الشمعة {'فوق' if is_long else 'تحت'} الخط {f:.2f} — "
                               f"الدخول {entry} والوقف عند خط الفلتر {f:.2f}"),
                    "assumptions": ("وقف=خط الفلتر، أهداف 1R/2R/3R حسب إدارة المخاطر المعتمدة — "
                                    "باكتست 15m أظهر أفضلية هامشية فقط (نُشر بطلب علاء)"),
                }
                out_sigs.append(sig)

    # حارس الحداثة (قرار علاء 2026-10-23): إسقاط إشارة تجاوز السعر الحي
    # هدفها الأول أو وقفها أو ابتعد عن دخولها أكثر من مخاطرة واحدة
    from freshness import filter_fresh
    out_sigs, dropped_stale = filter_fresh(out_sigs, mode="market")

    # ركن بقرار علاء 2026-10-24 (حزمة الركن): الإشارات تُسجَّل بسجل الظل
    # للقياس فقط — لا دفتر ولا تنبيه ولا مرآة. الصفقات المفتوحة سابقاً
    # (مثل #235) تُدار عادياً حتى إغلاقها.
    parked_shadow = []
    if out_sigs:
        try:
            with open(os.path.join(OUT, "shadow_signals.jsonl"), "a") as _f:
                for _s in out_sigs:
                    _f.write(json.dumps(
                        {"ts": datetime.now(_TZD).strftime("%Y-%m-%d %H:%M:%S"),
                         "reason": "parked", "strategy": _s["strategy"],
                         "dir": _s["dir"], "entry": _s["entry"], "sl": _s["sl"],
                         "tp1": _s.get("tp1"), "tp2": _s.get("tp2"),
                         "tp3": _s.get("tp3"),
                         "risk_usd": round(abs(_s["entry"] - _s["sl"]), 2)},
                        ensure_ascii=False) + "\n")
                    parked_shadow.append(_s["key"])
        except Exception:
            pass
        out_sigs = []

    with open(os.path.join(OUT, "gold_rangefilter.json"), "w") as fo:
        json.dump({"signals": out_sigs,
                   "parked_shadow": parked_shadow,
                   "dropped_stale": dropped_stale,
                   "at": datetime.now(_TZD).strftime("%Y-%m-%d %H:%M:%S")},
                  fo, ensure_ascii=False, indent=1)

    # رسم
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        data = closed[-120:]
        fc = filt[-120:]
        xs = list(range(len(data)))
        o = [c["o"] for c in data]; h = [c["h"] for c in data]
        l = [c["l"] for c in data]; cl = [c["c"] for c in data]
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
        for i in range(len(data)):
            col = "#26a69a" if cl[i] >= o[i] else "#ef5350"
            ax.plot([xs[i], xs[i]], [l[i], h[i]], color=col, linewidth=0.9)
            ax.plot([xs[i], xs[i]], sorted([o[i], cl[i]]), color=col, linewidth=2.4)
        ax.plot(xs, fc, color="#e3b341", linewidth=1.6, label="Range Filter")
        for sg in out_sigs:
            ax.axhline(sg["entry"], color="#58a6ff", linewidth=1.4)
            ax.axhline(sg["sl"], color="#ef5350", linewidth=1.2, linestyle=":")
            for tp, cc in (("tp1", "#26a69a"), ("tp2", "#26a69a"), ("tp3", "#26a69a")):
                ax.axhline(sg[tp], color=cc, linewidth=1.0, linestyle="--", alpha=0.8)
            ax.text(len(data) - 1, sg["entry"],
                    f" Range Filter {sg['dir']}: {sg['entry']} / وقف {sg['sl']}",
                    color="#58a6ff", fontsize=9, weight="bold", va="bottom", ha="right")
        ax.set_title(f"XAUUSD 15m · Range Filter | "
                     f"{'إشارة ' + out_sigs[0]['dir'] if out_sigs else 'لا إشارات جديدة'}",
                     color="white", fontsize=11, weight="bold")
        ax.tick_params(colors="#8b949e", labelsize=8)
        for sp in ax.spines.values():
            sp.set_color("#30363d")
        plt.tight_layout()
        plt.savefig(os.path.join(OUT, "gold_rangefilter.png"), dpi=130, facecolor="#0d1117")
        plt.close()
    except Exception as e:
        print(f"رسم: {e}", file=sys.stderr)

    print(json.dumps({"signals": out_sigs}, ensure_ascii=False)[:1500])
    print("RANGEFILTER DONE")


if __name__ == "__main__":
    main()
