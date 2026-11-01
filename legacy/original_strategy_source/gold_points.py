#!/usr/bin/env python3
"""استراتيجية النقاط — XAUUSD 1m — كسر مستويات علاء اليومية.

القواعد (بطلب علاء 2026-10-19 — قاعدة ثابتة):
- المستويات من gold_points_levels.json: خضراء=شراء، حمراء=بيع، زرقاء=محاور مضاربة.
- الدخول: إغلاق شمعة دقيقة واحدة beyond الرقم بـ ≥0.50$ باتجاهه.
  (بديل أمين لشرط "ثبات 5 ثواني" — لا ترصده الشموع؛ إغلاق الدقيقة تأكيد أقوى فعلياً)
- الوقف: 1.00$ خلف الرقم مباشرة.
- التعادل: عند ‎+1R (النظام المبسط — قرار علاء 2026-10-30؛ كان +20 نقطة) — عبر be_trigger_r في الدفتر.
- الأهداف: TP1=100 نقطة (1R)، TP2=250 نقطة (2.5R)، TP3=runner لأقرب محور أزرق (أو +400 نقطة).
- تكرار المحاولة: حتى 5 محاولات لكل رقم يومياً عند تحقق الشرط من جديد.
- فلتر الاتجاه/السيولة: H1 فوق/تحت EMA50 + شمعة الكسر موسعة (≥1.2× متوسط المدى).
- قوة الصفقة: /5 بعد التفعيل (زخم، أول محاولة، جلسة لندن/نيويورك، بُعد عن المستوى المعاكس، إغلاق مقنع).

المستويات تُحدَّث يومياً من لقطات علاء — السكربت يقرأ أحدث ملف مستويات.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from market_hours import require_market_open
from candle_db import get_candles

OUT = os.path.expanduser("~/workspace/gold-station")
TZ = "Asia/Damascus"
_TZD = ZoneInfo(TZ)
KEY = open(os.path.expanduser("~/.config/goldstation/twelvedata_key")).read().strip()
LEVELS = os.path.join(OUT, "gold_points_levels.json")
STATE = os.path.join(OUT, "gold_points_state.json")

BREAK_USD = 0.50      # كسر الرقم بنص دولار
SL_USD = 1.00         # الوقف 1$ خلف الرقم
BE_R = 1.0            # التعادل عند ‎+1R (النظام المبسط 2026-10-30 — كان 0.20)
TP1_USD = 1.00        # 100 نقطة
TP2_USD = 2.50        # 250 نقطة
RUNNER_USD = 4.00     # سقف الـrunner إذا لا محور قريب
MAX_ATTEMPTS = 5      # محاولات لكل رقم يومياً
MOM_MULT = 1.2        # شمعة الكسر موسعة ≥1.2× المتوسط


def td_live(interval, outputsize):
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}"
           f"&outputsize={outputsize}&order=ASC&timezone={TZ}&apikey={KEY}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "values" not in data:
        raise RuntimeError(str(data)[:200])
    return [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
             "l": float(v["low"]), "c": float(v["close"])} for v in data["values"]]


def ema(vals, n):
    k = 2 / (n + 1)
    out = []
    e = vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def in_killzone(now):
    # لندن 10:00-13:00 / نيويورك 15:30-22:00 بتوقيت دمشق
    m = now.hour * 60 + now.minute
    return (600 <= m < 780) or (930 <= m < 1320)


def main():
    require_market_open()
    lv = json.load(open(LEVELS))
    day = lv.get("date", "")
    buys = sorted(lv.get("buy", []))
    sells = sorted(lv.get("sell", []))
    pivots = sorted(lv.get("blue_pivots", []))

    m1 = None
    try:
        # قراءة محلية فقط بلا بديل حي: المزامنة تحدّث كل 5 دقائق —
        # الجلب الحي من الماسح كان يصطدم بحد المعدل الدقيقي (429) مع باقي الكرونات
        m1 = get_candles("1min", 300)
    except RuntimeError:
        print(json.dumps({"signals": [], "note": "شمعة الدقيقة قديمة — بانتظار المزامنة"}))
        return
    h1 = get_candles("1h", 120, live=lambda: td_live("1h", 120))
    if len(m1) < 60 or len(h1) < 60:
        print(json.dumps({"signals": [], "note": "بيانات غير كافية"}))
        return

    now = datetime.now(_TZD)
    # الشموع المغلقة المؤكدة فقط (إسقاط المتشكلة)
    closed = [c for c in m1
              if datetime.strptime(c["t"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZD)
              <= now.replace(second=0, microsecond=0)]
    if len(closed) < 60:
        closed = m1[:-1]

    st = {"last_t": "", "attempts": {}, "alerted_keys": []}
    if os.path.exists(STATE):
        try:
            st.update(json.load(open(STATE)))
        except Exception:
            pass
    # تصفير المحاولات يومياً
    today = now.strftime("%Y-%m-%d")
    attempts = {k: v for k, v in st.get("attempts", {}).items() if k.startswith(today)}

    # H1: اتجاه عبر EMA50 على المغلقة
    h1_closed = [c for c in h1
                 if datetime.strptime(c["t"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZD)
                 <= now.replace(minute=0, second=0, microsecond=0)]
    h1c = [c["c"] for c in (h1_closed if len(h1_closed) >= 60 else h1[:-1])]
    e50 = ema(h1c, 50)
    h1_trend_up = h1c[-1] > e50[-1]

    # نافذة الفحص: الشموع المغلقة بعد آخر معالجة (بحد أقصى 10 شموع)
    last_t = st.get("last_t", "")
    window = [c for c in closed if c["t"] > last_t][-10:] if last_t else closed[-3:]
    if not window:
        # إصلاح 2026-10-20 (بموافقة علاء): لا شموع أجدد من آخر معالجة —
        # خروج فوري بصمت بدل إعادة معالجة آخر شمعة قديمة (كانت تولّد إشارات
        # وهمية وتستهلك عدّاد المحاولات). الحالة لا تُحدَّث هنا عمداً.
        print(json.dumps({"signals": [], "note": "لا شموع جديدة — بانتظار المزامنة"}))
        return
    i0 = next(i for i, c in enumerate(closed) if c["t"] == window[0]["t"])
    pairs = [(closed[i], closed[i - 1]) for i in range(max(1, i0), i0 + len(window))]

    avg_range = sum(c["h"] - c["l"] for c in closed[-21:-1]) / 20

    signals = []
    for c, pc in pairs:
        rng = c["h"] - c["l"]
        momentum = rng >= MOM_MULT * avg_range if avg_range > 0 else False
        for side, levels in (("buy", buys), ("sell", sells)):
            is_buy = side == "buy"
            # فلتر الاتجاه الصلب
            if is_buy != h1_trend_up:
                continue
            for L in levels:
                akey = f"{today}|{side}|{L}"
                if attempts.get(akey, 0) >= MAX_ATTEMPTS:
                    continue
                if is_buy:
                    crossed = pc["c"] < L + BREAK_USD <= c["c"]
                    entry, sl = round(c["c"], 2), round(L - SL_USD, 2)
                    s = 1
                else:
                    crossed = pc["c"] > L - BREAK_USD >= c["c"]
                    entry, sl = round(c["c"], 2), round(L + SL_USD, 2)
                    s = -1
                if not crossed:
                    continue
                # قوة الصفقة /5
                strength = 0
                reasons_s = []
                if momentum:
                    strength += 1
                    reasons_s.append("زخم")
                if attempts.get(akey, 0) == 0:
                    strength += 1
                    reasons_s.append("أول محاولة")
                if in_killzone(now):
                    strength += 1
                    reasons_s.append("جلسة نشطة")
                opp = sells if is_buy else buys
                if not opp or min(abs(entry - o) for o in opp) >= 3.0:
                    strength += 1
                    reasons_s.append("بعيد عن المعاكس")
                # إغلاق مقنع: في الربع الأقوى من مدى الشمعة
                q = (c["c"] - c["l"]) / rng if rng > 0 else 0.5
                if (is_buy and q >= 0.75) or (not is_buy and q <= 0.25):
                    strength += 1
                    reasons_s.append("إغلاق مقنع")

                tp1 = round(entry + s * TP1_USD, 2)
                tp2 = round(entry + s * TP2_USD, 2)
                # TP3 = أقرب محور أزرق beyond TP2 باتجاه الصفقة وإلا +400 نقطة
                cands = [p for p in pivots if (p > tp2 if is_buy else p < tp2)]
                tp3 = round(min(cands) if is_buy and cands else
                            (max(cands) if not is_buy and cands else entry + s * RUNNER_USD), 2)
                n_try = attempts.get(akey, 0) + 1
                attempts[akey] = n_try
                key = f"POINTS|{L}|{n_try}|{c['t']}"
                signals.append({
                    "strategy": "النقاط",
                    "dir": "شراء" if is_buy else "بيع",
                    "entry": entry, "sl": sl,
                    "tp1": tp1, "tp2": tp2, "tp3": tp3,
                    "rr": round(abs(tp2 - entry) / abs(entry - sl), 2) if entry != sl else 0,
                    "be_trigger_r": BE_R,
                    "level": L, "attempt": n_try, "strength": strength,
                    "strength_reasons": reasons_s,
                    "is_runner_tp3": not cands,
                    "key": key, "t": c["t"],
                    "reason": (f"كسر الرقم {L} بنص دولار وإغلاق شمعة دقيقة "
                               f"{'فوقه' if is_buy else 'تحته'} عند {entry} — "
                               f"اتجاه H1 {'صاعد' if h1_trend_up else 'هابط'} متوافق"
                               + (f" — {', '.join(reasons_s)}" if reasons_s else "")),
                })

    st["last_t"] = closed[-1]["t"]
    st["attempts"] = attempts
    json.dump(st, open(STATE, "w"), ensure_ascii=False)
    # شارت: آخر 3 ساعات دقيقة واحدة + المستويات
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        xs = list(range(len(closed[-180:])))
        ax.plot(xs, [c["c"] for c in closed[-180:]], color="white", lw=1)
        for L in buys:
            ax.axhline(L, color="green", ls="--", lw=0.8, alpha=0.7)
        for L in sells:
            ax.axhline(L, color="red", ls="--", lw=0.8, alpha=0.7)
        for L in pivots:
            ax.axhline(L, color="blue", ls=":", lw=0.8, alpha=0.5)
        for sg in signals:
            ax.scatter([xs[-1]], [sg["entry"]],
                       color="green" if sg["dir"] == "شراء" else "red", s=80, zorder=5)
        ax.set_facecolor("black")
        fig.patch.set_facecolor("black")
        ax.tick_params(colors="gray", labelsize=7)
        for sp in ax.spines.values():
            sp.set_color("#333")
        plt.tight_layout()
        plt.savefig(os.path.join(OUT, "gold_points.png"), dpi=90)
        plt.close()
    except Exception as e:
        print(f"chart skipped: {e}")
    json.dump({"time": now.strftime("%Y-%m-%d %H:%M:%S"),
               "price": closed[-1]["c"], "levels_date": day,
               "h1_trend": "صاعد" if h1_trend_up else "هابط",
               "signals": signals},
              open(os.path.join(OUT, "gold_points.json"), "w"), ensure_ascii=False)
    print(json.dumps({"signals": len(signals), "price": closed[-1]["c"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
