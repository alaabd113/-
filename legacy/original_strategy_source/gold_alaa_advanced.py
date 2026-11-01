#!/usr/bin/env python3
"""ماسح استراتيجية «Alaa متطورة» — XAUUSD — تجربة التوافق GOLD_CONFLUENCE_EXPERIMENT_1.0.0.

نُشرت حية بطلب علاء 2026-10-21 (إشارات + دفتر + تعلم) رغم أن المواصفة الأصلية
كانت ورقية فقط. المنطق المنفّذ هو النسخة الكاملة C_TRIGGER:
  تصويت متوسطات/مؤشرات على M5 + درجة توافق ستة فريمات (B) + بوابات C:
  صوتان نشطان بكل مجموعة، CHOP<=55، فلتر H1/EMA200، ومحفّز تراجع M1 نحو EMA20.
درجات النسختين A وB تُحسب وتُسجَّل بكل تشغيل في alaa_advanced_decisions.csv
(سجل قرارات للمقارنة والتعلم) لكنهما لا تولّدان إشارات.

البيانات: قاعدة الشموع المحلية فقط عبر candle_db.get_candles (cTrader أولاً) —
صفر استهلاك TwelveData. الشموع المغلقة فقط (منع النظر للمستقبل).

انحرافات معلنة عن المواصفة (قيود المحرك الحي):
  - إدارة الدفتر المعتمدة: أثلاث عند 1R/1.8R/2.5R وتعادل بعد TP1.
    نسب المواصفة 40/35/25 والتريلينغ بعد TP2 وحدّ العمر 120 دقيقة غير مطبقة حياً.
  - الدخول = إغلاق آخر شمعة M1 مغلقة (المواصفة: افتتاح M1 التالية — فرق ثوانٍ بوضع الاستطلاع).
  - السبريد غير مخزّن بالقاعدة: حدّ الوقف الأدنى = 0.8*ATR_M5 فقط (حُذف مكوّن 3×السبريد).

سجل التعديلات:
  - 2026-10-21 ~03:00 (بقرار علاء — نسخة مخففة 1.1): تخفيف محفّز M1 فقط —
    نافذة التراجع 3←6 شموع، نسبة الجسم 0.40←0.30، موقع الإغلاق 0.70←0.60،
    حدّ الامتداد 1.0←1.25 ATR، وفحص آخر 3 شموع M1 مغلقة كشمعة إشارة محتملة.
    بقية البوابات (درجة B والأصوات وCHOP وH1) بلا تغيير. الفحص كل دقيقة.
    مراجعة النتائج 2026-10-22 لقرار إعادة التشديد أو الإبقاء.
    النسخة الصارمة محفوظة: gold_alaa_advanced.py.bak-20261021-strict
"""
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_hours import require_market_open
from candle_db import get_candles

OUT = os.path.expanduser("~/workspace/gold-station")
TZ = "Asia/Damascus"
_TZD = ZoneInfo(TZ)
STRATEGY = "Alaa متطورة"
DECISIONS_CSV = os.path.join(OUT, "alaa_advanced_decisions.csv")
LEDGER = os.path.join(OUT, "gold_ledger.json")

TFS = ["1min", "5min", "15min", "1h", "4h", "1day"]
DUR = {"1min": 60, "5min": 300, "15min": 900, "1h": 3600, "4h": 14400, "1day": 86400}
NEED = {"1min": 700, "5min": 700, "15min": 600, "1h": 600, "4h": 600, "1day": 600}
WARMUP = 420

EPS_ATR = 0.05
SCORE_THRESHOLD = 75
SCORE_MARGIN = 15
SUMMARY_THRESHOLD = 60
SUMMARY_MARGIN = 10
CHOP_MAX = 55.0
MIN_ACTIVE_VOTES = 2
# النسخة المخففة 1.1 (2026-10-21 بقرار علاء) — محفّز M1 فقط
PB_LOOKBACK = 6      # شموع M1 السابقة لفحص لمس نطاق EMA20 (كانت 3)
BODY_MIN = 0.30      # نسبة جسم شمعة التأكيد (كانت 0.40)
LOC_MIN = 0.60       # موقع إغلاق شمعة التأكيد (كان 0.70)
EXT_MAX = 1.25       # أقصى بُعد عن EMA20 بوحدة ATR (كان 1.0)
TRIGGER_SCAN = 3     # عدد آخر شموع M1 مغلقة تُفحص كشمعة إشارة محتملة
CONFIG_TAG = "1.1-relaxed-20261021"


# ---------- مؤشرات (شموع مغلقة فقط) ----------

def sma_series(vals, n):
    out = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema_series(vals, n):
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    out[n - 1] = e
    for i in range(n, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi_series(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains, losses = [], []
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = sum(gains) / n, sum(losses) / n

    def _rsi(ag_, al_):
        if ag_ == 0 and al_ == 0:
            return 50.0
        if al_ == 0:
            return 100.0
        if ag_ == 0:
            return 0.0
        rs = ag_ / al_
        return 100.0 - 100.0 / (1.0 + rs)

    out[n] = _rsi(ag, al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = _rsi(ag, al)
    return out


def macd_hist_series(closes):
    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)
    macd = [None] * len(closes)
    for i in range(len(closes)):
        if e12[i] is not None and e26[i] is not None:
            macd[i] = e12[i] - e26[i]
    valid = [i for i, v in enumerate(macd) if v is not None]
    hist = [None] * len(closes)
    if len(valid) < 9:
        return hist
    first = valid[0]
    seg = [macd[i] for i in valid]
    sig = ema_series(seg, 9)
    for j, i in enumerate(valid):
        if sig[j] is not None:
            hist[i] = macd[i] - sig[j]
    return hist


def atr_series(bars, n=14):
    out = [None] * len(bars)
    trs = [None] * len(bars)
    if len(bars) <= n:
        return out, trs
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    a = sum(trs[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(bars)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out, trs


def chop_last(bars, trs, n=14):
    i = len(bars) - 1
    if i < n or trs is None:
        return None
    seg_tr = [trs[j] for j in range(i - n + 1, i + 1) if trs[j] is not None]
    if len(seg_tr) < n:
        return None
    hh = max(b["h"] for b in bars[i - n + 1:i + 1])
    ll = min(b["l"] for b in bars[i - n + 1:i + 1])
    if hh - ll <= 0:
        return None
    return 100.0 * math.log10(sum(seg_tr) / (hh - ll)) / math.log10(n)


# ---------- تصويت ودرجات (مطابق لقسمي 6 و7 بالمواصفة) ----------

def group_score(votes, side):
    active = sum(1 for v in votes if v != 0)
    if active == 0:
        return 25
    agreeing = sum(1 for v in votes if v == side)
    return math.floor(50 * agreeing / active)


def direction(scores, threshold, margin):
    buy, sell = scores[1], scores[-1]
    if buy >= threshold and buy - sell >= margin:
        return 1
    if sell >= threshold and sell - buy >= margin:
        return -1
    return 0


def frame_votes(bars):
    """يُرجع (ma_votes, osc_votes, diag) أو None إذا نقص مؤشر."""
    closes = [b["c"] for b in bars]
    sma20 = sma_series(closes, 20)
    sma50 = sma_series(closes, 50)
    ema200 = ema_series(closes, 200)
    rsi = rsi_series(closes, 14)
    hist = macd_hist_series(closes)
    atr, _trs = atr_series(bars, 14)
    i = len(bars) - 1
    vals = [sma20[i], sma50[i], ema200[i], rsi[i], hist[i], atr[i]]
    if any(v is None for v in vals):
        return None
    eps = EPS_ATR * atr[i]
    close = closes[i]
    ma_votes = []
    for ma in (sma20[i], sma50[i], ema200[i]):
        ma_votes.append(1 if close > ma + eps else (-1 if close < ma - eps else 0))
    mom = close - closes[i - 10] if i >= 10 else 0.0
    osc_votes = [
        1 if rsi[i] >= 55 else (-1 if rsi[i] <= 45 else 0),
        1 if hist[i] > 0 else (-1 if hist[i] < 0 else 0),
        1 if mom > eps else (-1 if mom < -eps else 0),
    ]
    diag = {"close": close, "atr": atr[i], "rsi": rsi[i], "hist": hist[i],
            "ema200": ema200[i], "sma20": sma20[i], "sma50": sma50[i]}
    return ma_votes, osc_votes, diag


def closed_only(bars, tf, now):
    dur = timedelta(seconds=DUR[tf])
    out = []
    for b in bars:
        ts = datetime.strptime(b["t"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZD)
        if ts + dur <= now:
            out.append(b)
    return out


def open_position_exists():
    try:
        with open(LEDGER) as f:
            d = json.load(f)
        return any(t.get("strategy") == STRATEGY and t.get("status") == "open"
                   for t in d.get("trades", []))
    except Exception:
        return False


def append_decision(row):
    new = not os.path.exists(DECISIONS_CSV)
    with open(DECISIONS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    require_market_open()
    now = datetime.now(_TZD)
    run_ts = now.strftime("%Y-%m-%d %H:%M:%S")

    data, diag_tf = {}, {}
    insufficient = None
    for tf in TFS:
        try:
            bars = get_candles(tf, NEED[tf])
        except Exception as e:
            insufficient = f"لا بيانات {tf}: {e}"
            break
        bars = closed_only(bars, tf, now)
        if len(bars) < WARMUP:
            insufficient = f"تهيئة غير كافية {tf}: {len(bars)} < {WARMUP}"
            break
        data[tf] = bars

    result = {"signals": [], "at": run_ts, "strategy": STRATEGY, "config": CONFIG_TAG}
    if insufficient:
        result["note"] = insufficient
        _write_json(result)
        print(json.dumps({"signals": [], "note": insufficient}, ensure_ascii=False))
        return

    # أصوات ودرجات كل فريم
    frames = {}
    for tf in TFS:
        fv = frame_votes(data[tf])
        if fv is None:
            insufficient = f"مؤشر ناقص على {tf}"
            break
        ma_v, osc_v, dg = fv
        frames[tf] = {
            "ma": ma_v, "osc": osc_v, "diag": dg,
            "local": {s: group_score(ma_v, s) + group_score(osc_v, s) for s in (1, -1)},
        }
    if insufficient:
        result["note"] = insufficient
        _write_json(result)
        print(json.dumps({"signals": [], "note": insufficient}, ensure_ascii=False))
        return

    base = frames["5min"]["local"]
    side_a = direction(base, SCORE_THRESHOLD, SCORE_MARGIN)
    summaries = {tf: direction(frames[tf]["local"], SUMMARY_THRESHOLD, SUMMARY_MARGIN)
                 for tf in TFS}
    score_b = {}
    aligned = {}
    for s in (1, -1):
        aligned[s] = sum(1 for tf in TFS if summaries[tf] == s)
        score_b[s] = min(100, max(10, math.floor(base[s] / 2) + math.floor(50 * aligned[s] / 6)))
    side_b = direction(score_b, SCORE_THRESHOLD, SCORE_MARGIN)

    # CHOP على M5
    _a5, trs5 = atr_series(data["5min"], 14)
    chop5 = chop_last(data["5min"], trs5, 14)

    # بوابات C
    side_c, reject = 0, ""
    trig_diag = ""
    if side_b == 0:
        reject = "SCORE_REJECT"
    else:
        s = side_b
        ma_act = sum(1 for v in frames["5min"]["ma"] if v != 0)
        osc_act = sum(1 for v in frames["5min"]["osc"] if v != 0)
        h1_close = frames["1h"]["diag"]["close"]
        h1_ema = frames["1h"]["diag"]["ema200"]
        if min(ma_act, osc_act) < MIN_ACTIVE_VOTES:
            reject = "LOW_VOTE_COVERAGE"
        elif chop5 is None or chop5 > CHOP_MAX:
            reject = "CHOP_FILTER"
        elif (s == 1 and not h1_close > h1_ema) or (s == -1 and not h1_close < h1_ema):
            reject = "H1_BIAS"
        else:
            ok, trig_diag = _m1_trigger(data["1min"], s)
            if ok:
                side_c = s
            else:
                reject = "WAIT_TRIGGER"

    row = {
        "run_ts": run_ts,
        "m5_bar": data["5min"][-1]["t"],
        "local_buy": base[1], "local_sell": base[-1], "side_a": side_a,
        "aligned_buy": aligned[1], "aligned_sell": aligned[-1],
        "scoreb_buy": score_b[1], "scoreb_sell": score_b[-1], "side_b": side_b,
        "chop_m5": round(chop5, 2) if chop5 is not None else "",
        "side_c": side_c, "reject": reject if side_c == 0 else "",
        "trigger": trig_diag,
    }
    append_decision(row)
    result["diag"] = row

    signals = []
    if side_c != 0:
        s = side_c
        sig = _build_signal(data, frames, s, score_b, aligned, chop5, trig_diag)
        if sig is None:
            row["reject"] = "STOP_INVALID"
        elif open_position_exists():
            row["reject"] = "POSITION_EXISTS"
        else:
            signals.append(sig)
    result["signals"] = signals
    _write_json(result)
    _chart(data["5min"], frames["5min"], signals)
    print(json.dumps({"signals": signals, "diag": row}, ensure_ascii=False)[:1800])
    print("ALAAADV DONE")


def _trigger_at(bars, ema20, atr, i, s):
    if i < PB_LOOKBACK + 1 or ema20[i] is None or atr[i] is None:
        return False, "بيانات M1 غير كافية للمحفّز"
    # تراجع: إحدى الشموع السابقة ضمن النافذة لامست نطاق EMA20
    touched = False
    for j in range(i - PB_LOOKBACK, i):
        if ema20[j] is None or atr[j] is None:
            continue
        if bars[j]["l"] <= ema20[j] + 0.15 * atr[j] and bars[j]["h"] >= ema20[j] - 0.15 * atr[j]:
            touched = True
    if not touched:
        return False, f"لا تراجع نحو EMA20 بآخر {PB_LOOKBACK} شموع M1"
    b, prev = bars[i], bars[i - 1]
    rng = b["h"] - b["l"]
    if rng <= 0:
        return False, "شمعة بلا نطاق"
    body = abs(b["c"] - b["o"]) / rng
    ext = abs(b["c"] - ema20[i])
    if s == 1:
        loc = (b["c"] - b["l"]) / rng
        ok = (b["c"] > ema20[i] and b["c"] > prev["h"] and b["c"] > b["o"]
              and body >= BODY_MIN and loc >= LOC_MIN and ext <= EXT_MAX * atr[i])
        return ok, (f"إغلاق M1 {b['c']:.2f} فوق EMA20 {ema20[i]:.2f} وفوق قمة السابقة "
                    f"— جسم {body:.2f} وموقع إغلاق {loc:.2f}")
    loc = (b["h"] - b["c"]) / rng
    ok = (b["c"] < ema20[i] and b["c"] < prev["l"] and b["c"] < b["o"]
          and body >= BODY_MIN and loc >= LOC_MIN and ext <= EXT_MAX * atr[i])
    return ok, (f"إغلاق M1 {b['c']:.2f} تحت EMA20 {ema20[i]:.2f} وتحت قاع السابقة "
                f"— جسم {body:.2f} وموقع إغلاق {loc:.2f}")


def _m1_trigger(bars, s):
    closes = [b["c"] for b in bars]
    ema20 = ema_series(closes, 20)
    atr, _ = atr_series(bars, 14)
    last = len(bars) - 1
    diag = "لا محفّز"
    for i in range(last, max(last - TRIGGER_SCAN, 0), -1):
        ok, diag = _trigger_at(bars, ema20, atr, i, s)
        if ok:
            return True, diag
    return False, diag


def _build_signal(data, frames, s, score_b, aligned, chop5, trig_diag):
    m1 = data["1min"]
    atr_m5 = frames["5min"]["diag"]["atr"]
    entry = round(m1[-1]["c"], 2)
    last5 = m1[-5:]
    if s == 1:
        sl = min(b["l"] for b in last5) - 0.10 * atr_m5
        sl = min(sl, entry - 0.8 * atr_m5)
    else:
        sl = max(b["h"] for b in last5) + 0.10 * atr_m5
        sl = max(sl, entry + 0.8 * atr_m5)
    sl = round(sl, 2)
    d = abs(entry - sl)
    if d <= 0 or d > 2.0 * atr_m5:
        return None
    tp1 = round(entry + s * 1.0 * d, 2)
    tp2 = round(entry + s * 1.8 * d, 2)
    tp3 = round(entry + s * 2.5 * d, 2)
    m5_ts = data["5min"][-1]["t"]
    is_buy = s == 1
    reason = (f"توافق الفريمات: درجة B ‏{score_b[s]} من 100 (محلي M5 ‏{frames['5min']['local'][s]}) "
              f"وتوافق {aligned[s]} من 6 فريمات — CHOP على M5 ‏{chop5:.1f} (بلا تذبذب مانع)، "
              f"وإغلاق H1 {'فوق' if is_buy else 'تحت'} EMA200. {trig_diag}")
    return {
        "strategy": STRATEGY,
        "dir": "شراء" if is_buy else "بيع",
        "entry": entry, "sl": sl,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr": 2.5,
        "key": f"ALAAADV|{m5_ts}|{'buy' if is_buy else 'sell'}|{entry}",
        "t": m1[-1]["t"],
        "reason": reason,
        "note": ("Alaa متطورة — تجربة التوافق GOLD_CONFLUENCE (النسخة الكاملة C) "
                 "نُشرت حية بطلب علاء 2026-10-21؛ إدارة الدفتر: أثلاث وتعادل بعد TP1"),
        "assumptions": ("الوقف هيكلي من آخر 5 شموع M1 بهامش 0.10*ATR_M5 وحدّ أدنى 0.8*ATR_M5؛ "
                        "الأهداف 1R/1.8R/2.5R؛ الدخول عند إغلاق آخر M1 مغلقة"),
    }


def _write_json(result):
    with open(os.path.join(OUT, "gold_alaa_advanced.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)


def _chart(m5, frame5, signals):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        data = m5[-120:]
        closes = [b["c"] for b in m5]
        ema20_full = ema_series(closes, 20)
        ema20 = ema20_full[-120:]
        xs = list(range(len(data)))
        o = [b["o"] for b in data]; h = [b["h"] for b in data]
        l = [b["l"] for b in data]; cl = [b["c"] for b in data]
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
        for i in range(len(data)):
            col = "#26a69a" if cl[i] >= o[i] else "#ef5350"
            ax.plot([xs[i], xs[i]], [l[i], h[i]], color=col, linewidth=0.9)
            ax.plot([xs[i], xs[i]], sorted([o[i], cl[i]]), color=col, linewidth=2.4)
        ax.plot(xs, ema20, color="#e3b341", linewidth=1.4, label="EMA20 M5")
        for sg in signals:
            ax.axhline(sg["entry"], color="#58a6ff", linewidth=1.4)
            ax.axhline(sg["sl"], color="#ef5350", linewidth=1.2, linestyle=":")
            for tp in ("tp1", "tp2", "tp3"):
                ax.axhline(sg[tp], color="#26a69a", linewidth=1.0, linestyle="--", alpha=0.8)
            ax.text(len(data) - 1, sg["entry"],
                    f" Alaa متطورة {sg['dir']}: {sg['entry']} / وقف {sg['sl']}",
                    color="#58a6ff", fontsize=9, weight="bold", va="bottom", ha="right")
        ax.set_title(f"XAUUSD M5 · Alaa متطورة | "
                     f"{'إشارة ' + signals[0]['dir'] if signals else 'لا إشارات جديدة'}",
                     color="white", fontsize=11, weight="bold")
        ax.tick_params(colors="#8b949e", labelsize=8)
        for sp in ax.spines.values():
            sp.set_color("#30363d")
        plt.tight_layout()
        plt.savefig(os.path.join(OUT, "gold_alaa_advanced.png"), dpi=130, facecolor="#0d1117")
        plt.close()
    except Exception as e:
        print(f"رسم: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
