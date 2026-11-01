"""
Market Data Access Layer — Adaptive V2 (Shadow)

الغرض: قراءة Point-in-Time للشموع من قاعدة النظام الحي كما كانت
متاحة فعلاً عند أي لحظة T، مع منع Look-Ahead Bias بصورة صارمة.

قواعد صارمة:
- اتصال SQLite بصلاحية قراءة فقط (mode=ro) — الكتابة مستحيلة فيزيائياً.
- لا نداءات شبكة/API إطلاقاً. لا استيراد من أي ماسح حي.
- الشمعة تُعتبر «مغلقة» عند T فقط إذا كان وقت إغلاقها
  (ts + مدة الفريم) أصغر أو يساوي T.
- الشمعة الجارية التشكّل تُطلب صراحةً عبر دالة منفصلة ولا تختلط
  بالمغلقة أبداً.

كل الأوقات نصوص "YYYY-MM-DD HH:MM:SS" بنفس صيغة التخزين في القاعدة
(توقيت دمشق كما خزّنتها المزامنة).
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "candles.db"
SYMBOL = "XAUUSD"

INTERVAL_MINUTES = {
    "1min": 1,
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "1h": 60,
    "4h": 240,
    "1day": 1440,
}

# ترتيب تفضيل المصدر: cTrader أولاً (الأحدث والأدق بنيوياً)، ثم TwelveData.
SOURCE_PREFERENCE = ("ctrader", "twelvedata", "eodhd")

_FMT = "%Y-%m-%d %H:%M:%S"


def _parse(ts):
    return datetime.strptime(ts, _FMT)


def _connect():
    # mode=ro: أي محاولة كتابة عبر هذا الاتصال ترفضها SQLite نفسها.
    uri = f"file:{DB_PATH}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _fetch(con, interval, source, where, params, limit):
    sql = (
        "SELECT ts, o, h, l, c FROM candles "
        "WHERE symbol=? AND interval=? AND source=? AND " + where +
        " ORDER BY ts DESC LIMIT ?"
    )
    rows = con.execute(sql, (SYMBOL, interval, source, *params, limit)).fetchall()
    rows.reverse()
    return [
        {"ts": ts, "o": o, "h": h, "l": l, "c": c, "source": source,
         "interval": interval}
        for ts, o, h, l, c in rows
    ]


def closed_candles_asof(interval, as_of, limit=500, source=None):
    """
    الشموع المغلقة فقط كما كانت متاحة عند اللحظة as_of.

    شمعة بوقت بداية ts ومدة الفريم D تُعاد فقط إذا ts + D <= as_of.
    النتيجة مرتبة تصاعدياً بالزمن. as_of نص "YYYY-MM-DD HH:MM:SS".
    """
    if interval not in INTERVAL_MINUTES:
        raise ValueError(f"unknown interval: {interval}")
    dur = timedelta(minutes=INTERVAL_MINUTES[interval])
    t = _parse(as_of)
    # آخر بداية شمعة يمكن أن تكون مغلقة عند as_of
    last_start = (t - dur).strftime(_FMT)
    sources = (source,) if source else SOURCE_PREFERENCE
    con = _connect()
    try:
        for src in sources:
            rows = _fetch(con, interval, src, "ts<=?", (last_start,), limit)
            if rows:
                return rows
        return []
    finally:
        con.close()


def forming_candle(interval, as_of, source=None):
    """
    الشمعة الجارية التشكّل عند as_of (بدايتها <= as_of وإغلاقها > as_of)،
    أو None. تُستخدم للمراقبة فقط — لا تُعامل كتأكيد مغلق أبداً.
    """
    if interval not in INTERVAL_MINUTES:
        raise ValueError(f"unknown interval: {interval}")
    dur = timedelta(minutes=INTERVAL_MINUTES[interval])
    t = _parse(as_of)
    earliest_start = (t - dur).strftime(_FMT)  # حصرياً بعد هذا الحد
    sources = (source,) if source else SOURCE_PREFERENCE
    con = _connect()
    try:
        for src in sources:
            rows = _fetch(con, interval, src, "ts>? AND ts<=?",
                          (earliest_start, as_of), 1)
            if rows:
                c = rows[-1]
                c = dict(c)
                c["forming"] = True
                return c
        return None
    finally:
        con.close()


def latest_closed(interval, as_of, source=None):
    """آخر شمعة مغلقة عند as_of أو None."""
    rows = closed_candles_asof(interval, as_of, limit=1, source=source)
    return rows[-1] if rows else None
