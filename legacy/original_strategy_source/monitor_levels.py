#!/usr/bin/env python3
"""مراقبة مستويات الذهب — تحليل GoldRider الأسبوعي لأسبوع الاثنين 2026-10-26 (استُلم السبت 2026-10-24).
يقارن السعر الحالي بالمستويات ويطبع EVENT: عند حدث جديد فقط، وإلا QUIET.
المفتاح يُقرأ من ~/.config/goldstation/twelvedata_key (لا يُكتب في الكود).
الحالة تُحفظ في ~/workspace/gold-station/monitor-state.json لمنع تكرار التنبيه.
"""
import json, os, urllib.request

KEY_PATH = os.path.expanduser("~/.config/goldstation/twelvedata_key")
STATE_PATH = os.path.expanduser("~/workspace/gold-station/monitor-state.json")

BUY_TRIGGER, BUY_EARLY = 4026.0, 4012.0
SELL_EARLY, SELL_TRIGGER = 3977.0, 3966.0
BUY_TARGETS = [4018, 4022, 4032, 4042, 4050, 4053, 4065, 4077, 4086, 4090, 4097, 4103, 4111, 4123, 4126, 4131, 4136, 4142]
SELL_TARGETS = [3970, 3958, 3950, 3946, 3933, 3927, 3921, 3916, 3906, 3902, 3896, 3886, 3874, 3870, 3863, 3858, 3848, 3843]

def td(path, params, key):
    url = ("https://api.twelvedata.com" + path + "?" +
           "&".join(f"{k}={v}" for k, v in params.items()) + f"&apikey={key}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())

def main():
    from market_hours import require_market_open
    require_market_open()  # السوق مغلق = خروج صامت بلا أي طلب API (بأمر علاء 2026-10-17)
    with open(KEY_PATH) as f:
        key = f.read().strip()
    q = td("/quote", {"symbol": "XAU/USD", "interval": "1day"}, key)
    price = float(q["close"])  # السعر الحالي من /quote — يغني عن نداء /price المنفصل
    day_high, day_low = float(q["high"]), float(q["low"])

    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"fired": [], "day_high": day_high, "day_low": day_low,
                 "buy_targets_hit": [], "sell_targets_hit": []}
    fired = set(state.get("fired", []))
    events = []

    def fire(key, msg):
        if key not in fired:
            fired.add(key)
            events.append(msg)

    # اقتراب (ضمن 3 دولار) — تنبيه مرة واحدة
    if price >= BUY_EARLY - 3 and price < BUY_EARLY:
        fire("approach_buy_early", f"الذهب يقترب من الشراء المبكر 4012 — السعر الآن {price:.1f}")
    if price <= SELL_EARLY + 3 and price > SELL_EARLY:
        fire("approach_sell_early", f"الذهب يقترب من البيع المبكر 3977 — السعر الآن {price:.1f}")

    # دخول المناطق
    if price >= BUY_EARLY:
        fire("enter_buy_early", f"الذهب دخل منطقة الشراء المبكر (فوق 4012) — السعر {price:.1f}. راقب تأكيد السلوك السعري قبل الدخول")
    if price <= SELL_EARLY:
        fire("enter_sell_early", f"الذهب دخل منطقة البيع المبكر (تحت 3977) — السعر {price:.1f}. راقب تأكيد السلوك السعري قبل الدخول")

    # تفعيل الزناد
    if price >= BUY_TRIGGER:
        fire("buy_trigger", f"تفعّل الشراء فوق 4026 — السعر {price:.1f}. الأهداف: 4032 ثم 4042 ثم 4050-4053...")
    if price <= SELL_TRIGGER:
        fire("sell_trigger", f"تفعّل البيع تحت 3966 — السعر {price:.1f}. الأهداف: 3958 ثم 3950-3946...")

    # أهداف بعد التفعيل
    if price >= BUY_TRIGGER:
        hit = state.get("buy_targets_hit", [])
        for t in BUY_TARGETS:
            if price >= t and t not in hit:
                hit.append(t)
                events.append(f"الذهب حقق هدف الشراء {t} — السعر {price:.1f}")
        state["buy_targets_hit"] = hit
    if price <= SELL_TRIGGER:
        hit = state.get("sell_targets_hit", [])
        for t in SELL_TARGETS:
            if price <= t and t not in hit:
                hit.append(t)
                events.append(f"الذهب حقق هدف البيع {t} — السعر {price:.1f}")
        state["sell_targets_hit"] = hit

    # امتداد قمة/قاع اليوم بأكثر من 5 دولار عن آخر حالة
    if day_high > state.get("day_high", day_high) + 5:
        events.append(f"قمة جديدة لليوم: {day_high:.1f} (السابق {state.get('day_high'):.1f}) — من فيد TwelveData")
        state["day_high"] = day_high
    if day_low < state.get("day_low", day_low) - 5:
        events.append(f"قاع جديد لليوم: {day_low:.1f} (السابق {state.get('day_low'):.1f}) — من فيد TwelveData")
        state["day_low"] = day_low

    state["fired"] = sorted(fired)
    state["last_price"] = price
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)

    if events:
        for e in events:
            print("EVENT:", e)
    else:
        print(f"QUIET: price={price:.1f} day_range={day_low:.1f}-{day_high:.1f}")

if __name__ == "__main__":
    main()
