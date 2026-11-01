#!/usr/bin/env python3
"""Research-only, causal XAUUSD Sweep/MSS/FVG strategy comparison.

OHLC bars MUST be chronologically ordered bar OPEN timestamps.  Bid is default;
mid prices are supported via --price-basis mid.  No real orders or API calls.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

SETUPS = ("sweep", "sweep_mss", "sweep_mss_fvg", "filtered")

@dataclass(frozen=True)
class Settings:
    timeframe_minutes: int = 15
    initial_capital: float = 10000.0
    risk_fraction: float = 0.005
    daily_loss_fraction: float = 0.015
    contract_size: float = 100.0
    tick_size: float = 0.01
    volume_min: float = 0.01
    volume_max: float = 50.0
    volume_step: float = 0.01
    commission_roundtrip_per_lot: float = 7.0
    assumed_spread_price: float = 0.20
    point_size: float = 0.01
    entry_slippage: float = 0.05
    stop_slippage: float = 0.10
    sweep_window: int = 3
    mss_bars: int = 8
    fvg_bars: int = 4
    retest_bars: int = 6
    atr_period: int = 14
    atr_stop_fraction: float = 0.15
    rr: float = 2.0
    price_basis: str = "bid"
    margin_per_lot: float = 0.0  # Optional broker-supplied USD margin estimate, 0=unknown
    # The daily-loss guard blocks NEW trades. It cannot cap loss on an open trade.


def load_candles(path: str | Path, cfg: Settings, table: str | None = None,
                 symbol: str | None = None, timeframe_name: str | None = None) -> tuple[pd.DataFrame, dict]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"REAL_DATA_MISSING: {path}; no synthetic fallback")
    if path.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        if not table or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError("SQLite input requires a safe --table TABLE_NAME")
        with sqlite3.connect(path) as conn:
            column_rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = {str(c[1]).lower(): c[1] for c in column_rows}
            if not columns:
                raise ValueError(f"SQLite table not found: {table}")
            where, values = [], []
            for field, value in (("symbol", symbol), ("timeframe", timeframe_name)):
                if value is not None:
                    if field not in columns:
                        raise ValueError(f"Requested {field} filter but column is missing")
                    where.append(f'"{columns[field]}" = ?')
                    values.append(value)
            sql = f'SELECT * FROM "{table}"' + (" WHERE " + " AND ".join(where) if where else "")
            df = pd.read_sql_query(sql, conn, params=values)
    else:
        df = pd.read_csv(path)
    cols = {str(c).strip().lower(): c for c in df.columns}
    needed = ("time", "open", "high", "low", "close")
    missing = [c for c in needed if c not in cols]
    if missing:
        raise ValueError(f"Missing CSV columns: {missing}; required: {needed}")
    df = df.rename(columns={cols[c]: c for c in cols})
    if not len(df):
        raise ValueError("Empty CSV")
    raw_time = df["time"]
    if pd.api.types.is_numeric_dtype(raw_time):
        maximum = raw_time.abs().max()
        unit = "us" if maximum > 1e14 else ("ms" if maximum > 1e11 else "s")
        df["time"] = pd.to_datetime(raw_time, unit=unit, utc=True, errors="raise")
    else:
        df["time"] = pd.to_datetime(raw_time, utc=True, errors="raise", format="mixed")
    if df["time"].isna().any() or df["time"].duplicated().any():
        raise ValueError("Missing or duplicated candle time")
    if not df["time"].is_monotonic_increasing:
        raise ValueError("CSV times not strictly increasing; fix source order")
    for c in needed[1:]:
        df[c] = pd.to_numeric(df[c], errors="raise")
    a = df[list(needed[1:])].to_numpy(dtype=float)
    if not np.isfinite(a).all() or (a <= 0).any():
        raise ValueError("OHLC contains nonpositive/nonfinite values")
    if (df["high"] < df[["open", "low", "close"]].max(axis=1)).any() or \
       (df["low"] > df[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError("Invalid OHLC: high/low do not enclose open and close")
    if "spread_price" in cols:
        df["spread_price"] = pd.to_numeric(df[cols["spread_price"]], errors="raise")
        spread_source = "spread_price: native price units"
    elif "spread" in cols:
        df["spread_price"] = pd.to_numeric(df[cols["spread"]], errors="raise") * cfg.point_size
        spread_source = f"spread (points) * point_size={cfg.point_size}"
    else:
        df["spread_price"] = cfg.assumed_spread_price
        spread_source = f"ASSUMED CONSTANT {cfg.assumed_spread_price} USD (not historical)"
    if (df["spread_price"] < 0).any() or not np.isfinite(df["spread_price"]).all():
        raise ValueError("Invalid spread")
    if cfg.price_basis == "mid":
        # Convert MID bar approximations to BID. Assumes constant spread within each bar.
        for c in ("open", "high", "low", "close"):
            df[c] = df[c] - df["spread_price"] / 2
        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("Mid-to-bid conversion produced invalid price")
    elif cfg.price_basis != "bid":
        raise ValueError("price_basis must be bid or mid")
    tf = pd.Timedelta(minutes=cfg.timeframe_minutes)
    if cfg.timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be > 0")
    # Refuse partially closed present-day bars; historical bars remain intact.
    end = df["time"] + tf
    incomplete = end > pd.Timestamp.now(tz="UTC")
    n_incomplete = int(incomplete.sum())
    df = df.loc[~incomplete].reset_index(drop=True)
    if df.empty:
        raise ValueError("No fully closed candles remain")
    gaps = (df["time"].diff().dropna() != tf)
    out = {
        "bars": int(len(df)), "start": str(df.time.iloc[0]), "end": str(df.time.iloc[-1]),
        "unexpected_intervals": int(gaps.sum()), "dropped_incomplete": n_incomplete,
        "spread_source": spread_source, "price_basis": cfg.price_basis,
        "weekend_utc_bars": int((df.time.dt.dayofweek >= 5).sum()),
        "note": "UTC Sunday sessions can be real; no day-of-week filtering applied",
    }
    return df, out


def features(bars: pd.DataFrame, cfg: Settings) -> pd.DataFrame:
    df = bars.copy()
    w = cfg.sweep_window
    if w < 1:
        raise ValueError("sweep_window must be >= 1")
    hi_pivot = df.high.eq(df.high.rolling(2*w+1, center=True).max())
    lo_pivot = df.low.eq(df.low.rolling(2*w+1, center=True).min())
    # A pivot from index t may only be used at t+w (after w bars have CLOSED).
    df["last_sh"] = df.high.shift(w).where(hi_pivot.shift(w).eq(True)).ffill()
    df["last_sl"] = df.low.shift(w).where(lo_pivot.shift(w).eq(True)).ffill()
    df["fvg_bull"] = df.low > df.high.shift(2)
    df["fvg_bear"] = df.high < df.low.shift(2)
    prev = df.close.shift(1)
    true_range = pd.concat([
        df.high - df.low, (df.high-prev).abs(), (df.low-prev).abs()
    ], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(cfg.atr_period, min_periods=cfg.atr_period).mean()
    df["close_time"] = df.time + pd.Timedelta(minutes=cfg.timeframe_minutes)
    for minutes, ema_span in ((60, 20), (240, 10)):
        col = f"trend_{minutes}"
        if minutes % cfg.timeframe_minutes:
            df[col] = 0
            continue
        bars_per_htf = minutes // cfg.timeframe_minutes
        if bars_per_htf <= 1:
            df[col] = 0
            continue
        temp = df.set_index("close_time").resample(
            f"{minutes}min", label="right", closed="right"
        ).agg(close=("close", "last"), count=("close", "count"))
        temp["close"] = temp.close.where(temp["count"] == bars_per_htf)
        # No forward fill across missing higher-timeframe bars.
        ema = temp.close.ewm(span=ema_span, adjust=False, min_periods=ema_span, ignore_na=False).mean()
        prev_ema = ema.shift(1)
        temp[col] = np.where((temp.close > ema) & (ema > prev_ema), 1,
                    np.where((temp.close < ema) & (ema < prev_ema), -1, 0))
        htf = temp[[col]].reset_index().rename(columns={"close_time": "htf_time"})
        aligned = pd.merge_asof(
            df[["close_time"]].sort_values("close_time"),
            htf.sort_values("htf_time"),
            left_on="close_time", right_on="htf_time", direction="backward"
        )
        df[col] = aligned[col].fillna(0).astype(int).to_numpy()
    london = df.close_time.dt.tz_convert("Europe/London")
    new_york = df.close_time.dt.tz_convert("America/New_York")
    df["session_ok"] = london.dt.hour.between(8, 10) | new_york.dt.hour.between(8, 10)
    return df


def signals(df: pd.DataFrame, cfg: Settings, setup: str) -> pd.DataFrame:
    if setup not in SETUPS:
        raise ValueError(setup)
    x = df.copy()
    x["signal"] = 0
    x["stop"] = np.nan
    x["sweep_extreme"] = np.nan
    x["reason"] = ""
    x["signal_id"] = ""
    x["signal_confirmed_at"] = pd.Series(pd.NaT, index=x.index, dtype="datetime64[ns, UTC]")
    pending: dict[int, dict | None] = {1: None, -1: None}

    def emit(i: int, side: int, event: dict, reason: str):
        if int(x.at[i, "signal"]) != 0:
            # An ambiguous opposite-direction signal is rejected.
            x.at[i, "signal"] = 0
            x.at[i, "stop"] = np.nan
            x.at[i, "reason"] = "AMBIGUOUS"
            x.at[i, "signal_id"] = ""
            return
        atr = float(x.at[i, "atr"])
        if not math.isfinite(atr):
            return
        buffer = max(cfg.tick_size * 2, atr * cfg.atr_stop_fraction)
        ext = event["extreme"]
        # Stop for a short is an ASK threshold; events are detected on BID prices.
        spread = float(x.at[i, "spread_price"])
        raw_stop = ext - buffer if side == 1 else ext + buffer + spread
        # Place stop on a valid tick at least as conservative as the raw stop.
        stop = ((math.floor(raw_stop/cfg.tick_size + 1e-9) if side == 1
                else math.ceil(raw_stop/cfg.tick_size - 1e-9)) * cfg.tick_size)
        x.at[i, "signal"] = side
        x.at[i, "stop"] = stop
        x.at[i, "sweep_extreme"] = ext
        x.at[i, "reason"] = reason
        x.at[i, "signal_id"] = f"{setup}:{side}:{x.at[event['idx'], 'time'].isoformat()}"
        x.at[i, "signal_confirmed_at"] = x.at[i, "time"] + pd.Timedelta(minutes=cfg.timeframe_minutes)

    for i in range(len(x)):
        r = x.iloc[i]
        if not np.isfinite(r.atr):
            continue
        # Advance old events first. All comparisons use data known at THIS close.
        for side in (1, -1):
            e = pending[side]
            if e is None:
                continue
            age = i - e["idx"]
            if age > cfg.mss_bars + cfg.fvg_bars + cfg.retest_bars or \
               (side == 1 and r.close < e["extreme"]) or \
               (side == -1 and r.close > e["extreme"]):
                pending[side] = None
                continue
            if age < 1:
                continue
            if not e["mss"]:
                if age > cfg.mss_bars:
                    pending[side] = None
                    continue
                threshold = e["break_level"]
                crossing = ((r.close > threshold and x.at[i-1, "close"] <= threshold)
                            if side == 1 else
                            (r.close < threshold and x.at[i-1, "close"] >= threshold))
                if crossing:
                    e["mss"] = True
                    e["mss_idx"] = i
                    if setup == "sweep_mss":
                        emit(i, side, e, "SWEEP+CONFIRMED_MSS")
                        pending[side] = None
                        continue
            if e["mss"] and setup in ("sweep_mss_fvg", "filtered"):
                if "fvg_idx" not in e:
                    if i - e["mss_idx"] > cfg.fvg_bars:
                        pending[side] = None
                        continue
                    fvg = bool(r.fvg_bull) if side == 1 else bool(r.fvg_bear)
                    if fvg:
                        e["fvg_idx"] = i
                        if setup == "sweep_mss_fvg":
                            emit(i, side, e, "SWEEP+MSS+FVG")
                            pending[side] = None
                        else:
                            # Save zone established at this bar CLOSE. Retest starts NEXT bar.
                            e["fvg_top"] = float(r.low) if side == 1 else float(x.at[i-2, "low"])
                            e["fvg_bottom"] = float(x.at[i-2, "high"]) if side == 1 else float(r.high)
                elif setup == "filtered" and i > e["fvg_idx"]:
                    if i - e["fvg_idx"] > cfg.retest_bars:
                        pending[side] = None
                        continue
                    touched = (r.low <= e["fvg_top"] if side == 1 else r.high >= e["fvg_bottom"])
                    invalid_zone = (r.close < e["fvg_bottom"] if side == 1 else r.close > e["fvg_top"])
                    if invalid_zone:
                        pending[side] = None
                    elif touched:
                        passes = (int(r.trend_60) == side and int(r.trend_240) == side
                                  and bool(r.session_ok))
                        if passes:
                            emit(i, side, e, "SWEEP+MSS+FVG_RETEST+H1/H4+SESSION")
                        pending[side] = None
        # Detect a fresh sweep using ONLY the last fully confirmed pivot (previous bar).
        if i == 0:
            continue
        low_level, high_level = x.at[i-1, "last_sl"], x.at[i-1, "last_sh"]
        bull = pd.notna(low_level) and r.low < low_level and r.close > low_level
        bear = pd.notna(high_level) and r.high > high_level and r.close < high_level
        if bull and bear:
            continue  # outside candle swept both sides; ordering unavailable
        for side, active in ((1, bull), (-1, bear)):
            if not active:
                continue
            ext = float(r.low if side == 1 else r.high)
            ref = high_level if side == 1 else low_level
            event = {"idx": i, "extreme": ext, "break_level": float(ref) if pd.notna(ref) else np.nan,
                     "mss": False, "mss_idx": None}
            if setup == "sweep":
                emit(i, side, event, "CONFIRMED_SWEEP")
            elif pd.notna(ref):
                pending[side] = event
    return x


class Simulator:
    """Bar-level BID execution, SL-first on ambiguous candles. Research, not live execution."""
    def __init__(self, cfg: Settings):
        self.c = cfg
        self.balance = cfg.initial_capital
        self.position: dict | None = None
        self.trades: list[dict] = []
        self.equity: list[dict] = []
        self.day = None
        self.day_start = cfg.initial_capital
        self.locked = False
        self.rejected: dict[str, int] = {}

    def reject(self, reason: str):
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    def equity_at(self, bid: float, spread: float) -> float:
        p = self.position
        if p is None:
            return self.balance
        quote = bid if p["direction"] == 1 else bid + spread
        pnl_open = (quote - p["entry"]) * p["direction"] * self.c.contract_size * p["remaining"]
        estimated_fees = self.c.commission_roundtrip_per_lot * p["remaining"]
        return self.balance + pnl_open - estimated_fees

    def close(self, price: float, tag: str, timestamp):
        p = self.position
        if p is None:
            return
        # Only a single TP 2R is used to compare equal, reproducible hypotheses.
        pnl = (price - p["entry"]) * p["direction"] * self.c.contract_size * p["lots"]
        pnl -= self.c.commission_roundtrip_per_lot * p["lots"]
        self.balance += pnl
        self.trades.append({
            "signal_id": p["signal_id"], "side": "BUY" if p["direction"] == 1 else "SELL",
            "entry_time": p["entry_time"], "exit_time": timestamp,
            "entry": p["entry"], "exit": price, "stop": p["stop"], "target": p["target"],
            "lots": p["lots"], "pnl": pnl, "risk_dollars": p["risk_dollars"],
            "r_multiple": pnl / p["risk_dollars"], "result": tag,
        })
        self.position = None

    def manage_bar(self, row, bar_end):
        p = self.position
        if p is None:
            return
        d, sl, tp = p["direction"], p["stop"], p["target"]
        spread = float(row.spread_price)
        open_quote = float(row.open) if d == 1 else float(row.open) + spread
        high_quote = float(row.high) if d == 1 else float(row.high) + spread
        low_quote = float(row.low) if d == 1 else float(row.low) + spread
        # STOP is a stop-market fill; OPEN GAP can be worse than stop threshold.
        gap_stop = open_quote <= sl if d == 1 else open_quote >= sl
        gap_target = open_quote >= tp if d == 1 else open_quote <= tp
        intra_stop = low_quote <= sl if d == 1 else high_quote >= sl
        intra_target = high_quote >= tp if d == 1 else low_quote <= tp
        if gap_stop:
            self.close(open_quote - d*self.c.stop_slippage, "STOP_GAP", row.time)
        elif gap_target:
            self.close(tp, "TARGET_GAP_LIMIT", row.time)  # no optimistic gap bonus
        elif intra_stop:
            self.close(sl - d*self.c.stop_slippage, "STOP", bar_end)
        elif intra_target:
            self.close(tp, "TARGET", bar_end)

    def enter(self, row, signal_row):
        d = int(signal_row.signal)
        if d not in (1, -1):
            return
        spread = float(row.spread_price)
        entry = float(row.open) + (spread if d == 1 else 0) + d*self.c.entry_slippage
        stop = float(signal_row.stop)
        dist = (entry-stop)*d
        if not np.isfinite(dist) or dist <= self.c.tick_size:
            self.reject("INVALID_STOP")
            return
        allowed = min(self.balance, self.equity_at(float(row.open), spread)) * self.c.risk_fraction
        full_stop_loss_per_lot = (dist + self.c.stop_slippage) * self.c.contract_size + self.c.commission_roundtrip_per_lot
        lots = math.floor((allowed / full_stop_loss_per_lot + 1e-10) / self.c.volume_step) * self.c.volume_step
        lots = round(min(lots, self.c.volume_max), 8)
        if self.c.margin_per_lot > 0:
            affordable = math.floor((max(0, self.balance) / self.c.margin_per_lot + 1e-10)
                                    / self.c.volume_step) * self.c.volume_step
            lots = round(min(lots, affordable), 8)
        if lots < self.c.volume_min:
            self.reject("BELOW_MINIMUM_LOT")
            return
        unrounded_target = entry + d * dist * self.c.rr
        # Conservative tick rounding on profit targets.
        tick = self.c.tick_size
        target = ((math.floor(unrounded_target/tick + 1e-9) if d == 1
                   else math.ceil(unrounded_target/tick - 1e-9)) * tick)
        if (target - entry)*d <= 0:
            self.reject("INVALID_TARGET")
            return
        self.position = dict(direction=d, entry=entry, stop=stop, target=target,
                             lots=lots, remaining=lots, entry_time=row.time,
                             risk_dollars=full_stop_loss_per_lot*lots,
                             signal_id=signal_row.signal_id)

    def run(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        td = pd.Timedelta(minutes=self.c.timeframe_minutes)
        for i in range(len(df)):
            row = df.iloc[i]
            # Daily reset is based on the ACTUAL bar open (UTC research convention).
            equity_open = self.equity_at(float(row.open), float(row.spread_price))
            date = row.time.date()
            if date != self.day:
                self.day, self.day_start, self.locked = date, equity_open, False
            if equity_open <= self.day_start*(1-self.c.daily_loss_fraction):
                self.locked = True
            had_open = self.position is not None
            if had_open:
                self.manage_bar(row, row.time+td)
            elif i > 0 and df.iloc[i-1].signal != 0:
                last = df.iloc[i-1]
                if row.time != last.time + td:
                    self.reject("DELAYED_AFTER_GAP")
                elif self.locked:
                    self.reject("DAILY_LIMIT")
                else:
                    self.enter(row, last)
                    self.manage_bar(row, row.time+td)  # entry bar included
            equity_close = self.equity_at(float(row.close), float(row.spread_price))
            if equity_close <= self.day_start*(1-self.c.daily_loss_fraction):
                self.locked = True
            self.equity.append({"time": row.time+td, "equity": equity_close,
                                "cash": self.balance, "daily_locked": self.locked})
        if self.position is not None:
            last = df.iloc[-1]
            exit_quote = float(last.close) + (float(last.spread_price) if self.position["direction"] == -1 else 0)
            self.close(exit_quote - self.position["direction"]*self.c.stop_slippage,
                       "END_OF_DATA_MARKET_LIQUIDATION", last.time+td)
            if self.equity:
                self.equity[-1]["equity"] = self.balance
                self.equity[-1]["cash"] = self.balance
        return pd.DataFrame(self.trades), pd.DataFrame(self.equity)


def wilson_interval(wins: int, count: int, z: float = 1.96):
    """Approximate 95% Wilson confidence interval for observed trade win rate."""
    if count == 0:
        return None
    p = wins / count
    denom = 1 + z*z/count
    center = (p + z*z/(2*count)) / denom
    half = z*math.sqrt(p*(1-p)/count + z*z/(4*count*count))/denom
    return [round(100*(center-half), 2), round(100*(center+half), 2)]


def performance(trades: pd.DataFrame, curve: pd.DataFrame, cfg: Settings) -> dict:
    if len(curve):
        series = pd.concat([pd.Series([cfg.initial_capital]), curve.equity.reset_index(drop=True)], ignore_index=True)
        dd = (series / series.cummax() - 1).min() * 100
        final = float(series.iloc[-1])
    else:
        dd, final = 0.0, cfg.initial_capital
    if trades.empty:
        return {"trades": 0, "buy": 0, "sell": 0, "win_rate_pct": None,
                "profit_factor": None, "avg_r": None, "max_drawdown_pct": float(dd),
                "win_rate_95ci_pct": None, "buy_win_rate_pct": None,
                "sell_win_rate_pct": None, "small_sample_warning": True,
                "net_pnl": final-cfg.initial_capital, "final_equity": final}
    wins = trades.loc[trades.pnl > 0, "pnl"].sum()
    losses = -trades.loc[trades.pnl < 0, "pnl"].sum()
    pf = float(wins/losses) if losses > 0 else None
    by = trades[trades.side == "BUY"]
    se = trades[trades.side == "SELL"]
    return {"trades": len(trades), "buy": int((trades.side == "BUY").sum()),
            "sell": int((trades.side == "SELL").sum()),
            "win_rate_pct": round(float((trades.pnl > 0).mean() * 100), 2),
            "win_rate_95ci_pct": wilson_interval(int((trades.pnl > 0).sum()), len(trades)),
            "buy_win_rate_pct": round(float((by.pnl > 0).mean()*100), 2) if len(by) else None,
            "sell_win_rate_pct": round(float((se.pnl > 0).mean()*100), 2) if len(se) else None,
            "small_sample_warning": bool(len(trades) < 100),
            "profit_factor": round(pf, 3) if pf is not None else None,
            "avg_r": round(float(trades.r_multiple.mean()), 4),
            "max_drawdown_pct": round(float(dd), 3),
            "net_pnl": round(float(final-cfg.initial_capital), 2),
            "final_equity": round(float(final), 2)}


def run_comparison(bars: pd.DataFrame, cfg: Settings, outdir: str | Path,
                   evaluation: str = "all", holdout_fraction: float = 0.30) -> dict:
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    if evaluation not in ("all", "dev", "holdout"):
        raise ValueError("evaluation must be all/dev/holdout")
    if not 0 < holdout_fraction < 0.8:
        raise ValueError("holdout_fraction must be between 0 and 0.8")
    feat = features(bars, cfg)
    split_index = int(len(feat)*(1-holdout_fraction))
    if split_index < 100 or len(feat)-split_index < 30:
        raise ValueError("Not enough candles for split; provide at least ~200 closed candles")
    report = {"mode": evaluation, "split_time": str(feat.time.iloc[split_index]),
              "assumptions": asdict(cfg), "results": {}}
    for name in SETUPS:
        marked = signals(feat, cfg, name)
        if evaluation != "all":
            if evaluation == "dev":
                marked.loc[marked.index >= split_index, "signal"] = 0
                data = marked.iloc[:split_index].copy().reset_index(drop=True)
            else:
                # Generate features on ALL previous history, then only test signals in holdout.
                data = marked.iloc[max(0, split_index-1):].copy().reset_index(drop=True)
                data.loc[0, "signal"] = 0
                data.loc[0, "stop"] = np.nan
        else:
            data = marked
        sim = Simulator(cfg)
        trade_log, curve = sim.run(data)
        summary = performance(trade_log, curve, cfg)
        summary["signals"] = int((data.signal != 0).sum())
        summary["rejections"] = sim.rejected
        report["results"][name] = summary
        trade_log.to_csv(out/f"trades_{name}.csv", index=False)
        curve.to_csv(out/f"equity_{name}.csv", index=False)
        cols = ["time", "signal_confirmed_at", "signal", "signal_id", "reason", "sweep_extreme", "stop", "close"]
        data.loc[data.signal != 0, cols].to_csv(out/f"signals_{name}.csv", index=False)
    (out/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def cli():
    p = argparse.ArgumentParser(description="XAUUSD research backtest on your own CSV candles. No MT5/API.")
    p.add_argument("--csv", required=True, help="CSV or SQLite .db with time,open,high,low,close")
    p.add_argument("--table", help="SQLite table name (required for .db)")
    p.add_argument("--symbol", help="Optional SQLite symbol filter, e.g. XAUUSD")
    p.add_argument("--timeframe-name", help="Optional SQLite timeframe field filter, e.g. M15")
    p.add_argument("--out", default="gold_results")
    p.add_argument("--timeframe-minutes", type=int, default=15)
    p.add_argument("--price-basis", choices=["bid", "mid"], default="bid")
    p.add_argument("--spread-price", type=float, default=0.20,
                   help="Fallback constant spread in price dollars if absent from CSV")
    p.add_argument("--point", type=float, default=0.01, help="Value of one broker spread POINT in price units")
    p.add_argument("--contract-size", type=float, default=100.0)
    p.add_argument("--tick-size", type=float, default=0.01)
    p.add_argument("--margin-per-lot", type=float, default=0.0, help="Broker reported USD margin per lot, 0=unknown")
    p.add_argument("--commission-rt", type=float, default=7.0, help="USD per lot for entire round trip")
    p.add_argument("--risk", type=float, default=0.005)
    p.add_argument("--capital", type=float, default=10000.0)
    p.add_argument("--entry-slip", type=float, default=0.05)
    p.add_argument("--stop-slip", type=float, default=0.10)
    p.add_argument("--min-lot", type=float, default=0.01)
    p.add_argument("--max-lot", type=float, default=50.0)
    p.add_argument("--lot-step", type=float, default=0.01)
    p.add_argument("--evaluation", choices=["dev", "holdout", "all"], default="dev")
    p.add_argument("--holdout-fraction", type=float, default=0.30)
    a = p.parse_args()
    cfg = Settings(timeframe_minutes=a.timeframe_minutes, price_basis=a.price_basis,
                   assumed_spread_price=a.spread_price, point_size=a.point,
                   contract_size=a.contract_size, commission_roundtrip_per_lot=a.commission_rt,
                   risk_fraction=a.risk, initial_capital=a.capital,
                   entry_slippage=a.entry_slip, stop_slippage=a.stop_slip,
                   volume_min=a.min_lot, volume_max=a.max_lot, volume_step=a.lot_step,
                   tick_size=a.tick_size, margin_per_lot=a.margin_per_lot)
    if not (cfg.initial_capital > 0 and 0 < cfg.risk_fraction <= 0.02 and
            cfg.contract_size > 0 and cfg.tick_size > 0 and cfg.volume_step > 0 and
            cfg.volume_min > 0 and cfg.volume_max >= cfg.volume_min and
            cfg.point_size > 0 and cfg.commission_roundtrip_per_lot >= 0 and
            cfg.entry_slippage >= 0 and cfg.stop_slippage >= 0 and cfg.assumed_spread_price >= 0
            and cfg.margin_per_lot >= 0):
        raise ValueError("Invalid or unsafe configuration")
    bars, quality = load_candles(a.csv, cfg, table=a.table,
                                 symbol=a.symbol, timeframe_name=a.timeframe_name)
    results = run_comparison(bars, cfg, a.out, a.evaluation, a.holdout_fraction)
    results["data_quality"] = quality
    (Path(a.out)/"report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nDATA QUALITY:", json.dumps(quality, indent=2, ensure_ascii=False))
    print(f"\nEVALUATION={a.evaluation} | chronological split={results['split_time']}")
    print("Setups: sweep | sweep_mss | sweep_mss_fvg | filtered")
    for name, r in results["results"].items():
        print(f"{name:17s} trades={r['trades']:4} win={str(r['win_rate_pct']):>6}% "
              f"PF={str(r['profit_factor']):>7} AvgR={str(r['avg_r']):>7} "
              f"Net=${r['net_pnl']:>10.2f} MaxDD={r['max_drawdown_pct']}%")
    print(f"\nCSV trade logs, equity curves, signals and report.json saved under: {a.out}")
    print("CAUTION: Bid/mid approximation, bar-level SL-first, estimated execution, research only.")
    print("WARN:  <100 closed trades per setup = weak sample. 95% Wilson intervals in report.json.")
    if cfg.margin_per_lot == 0:
        print("WARN: No broker margin data provided; margin feasibility was NOT validated.")

if __name__ == "__main__":
    cli()
