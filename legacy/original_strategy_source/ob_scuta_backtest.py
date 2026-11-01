#!/usr/bin/env python3
"""
SCUTA Order Block rule — backtest on local gold candles (research only).

Rule (from the SCUTA video extraction; choices the video left open are
DECLARED here and in the report):
  1. Displacement candle: closed candle with body |c-o| >= MULT * ATR(14),
     ATR = simple mean of the True Ranges of the 14 PRIOR candles
     (no lookahead). Direction = candle direction.
  2. Order Block = last candle before the displacement candle whose
     direction is opposite to it. Zone = that candle's full high-low range.
  3. Entry: first later candle that retests the zone -> limit fill at the
     proximal edge (bullish disp.: zone high; bearish: zone low).
     A candle that closes beyond the distal edge without touching the
     proximal edge invalidates the zone (no trade). One trade per zone,
     first retest only.
  4. Stop loss at the distal edge (bullish: zone low; bearish: zone high).
     No buffer.
  5. Target: fixed +2R, R = |entry - SL|.
  6. Same-candle SL+TP conflict: stop-first (conservative).
  7. One open position at a time: no new zones are created while a trade
     is open; pending zones are discarded when a trade is entered.
  8. Timeout: if neither SL nor TP within 1000 candles from the entry
     candle, close at that candle's close and record actual R.

Costs (Adaptive V2 realistic model): price degradation against the trader,
split half at entry / half at exit:
  gross    = 0.00 $ round trip
  net      = 0.40 $ round trip (spread 0.30 + slippage 0.10)
  pressure = 0.80 $ round trip (x2)
SL/TP trigger levels are the planned (gross) levels; executed entry/exit
prices are degraded by the per-side cost. Result R = $PnL / planned R $.

Data: ~/workspace/gold-station/candles.db, table candles
(symbol, interval, ts, source, o, h, l, c). ts = Damascus local time.
Duplicate ts: source 'ctrader' preferred. Read-only.
"""

import json
import sqlite3
import sys

import numpy as np

DB = "/home/hatch/workspace/gold-station/candles.db"
SYMBOL = "XAUUSD"
ATR_LEN = 14
MAX_HOLD = 1000

COSTS = {"gross": 0.0, "net": 0.40, "pressure": 0.80}  # round-trip $
RUNS = [
    ("A", "5min", 1.5),
    ("B", "15min", 1.5),
    ("C", "5min", 1.0),
]


def load_candles(interval):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT ts, source, o, h, l, c FROM candles WHERE symbol=? AND interval=?",
        (SYMBOL, interval),
    ).fetchall()
    con.close()
    by_ts = {}
    for ts, source, o, h, l, c in rows:
        if ts in by_ts and by_ts[ts][0] == "ctrader":
            continue  # keep ctrader
        by_ts[ts] = (source, o, h, l, c)
    tss = sorted(by_ts)
    data = [by_ts[t] for t in tss]
    return {
        "ts": tss,
        "o": np.array([d[1] for d in data], dtype=float),
        "h": np.array([d[2] for d in data], dtype=float),
        "l": np.array([d[3] for d in data], dtype=float),
        "c": np.array([d[4] for d in data], dtype=float),
    }


def compute_atr(cand, n=ATR_LEN):
    """ATR at index i = mean TR of candles i-n .. i-1 (prior only)."""
    h, l, c = cand["h"], cand["l"], cand["c"]
    N = len(c)
    tr = np.zeros(N)
    tr[1:] = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    atr = np.full(N, np.nan)
    cs = np.cumsum(tr)
    for i in range(n, N):
        atr[i] = (cs[i - 1] - (cs[i - n - 1] if i - n - 1 >= 0 else 0.0)) / n
    return atr


def find_trades(cand, mult):
    """Return list of gross trade dicts (prices before costs)."""
    o, h, l, c, ts = cand["o"], cand["h"], cand["l"], cand["c"], cand["ts"]
    N = len(c)
    atr = compute_atr(cand)
    trades = []
    pending = []  # list of zone dicts, oldest first
    i = ATR_LEN + 1
    while i < N:
        # --- check pending zones for retest / invalidation on candle i ---
        filled = None
        still = []
        for z in pending:
            if z["dir"] == 1:  # bullish displacement -> buy the dip into zone
                if l[i] <= z["prox"]:  # touched proximal edge -> fill
                    filled = z
                    break
                if c[i] < z["dist"]:  # closed beyond distal, no fill
                    continue  # invalidated, drop
                still.append(z)
            else:  # bearish displacement -> sell the rally into zone
                if h[i] >= z["prox"]:
                    filled = z
                    break
                if c[i] > z["dist"]:
                    continue
                still.append(z)
        if filled is not None:
            pending = []  # one position at a time: discard other zones
            entry = filled["prox"]
            sl = filled["dist"]
            risk = abs(entry - sl)
            tp = entry + filled["dir"] * 2.0 * risk
            exit_price, exit_kind, exit_idx = None, None, None
            for k in range(i, min(i + MAX_HOLD, N)):
                if filled["dir"] == 1:
                    if l[k] <= sl:
                        exit_price, exit_kind, exit_idx = sl, "sl", k
                        break
                    if h[k] >= tp:
                        exit_price, exit_kind, exit_idx = tp, "tp", k
                        break
                else:
                    if h[k] >= sl:
                        exit_price, exit_kind, exit_idx = sl, "sl", k
                        break
                    if l[k] <= tp:
                        exit_price, exit_kind, exit_idx = tp, "tp", k
                        break
            if exit_idx is None:
                exit_idx = min(i + MAX_HOLD - 1, N - 1)
                exit_price, exit_kind = c[exit_idx], "timeout"
            trades.append(
                {
                    "dir": filled["dir"],
                    "entry": float(entry),
                    "sl": float(sl),
                    "tp": float(tp),
                    "risk": float(risk),
                    "exit": float(exit_price),
                    "exit_kind": exit_kind,
                    "entry_ts": ts[i],
                    "exit_ts": ts[exit_idx],
                }
            )
            i = exit_idx + 1
            continue
        pending = still
        # --- displacement detection on candle i (only while flat) ---
        a = atr[i]
        if not np.isnan(a) and a > 0:
            body = c[i] - o[i]
            if abs(body) >= mult * a:
                d = 1 if body > 0 else -1
                # last opposite-direction candle before i
                j = i - 1
                while j >= 0:
                    bj = c[j] - o[j]
                    if bj != 0 and (1 if bj > 0 else -1) == -d:
                        break
                    j -= 1
                if j >= 0:
                    if d == 1:
                        prox, dist = h[j], l[j]
                    else:
                        prox, dist = l[j], h[j]
                    if dist != prox:
                        pending.append(
                            {"dir": d, "prox": float(prox), "dist": float(dist)}
                        )
        i += 1
    return trades


def apply_costs(trades, round_trip):
    side = round_trip / 2.0
    out = []
    for t in trades:
        e = t["entry"] + t["dir"] * side  # worse fill
        x = t["exit"] - t["dir"] * side  # worse exit
        pnl = t["dir"] * (x - e)
        out.append({**t, "r": pnl / t["risk"], "pnl_usd": pnl})
    return out


def metrics(trades, round_trip):
    if not trades:
        return {"trades": 0}
    rs = np.array([t["r"] for t in trades])
    wins = rs > 0
    gp = rs[rs > 0].sum()
    gl = -rs[rs < 0].sum()
    eq = np.cumsum(rs)
    peak = np.maximum.accumulate(eq)
    mdd = float((peak - eq).max()) if len(eq) else 0.0
    avg_risk = float(np.mean([t["risk"] for t in trades]))
    cost_pct = (round_trip / avg_risk * 100.0) if avg_risk > 0 else 0.0
    c_frac = round_trip / avg_risk if avg_risk > 0 else 0.0  # cost in R units
    be_wr = (1.0 + c_frac) / 3.0 * 100.0  # theoretical, for 2R target / -1R stop
    return {
        "trades": int(len(rs)),
        "win_rate": float(wins.mean() * 100),
        "avg_r": float(rs.mean()),
        "total_r": float(rs.sum()),
        "pf": float(gp / gl) if gl > 0 else float("inf"),
        "max_dd_r": mdd,
        "avg_risk_usd": avg_risk,
        "avg_cost_pct_risk": float(cost_pct),
        "be_win_rate": float(be_wr),
        "tp_exits": int(sum(1 for t in trades if t["exit_kind"] == "tp")),
        "sl_exits": int(sum(1 for t in trades if t["exit_kind"] == "sl")),
        "timeout_exits": int(sum(1 for t in trades if t["exit_kind"] == "timeout")),
    }


def split_metrics(trades):
    res = {}
    for name, d in (("long", 1), ("short", -1)):
        sub = [t for t in trades if t["dir"] == d]
        if sub:
            rs = np.array([t["r"] for t in sub])
            res[name] = {
                "trades": int(len(rs)),
                "win_rate": float((rs > 0).mean() * 100),
                "avg_r": float(rs.mean()),
                "total_r": float(rs.sum()),
            }
        else:
            res[name] = {"trades": 0}
    return res


def main():
    all_out = {}
    for run_id, interval, mult in RUNS:
        cand = load_candles(interval)
        gross_trades = find_trades(cand, mult)
        run = {
            "interval": interval,
            "mult": mult,
            "coverage": {"from": cand["ts"][0], "to": cand["ts"][-1],
                         "candles": len(cand["ts"])},
            "scenarios": {},
        }
        for scen, rt in COSTS.items():
            tr = apply_costs(gross_trades, rt)
            run["scenarios"][scen] = {
                "metrics": metrics(tr, rt),
                "split": split_metrics(tr),
            }
        all_out[run_id] = run
        print(f"Run {run_id} ({interval}, x{mult}): "
              f"{len(gross_trades)} trades, coverage "
              f"{cand['ts'][0]} -> {cand['ts'][-1]} ({len(cand['ts'])} candles)")
        for scen in COSTS:
            m = run["scenarios"][scen]["metrics"]
            if m["trades"]:
                print(f"  {scen:9s} WR {m['win_rate']:5.1f}%  avgR {m['avg_r']:+.3f}  "
                      f"totR {m['total_r']:+.2f}  PF {m['pf']:.2f}  "
                      f"maxDD {m['max_dd_r']:.2f}R  cost% {m['avg_cost_pct_risk']:.1f}")
    print(json.dumps(all_out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
