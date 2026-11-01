#!/usr/bin/env python3
"""
lux_smc.py — Python port of LuxAlgo "Smart Money Concepts" (Pine v5) for our gold engine.

Faithful core logic ported from the original indicator:
  - leg()-based pivots (swing size=50, internal size=5, equal size=3)
  - BOS / CHoCH via close crossover of pivot levels (displayStructure)
  - Order Blocks stored on structure breaks, mitigated on High/Low breach
    (internal OBs = default ON in the original; swing OBs enabled here for analysis)
  - EQH / EQL with threshold 0.1 * ATR(200)
  - Fair Value Gaps (3-candle, auto-threshold = 2x running mean |delta%|) — enabled here
  - Trailing extremes + Premium / Equilibrium / Discount zones
Data source: candles.db (cTrader preferred). No external API calls.
Usage: lux_smc.py [interval] [--chart PATH] [--chart-bars N]
"""
import sys, json, sqlite3
import numpy as np

DB = "/home/hatch/workspace/gold-station/candles.db"
BULLISH, BEARISH = 1, -1

def load(interval):
    db = sqlite3.connect(DB)
    rows = db.execute(
        "SELECT ts,o,h,l,c,source FROM candles WHERE symbol='XAUUSD' AND interval=? ORDER BY ts",
        (interval,)).fetchall()
    db.close()
    # dedupe by ts, prefer ctrader
    best = {}
    for ts, o, h, l, c, src in rows:
        if ts not in best or src == "ctrader":
            best[ts] = (o, h, l, c)
    ts = sorted(best)
    O = np.array([best[t][0] for t in ts]); H = np.array([best[t][1] for t in ts])
    L = np.array([best[t][2] for t in ts]); C = np.array([best[t][3] for t in ts])
    return ts, O, H, L, C

def rma(x, n):
    out = np.full(len(x), np.nan); a = 1.0 / n
    s = None
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        s = v if s is None else s + a * (v - s)
        out[i] = s
    return out

class Leg:
    """Pine leg(size): var leg flips when bar[size] exceeds the last `size` bars."""
    def __init__(self, size):
        self.size = size; self.leg = 0
    def update(self, i, H, L):
        s = self.size
        if i < s:
            return 0
        change = 0
        new_high = H[i - s] > np.max(H[i - s + 1: i + 1])
        new_low = L[i - s] < np.min(L[i - s + 1: i + 1])
        old = self.leg
        if new_high:
            self.leg = 0
        elif new_low:
            self.leg = 1
        if self.leg != old:
            change = 1 if self.leg > old else -1
        return change

class Pivot:
    def __init__(self):
        self.level = np.nan; self.last = np.nan; self.crossed = False
        self.time = None; self.idx = -1

def run(interval="15min"):
    ts, O, H, L, C = load(interval)
    n = len(C)
    tr = np.maximum(H - L, np.maximum(np.abs(H - np.roll(C, 1)), np.abs(L - np.roll(C, 1))))
    tr[0] = H[0] - L[0]
    atr200 = rma(tr, 200)

    # parsed highs/lows with the ATR volatility filter (default filter = Atr)
    hv = (H - L) >= (2 * np.nan_to_num(atr200, nan=1e18))
    pH = np.where(hv, L, H); pL = np.where(hv, H, L)

    legs = {50: Leg(50), 5: Leg(5), 3: Leg(3)}
    piv = {"swingH": Pivot(), "swingL": Pivot(), "intH": Pivot(), "intL": Pivot(),
           "eqH": Pivot(), "eqL": Pivot()}
    trend = {"swing": 0, "internal": 0}
    events = []            # structure events
    eq_events = []         # EQH/EQL
    obs = {"internal": [], "swing": []}   # each: dict(hi,lo,idx,bias)
    fvgs = []              # dict(top,bottom,bias,idx)
    fvg_events = []
    cum_abs_delta = 0.0

    trail_top, trail_bot = -np.inf, np.inf

    def store_ob(kind, pivot_idx, i, bias):
        if bias == BEARISH:
            seg = pH[pivot_idx: i + 1]; j = pivot_idx + int(np.argmax(seg))
        else:
            seg = pL[pivot_idx: i + 1]; j = pivot_idx + int(np.argmin(seg))
        obs[kind].insert(0, {"hi": float(pH[j]), "lo": float(pL[j]), "idx": int(j),
                             "time": ts[j], "bias": bias})
        if len(obs[kind]) > 100:
            obs[kind].pop()

    for i in range(n):
        # trailing extremes (running, as in updateTrailingExtremes)
        trail_top = max(trail_top, H[i]); trail_bot = min(trail_bot, L[i])

        # --- FVG mitigation ---
        fvgs = [f for f in fvgs if not ((f["bias"] == BULLISH and L[i] < f["bottom"]) or
                                        (f["bias"] == BEARISH and H[i] > f["top"]))]

        # --- pivots: getCurrentStructure(50 / 5 / 3) ---
        for size, hk, lk in ((50, "swingH", "swingL"), (5, "intH", "intL"), (3, "eqH", "eqL")):
            ch = legs[size].update(i, H, L)
            if ch == 1:      # start of bullish leg -> new pivot low at bar i-size
                p = piv[lk]
                if size == 3 and not np.isnan(p.level) and abs(p.level - L[i - 3]) < 0.1 * (atr200[i] if not np.isnan(atr200[i]) else 0):
                    eq_events.append({"type": "EQL", "level": float(L[i - 3]), "time": ts[i - 3], "idx": i - 3})
                p.last, p.level, p.crossed, p.time, p.idx = p.level, L[i - size], False, ts[i - size], i - size
            elif ch == -1:    # start of bearish leg -> new pivot high
                p = piv[hk]
                if size == 3 and not np.isnan(p.level) and abs(p.level - H[i - 3]) < 0.1 * (atr200[i] if not np.isnan(atr200[i]) else 0):
                    eq_events.append({"type": "EQH", "level": float(H[i - 3]), "time": ts[i - 3], "idx": i - 3})
                p.last, p.level, p.crossed, p.time, p.idx = p.level, H[i - size], False, ts[i - size], i - size

        # --- displayStructure: internal then swing ---
        for internal in (True, False):
            hk, lk = ("intH", "intL") if internal else ("swingH", "swingL")
            tkey = "internal" if internal else "swing"
            kind = "internal" if internal else "swing"
            ph, pl = piv[hk], piv[lk]
            if i > 0:
                if not np.isnan(ph.level) and not ph.crossed and C[i] > ph.level and C[i - 1] <= ph.level:
                    if not internal or ph.level != piv["swingH"].level:
                        tag = "CHoCH" if trend[tkey] == BEARISH else "BOS"
                        events.append({"tf": kind, "dir": "bullish", "tag": tag,
                                       "level": float(ph.level), "time": ts[i], "idx": i,
                                       "pivot_time": ph.time})
                        ph.crossed = True; trend[tkey] = BULLISH
                        store_ob(kind, ph.idx, i, BULLISH)
                if not np.isnan(pl.level) and not pl.crossed and C[i] < pl.level and C[i - 1] >= pl.level:
                    if not internal or pl.level != piv["swingL"].level:
                        tag = "CHoCH" if trend[tkey] == BULLISH else "BOS"
                        events.append({"tf": kind, "dir": "bearish", "tag": tag,
                                       "level": float(pl.level), "time": ts[i], "idx": i,
                                       "pivot_time": pl.time})
                        pl.crossed = True; trend[tkey] = BEARISH
                        store_ob(kind, pl.idx, i, BEARISH)

        # --- order block mitigation (High/Low mode) ---
        for kind in ("internal", "swing"):
            obs[kind] = [o for o in obs[kind] if not (
                (o["bias"] == BEARISH and H[i] > o["hi"]) or
                (o["bias"] == BULLISH and L[i] < o["lo"]))]

        # --- FVG creation (chart timeframe) ---
        if i >= 2:
            delta_pct = (C[i - 1] - O[i - 1]) / (O[i - 1] * 100.0)
            cum_abs_delta += abs(delta_pct)
            thr = (cum_abs_delta / max(i, 1)) * 2 if i > 0 else 0.0
            if L[i] > H[i - 2] and C[i - 1] > H[i - 2] and delta_pct > thr:
                fvgs.insert(0, {"top": float(L[i]), "bottom": float(H[i - 2]), "bias": BULLISH, "idx": i - 1, "time": ts[i - 1]})
                fvg_events.append({"dir": "bullish", "top": float(L[i]), "bottom": float(H[i - 2]), "time": ts[i - 1]})
            if H[i] < L[i - 2] and C[i - 1] < L[i - 2] and -delta_pct > thr:
                fvgs.insert(0, {"top": float(L[i - 2]), "bottom": float(H[i]), "bias": BEARISH, "idx": i - 1, "time": ts[i - 1]})
                fvg_events.append({"dir": "bearish", "top": float(L[i - 2]), "bottom": float(H[i]), "time": ts[i - 1]})

    price = float(C[-1])
    rng = trail_top - trail_bot
    pos = (price - trail_bot) / rng * 100 if rng > 0 else 50.0
    zone = "Premium" if price > 0.95 * trail_bot + 0.05 * trail_top + 0.9 * rng * 0 else None
    # zones per original formulas
    prem_bot = 0.05 * trail_top + 0.95 * trail_bot + 0.9 * (trail_top - trail_bot)  # not used; computed below properly
    premium_bottom = trail_top - 0.05 * rng
    discount_top = trail_bot + 0.05 * rng
    eq_top = 0.525 * trail_top + 0.475 * trail_bot
    eq_bot = 0.475 * trail_top + 0.525 * trail_bot
    if price >= premium_bottom:
        zone = "Premium"
    elif price <= discount_top:
        zone = "Discount"
    elif eq_bot <= price <= eq_top:
        zone = "Equilibrium"
    else:
        zone = "Premium-side" if price > eq_top else "Discount-side"

    out = {
        "interval": interval, "bars": n, "from": ts[0], "to": ts[-1], "price": price,
        "swing_trend": {1: "BULLISH", -1: "BEARISH", 0: "—"}[trend["swing"]],
        "internal_trend": {1: "BULLISH", -1: "BEARISH", 0: "—"}[trend["internal"]],
        "swing_high": {"level": float(piv["swingH"].level), "time": piv["swingH"].time},
        "swing_low": {"level": float(piv["swingL"].level), "time": piv["swingL"].time},
        "internal_high": {"level": float(piv["intH"].level), "time": piv["intH"].time},
        "internal_low": {"level": float(piv["intL"].level), "time": piv["intL"].time},
        "trailing_top": float(trail_top), "trailing_bottom": float(trail_bot),
        "range_position_pct": round(pos, 1), "zone": zone,
        "events_total": len(events),
        "last_swing_events": [e for e in events if e["tf"] == "swing"][-6:],
        "last_internal_events": [e for e in events if e["tf"] == "internal"][-6:],
        "active_internal_obs": obs["internal"][:5],
        "active_swing_obs": obs["swing"][:5],
        "active_fvgs_near": [f for f in fvgs if abs((f["top"] + f["bottom"]) / 2 - price) < 60][:8],
        "last_eq_events": eq_events[-4:],
        "last_fvg_events": fvg_events[-5:],
    }
    return out, (ts, O, H, L, C), events, obs, fvgs

if __name__ == "__main__":
    interval = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "15min"
    res, _, _, _, _ = run(interval)
    print(json.dumps(res, ensure_ascii=False, indent=1))
