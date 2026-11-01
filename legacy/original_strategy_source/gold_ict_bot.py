#!/usr/bin/env python3
"""بوت تحليل الذهب باستراتيجية ICT — جاهز للاستضافة على BotKeep.

يعمل 24/7: كل SCAN_MINUTES دقيقة يحلل XAUUSD بنموذج الدخول عالي الاحتمالية
(سحب سيولة ← إزاحة ← MSS ← FVG ← إعادة اختبار، R:R ≥ 2)
ويرسل بطاقة الصفقة إلى تيليجرام عند تحقق الشروط فقط.

متغيرات البيئة (تُضبط كـ Secrets في لوحة BotKeep — لا تُكتب في الكود):
  TWELVEDATA_KEY     مفتاح TwelveData لبيانات الذهب (مطلوب)
  TELEGRAM_BOT_TOKEN توكن بوت التيليجرام المرسل (مطلوب)
  TELEGRAM_CHAT_ID   معرف المحادثة/القناة المستلمة (مطلوب)
  SCAN_MINUTES       الفاصل بين الفحوص بالدقائق (اختياري، الافتراضي 15)

التشغيل: python gold_ict_bot.py   (stdlib فقط — لا يحتاج pip)
"""
import json
import os
import time
import traceback
import urllib.parse
import urllib.request

SYMBOL = "XAU/USD"
TZ = "Asia/Damascus"
MIN_PEN = 1.0          # أقل اختراق يُعتبر سحب سيولة حقيقي ($)
DISP_MULT = 1.2        # عتبة الإزاحة: جسم الشمعة > 1.2 × ATR
MIN_RR = 2.0           # أقل R:R مقبول حسب الكورس


def td(key, interval, outputsize):
    url = (f"https://api.twelvedata.com/time_series?symbol={urllib.parse.quote(SYMBOL)}"
           f"&interval={interval}&outputsize={outputsize}&order=ASC"
           f"&timezone={TZ}&apikey={key}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "values" not in data:
        raise RuntimeError(f"TwelveData: {str(data)[:160]}")
    return [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
             "l": float(v["low"]), "c": float(v["close"])} for v in data["values"]]


def swings(candles, n=3):
    highs, lows = [], []
    for i in range(n, len(candles) - n):
        h, l = candles[i]["h"], candles[i]["l"]
        if all(h >= candles[j]["h"] for j in range(i - n, i + n + 1) if j != i):
            highs.append((i, h, candles[i]["t"]))
        if all(l <= candles[j]["l"] for j in range(i - n, i + n + 1) if j != i):
            lows.append((i, l, candles[i]["t"]))
    return highs, lows


def atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:period]) / period
    for x in trs[period:]:
        a = (a * (period - 1) + x) / period
    return a


def body(c):
    return abs(c["c"] - c["o"])


def bullish_fvg(c1, c2, c3):
    if c2["c"] <= c2["o"]:
        return None
    if c1["h"] <= c3["l"]:
        return (c3["l"], c1["h"])
    return None


def bearish_fvg(c1, c2, c3):
    if c2["c"] >= c2["o"]:
        return None
    if c1["l"] >= c3["h"]:
        return (c1["l"], c3["h"])
    return None


def analyze(key):
    h4 = td(key, "4h", 80)
    m15 = td(key, "15min", 220)
    a15 = atr(m15)
    price = m15[-1]["c"]
    now_t = m15[-1]["t"]

    h4h, h4l = swings(h4, 2)
    m15h, m15l = swings(m15, 4)

    deal_low = h4l[-1][1] if h4l else min(c["l"] for c in h4)
    deal_high = h4h[-1][1] if h4h else max(c["h"] for c in h4)
    if h4h and h4l and h4h[-1][0] < h4l[-1][0]:
        deal_high = max(c["h"] for c in m15[-96:])
    eq = (deal_high + deal_low) / 2
    in_premium = price > eq

    sweep = None
    for i in range(len(m15) - 40, len(m15)):
        c = m15[i]
        ph = [s for s in m15h if s[0] < i - 4]
        pl = [s for s in m15l if s[0] < i - 4]
        if ph and c["h"] > ph[-1][1] and c["c"] < ph[-1][1] and (c["h"] - ph[-1][1]) >= MIN_PEN:
            sweep = {"dir": "BSL", "level": ph[-1][1], "idx": i, "t": c["t"]}
        elif pl and c["l"] < pl[-1][1] and c["c"] > pl[-1][1] and (pl[-1][1] - c["l"]) >= MIN_PEN:
            sweep = {"dir": "SSL", "level": pl[-1][1], "idx": i, "t": c["t"]}

    displacement = None
    if sweep:
        si = sweep["idx"]
        bearish = sweep["dir"] == "BSL"
        for j in range(si + 1, min(si + 12, len(m15))):
            c = m15[j]
            if body(c) > DISP_MULT * a15:
                if bearish and c["c"] < c["o"]:
                    displacement = {"bearish": True, "idx": j, "t": c["t"],
                                    "extreme": max(m15[k]["h"] for k in range(si, j + 1))}
                    break
                if not bearish and c["c"] > c["o"]:
                    displacement = {"bearish": False, "idx": j, "t": c["t"],
                                    "extreme": min(m15[k]["l"] for k in range(si, j + 1))}
                    break

    mss = None
    if displacement:
        di = displacement["idx"]
        bearish = displacement["bearish"]
        for j in range(di + 1, len(m15)):
            c = m15[j]
            pl = [s for s in m15l if s[0] < j - 4]
            ph = [s for s in m15h if s[0] < j - 4]
            if bearish and pl and c["o"] > pl[-1][1] > c["c"]:
                mss = {"bearish": True, "level": pl[-1][1], "idx": j, "t": c["t"]}
                break
            if not bearish and ph and c["o"] < ph[-1][1] < c["c"]:
                mss = {"bearish": False, "level": ph[-1][1], "idx": j, "t": c["t"]}
                break

    fvgs = []
    for i in range(len(m15) - 60, len(m15) - 2):
        c1, c2, c3 = m15[i], m15[i + 1], m15[i + 2]
        z = bullish_fvg(c1, c2, c3)
        if z:
            filled = any(m15[k]["l"] < z[1] for k in range(i + 3, len(m15)))
            if not filled:
                fvgs.append({"bearish": False, "top": z[0], "bot": z[1], "idx": i + 1, "t": c2["t"]})
        z = bearish_fvg(c1, c2, c3)
        if z:
            filled = any(m15[k]["h"] > z[0] for k in range(i + 3, len(m15)))
            if not filled:
                fvgs.append({"bearish": True, "top": z[0], "bot": z[1], "idx": i + 1, "t": c2["t"]})

    setup = None
    if sweep and displacement and mss:
        bearish = mss["bearish"]
        cand = [f for f in fvgs if f["bearish"] == bearish and f["idx"] >= displacement["idx"]]
        # القاعدة الميكانيكية: بيع في العلاوة فقط / شراء في الخصم فقط
        cand = [f for f in cand if (bearish and f["bot"] > eq) or ((not bearish) and f["top"] < eq)]
        if cand:
            f = cand[-1]
            entry = (f["top"] + f["bot"]) / 2
            if bearish:
                sl = displacement["extreme"] + 0.25 * a15
                lows = [s[1] for s in m15l if s[0] < len(m15) - 4]
                tp = min(lows) if lows else deal_low
            else:
                sl = displacement["extreme"] - 0.25 * a15
                highs = [s[1] for s in m15h if s[0] < len(m15) - 4]
                tp = max(highs) if highs else deal_high
            risk = abs(entry - sl)
            rr = abs(tp - entry) / risk if risk > 0 else 0
            inside = f["bot"] <= price <= f["top"]
            if rr >= MIN_RR:
                setup = {
                    "key": f"{'sell' if bearish else 'buy'}|{f['t']}|{round(entry, 2)}",
                    "dir": "بيع" if bearish else "شراء",
                    "entry": round(entry, 2), "sl": round(sl, 2),
                    "tp": round(tp, 2), "rr": round(rr, 2),
                    "inside": inside,
                    "sweep_level": round(sweep["level"], 2),
                    "sweep_t": sweep["t"],
                    "zone": "العلاوة" if bearish else "الخصم",
                }

    return {
        "time": now_t, "price": round(price, 2),
        "zone": "علاوة Premium (البيع فقط)" if in_premium else "خصم Discount (الشراء فقط)",
        "setup": setup,
    }


def tg_send(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0"})
    urllib.request.urlopen(req, timeout=30).read()


def card(a):
    s = a["setup"]
    return (
        "🥇 <b>XAUUSD · صفقة ICT جديدة</b>\n"
        f"الاتجاه: <b>{s['dir']}</b>\n"
        f"الدخول: <b>{s['entry']}</b> | الوقف: <b>{s['sl']}</b> | الهدف: <b>{s['tp']}</b>\n"
        f"R:R = <b>{s['rr']}</b>\n"
        f"السبب: سحب سيولة عند {s['sweep_level']} ({s['sweep_t']})، إزاحة قوية، "
        f"كسر هيكل MSS، عودة لاختبار فجوة في {s['zone']}.\n"
        f"السعر وقت الإشارة: {a['price']}\n"
        "المخاطرة المقترحة: 0.25%-1% من الحساب.\n"
        "<i>للمراقبة والدراسة — ليست توصية مالية.</i>"
    )


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_key": None}


def main():
    td_key = os.environ.get("TWELVEDATA_KEY", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not td_key or not tg_token or not tg_chat:
        raise SystemExit("Missing env: TWELVEDATA_KEY / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    minutes = int(os.environ.get("SCAN_MINUTES", "15"))
    state_path = os.environ.get("STATE_FILE", "bot_state.json")

    print(f"[bot] ICT gold bot started — scan every {minutes} min", flush=True)
    while True:
        try:
            a = analyze(td_key)
            s = a["setup"]
            if s and s["inside"]:
                st = load_state(state_path)
                if st.get("last_key") != s["key"]:
                    tg_send(tg_token, tg_chat, card(a))
                    with open(state_path, "w") as f:
                        json.dump({"last_key": s["key"]}, f)
                    print(f"[bot] ALERT sent: {s['key']}", flush=True)
                else:
                    print(f"[bot] {a['time']} price={a['price']} setup already alerted", flush=True)
            else:
                print(f"[bot] {a['time']} price={a['price']} zone={a['zone']} no setup", flush=True)
        except Exception:
            traceback.print_exc()
        time.sleep(minutes * 60)


if __name__ == "__main__":
    main()
