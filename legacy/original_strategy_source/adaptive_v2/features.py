"""
Feature Snapshot — Adaptive V2 (Shadow), Step 3

لقطة خصائص رقمية لكل صفقة تُحسب كما كانت لحظة فتحها (as_of = ts_open)
من الشموع المغلقة فقط عبر market_data — بلا أي نظرة للمستقبل.

الخصائص كلها مشتقة من OHLC المخزّن (لا حجم ولا سبريد حقيقي متاح —
السبريد يُنمذج معلناً في المحاكي، لا يُدّعى هنا).
أي خاصية لا تكفي بياناتها تُسجَّل None — لا تُخمَّن أبداً.
"""

import math
from datetime import datetime

import market_data as md

FMT = "%Y-%m-%d %H:%M:%S"


def _ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    g = sum(gains[-period:]) / period
    l = sum(losses[-period:]) / period
    if l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + g / l)


def _session(hour):
    if hour < 9:
        return "asia"
    if hour < 14:
        return "london"
    if hour < 18:
        return "overlap"
    if hour < 23:
        return "newyork"
    return "late"


def snapshot(trade):
    """لقطة خصائص صفقة واحدة عند لحظة فتحها.

    trade: dict من الدفتر (id, strategy, dir, entry, sl, tp1..tp3, rr,
    ts_open, mgmt, note). dir قد تكون عربية (شراء/بيع) أو buy/sell.
    """
    ts_open = trade["ts_open"]
    entry = float(trade["entry"])
    sl = float(trade["sl"])
    risk = abs(entry - sl)
    d = str(trade.get("dir", ""))
    sign = 1.0 if d in ("buy", "شراء", "long") else -1.0
    t = datetime.strptime(ts_open, FMT)

    f = {
        "risk_usd": round(risk, 2),
        "rr_planned": trade.get("rr"),
        "mgmt": trade.get("mgmt") or "thirds",
        "is_limit": 1 if "LIMIT" in str(trade.get("note") or "") else 0,
        "hour": t.hour,
        "dow": t.weekday(),
        "session": _session(t.hour),
        "hour_sin": round(math.sin(2 * math.pi * t.hour / 24.0), 4),
        "hour_cos": round(math.cos(2 * math.pi * t.hour / 24.0), 4),
    }
    if risk <= 0:
        f["error"] = "non-positive risk"
        return f

    # --- M15: تقلب وزخم ومساحة للهدف ---
    m15 = md.closed_candles_asof("15min", ts_open, limit=160)
    if len(m15) >= 20:
        closes = [c["c"] for c in m15]
        atr15 = _atr(m15)
        f["atr15_usd"] = round(atr15, 2) if atr15 else None
        f["atr15_r"] = round(atr15 / risk, 3) if atr15 else None
        rsi = _rsi(closes)
        f["rsi15"] = round(rsi, 1) if rsi is not None else None
        if len(closes) >= 6:
            f["mom5_dir_r"] = round(sign * (closes[-1] - closes[-6]) / risk, 3)
        win = m15[-40:]
        sh = max(c["h"] for c in win)
        slw = min(c["l"] for c in win)
        if sign > 0:
            f["room_r"] = round((sh - entry) / risk, 3)
            f["against_r"] = round((entry - slw) / risk, 3)
        else:
            f["room_r"] = round((entry - slw) / risk, 3)
            f["against_r"] = round((sh - entry) / risk, 3)

    # --- H1 / H4: محاذاة الاتجاه مع EMA200 والتراص ---
    for tf, key in (("1h", "h1"), ("4h", "h4")):
        rows = md.closed_candles_asof(tf, ts_open, limit=260)
        if len(rows) >= 60:
            closes = [c["c"] for c in rows]
            atr = _atr(rows)
            e20, e50, e200 = _ema(closes, 20), _ema(closes, 50), _ema(closes, 200)
            last = closes[-1]
            if e200 is not None:
                f[f"trend_align_{key}"] = round(sign * (last - e200) / risk, 3)
            if e20 is not None and e50 is not None:
                stack = 1 if e20 > e50 else -1
                f[f"ema_stack_{key}"] = int(sign * stack)
            if atr:
                f[f"atr_{key}_usd"] = round(atr, 2)
    return f
