"""Explainable seven-layer signal/risk pipeline. FAIL CLOSED. No execution imports.
Research-only examples do NOT automatically enter this live pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
from math import isfinite, floor
import hashlib,json

@dataclass(frozen=True)
class Quote:
    bid:float; ask:float; timestamp_utc:datetime

@dataclass(frozen=True)
class BrokerSymbol:
    symbol_id:int
    symbol_name:str
    min_volume:int     # cTrader protocol units: 1/100 of underlying unit
    step_volume:int
    max_volume:int
    lot_size:int        # also in protocol units; never assume 0.01 lot translates to fixed volume
    digits:int=2
    trade_allowed:bool=True

@dataclass(frozen=True)
class Candidate:
    strategy_id:str; symbol_name:str; timeframe:str
    signal_bar_end_utc:datetime; side:str; stop_price:float; target_price:float
    pivot_confirmed:bool; source_data_ok:bool; market_regime:str
    signals:dict[str,bool]=field(default_factory=dict)

@dataclass(frozen=True)
class Account:
    account_id:int; is_live:bool; equity_usd:float; day_start_equity_usd:float
    open_positions:int=0
    currency:str='USD'

@dataclass(frozen=True)
class Decision:
    status:str; reason:str; strategy_id:str; grade:str
    evidence:dict; order:Optional[dict]=None

def _utc(dt):
    if dt.tzinfo is None or dt.utcoffset() is None:raise ValueError('UTC timezone-aware timestamp required')
    return dt.astimezone(timezone.utc)

def assess(candidate:Candidate,quote:Quote,account:Account,symbol:BrokerSymbol,config:dict,now:datetime)->Decision:
    checks={};score=0
    def fail(why):return Decision('REJECT',why,candidate.strategy_id,'D',dict(checks))
    if account.is_live:return fail('LIVE_ACCOUNT_NOT_ALLOWED')
    if account.currency!='USD':return fail('ACCOUNT_CURRENCY_CONVERSION_NOT_AVAILABLE')
    if symbol.symbol_name != candidate.symbol_name:return fail('SYMBOL_MISMATCH')
    if candidate.strategy_id not in config.get('approved_strategy_ids',[]):return fail('STRATEGY_UNAPPROVED')
    if candidate.strategy_id not in config.get('enabled_strategy_ids', [candidate.strategy_id]):return fail('STRATEGY_DISABLED')
    if candidate.strategy_id in config.get('research_only_strategy_ids',[]):return fail('STRATEGY_RESEARCH_ONLY')
    if not candidate.pivot_confirmed or not candidate.source_data_ok:return fail('UNCONFIRMED_OR_BAD_DATA')
    if candidate.side not in ('BUY','SELL'):return fail('INVALID_SIDE')
    try:
        signal_time=_utc(candidate.signal_bar_end_utc);quote_time=_utc(quote.timestamp_utc);now=_utc(now)
    except ValueError as e:return fail(str(e))
    if now<signal_time or signal_time>quote_time:return fail('FUTURE_SIGNAL')
    if not (0<=(now-quote_time).total_seconds()<=config['max_price_age_sec']):return fail('STALE_QUOTE')
    if not (0<=(now-signal_time).total_seconds()<=max(60,300 if candidate.timeframe=='M5' else 900)):return fail('STALE_SIGNAL')
    if not (isfinite(quote.bid) and isfinite(quote.ask) and 0<quote.bid<quote.ask):return fail('INVALID_QUOTE')
    spread=quote.ask-quote.bid;checks['spread']=round(spread,6)
    if spread>config['max_spread_price_usd']:return fail('SPREAD_TOO_WIDE')
    entry=quote.ask if candidate.side=='BUY' else quote.bid
    side=1 if candidate.side=='BUY' else -1
    risk=side*(entry-candidate.stop_price)
    reward=side*(candidate.target_price-entry)
    if not all(map(isfinite,[risk,reward])) or risk<=0 or reward<=0:return fail('INVALID_SL_TP')
    checks['risk_price']=round(risk,5);checks['rr']=round(reward/risk,3)
    if risk>config['max_sl_price_usd']:return fail('STOP_OVER_POLICY_CAP')
    if reward/risk<config['min_rr']:return fail('RR_TOO_SMALL')
    if not symbol.trade_allowed or symbol.min_volume<=0 or symbol.step_volume<=0:return fail('SYMBOL_NOT_TRADEABLE')
    if account.open_positions>=config['max_positions']:return fail('MAX_POSITIONS')
    if account.equity_usd<=0 or account.day_start_equity_usd<=0:return fail('INVALID_EQUITY')
    dd=(account.day_start_equity_usd-account.equity_usd)/account.day_start_equity_usd*100
    if dd>=config['daily_loss_limit_pct']:return fail('DAILY_LOSS_CIRCUIT_BREAKER')
    # 1 protocol volume unit = 0.01 underlying units. Risk measured in price difference * underlying units for XAUUSD account USD.
    budget=account.equity_usd*config['risk_pct_per_trade']/100
    max_protocol=100*budget/risk
    volume=floor((max_protocol-symbol.min_volume)/symbol.step_volume)*symbol.step_volume+symbol.min_volume if max_protocol>=symbol.min_volume else 0
    ceiling=symbol.min_volume+((symbol.max_volume-symbol.min_volume)//symbol.step_volume)*symbol.step_volume
    volume=min(volume,ceiling)
    if volume<symbol.min_volume:return fail('MIN_VOLUME_EXCEEDS_RISK_BUDGET')
    worst_risk=risk*volume/100
    if worst_risk>budget+1e-9:return fail('RISK_ROUNDING_OVER_BUDGET')
    weights={'structure':20,'liquidity':20,'displacement':15,'higher_timeframe':15,'session':10,'entry_confirmation':20}
    score=sum(v for k,v in weights.items() if candidate.signals.get(k,False))
    if not candidate.pivot_confirmed:return fail('UNCONFIRMED_PIVOT')
    grade='A' if score>=75 else 'B' if score>=55 else 'C'
    checks.update({'score':score,'regime':candidate.market_regime,'worst_risk_usd':round(worst_risk,4),'budget_usd':round(budget,4)})
    if score<75:return Decision('SHADOW','INSUFFICIENT_CONFLUENCE_FOR_DEMO',candidate.strategy_id,grade,checks)
    raw={'strategy_id':candidate.strategy_id,'signal_bar_end_utc':signal_time.isoformat(),'symbol_id':symbol.symbol_id,'side':candidate.side}
    oid=hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()[:32]
    order={'client_order_id':'GS-'+oid,'ctidTraderAccountId':account.account_id,'symbolId':symbol.symbol_id,'side':candidate.side,'volume_cent_units':volume,'entry_quote':entry,'stop_price':candidate.stop_price,'target_price':candidate.target_price,'risk_price':round(risk,5),'worst_risk_usd':round(worst_risk,4)}
    if config.get('mode')!='DEMO' or config.get('allow_demo_order') is not True:
        return Decision('SHADOW','DEMO_DISABLED_BY_CONFIG',candidate.strategy_id,grade,checks,order)
    return Decision('DEMO_READY','BROKER_CONFIRMATION_REQUIRED',candidate.strategy_id,grade,checks,order)
