"""Separate, opt-in decision context. Never silently changes frozen PO3 logic.
May prevent a demo candidate when explicitly configured by operator.
"""
import json
from pathlib import Path
from dataclasses import replace
from engine.smc_context import latest
from engine.volume_profile import compute
from engine.signal_hub import closed_only

SETTINGS=Path(__file__).resolve().parents[1]/'config/context_layers.json'

def read_settings(path=SETTINGS):
    cfg=json.loads(Path(path).read_text(encoding='utf8'))
    for key in ('smc_gate','vp_gate'):
        if not isinstance(cfg.get(key),bool):raise ValueError('Invalid context gate setting '+key)
    return cfg

def apply(candidates,frames,cfg=None):
    cfg=read_settings() if cfg is None else cfg
    annotated=[]; audit=[]
    cache={}
    for c in candidates:
        tf={'M1':'1min','M5':'5min','M15':'15min','M30':'30min','H1':'1h','H4':'4h','D1':'1day'}.get(c.timeframe)
        if tf not in frames: audit.append({'strategy':c.strategy_id,'reason':'MISSING_FRAME'});continue
        key=(tf,c.signal_bar_end_utc)
        if key not in cache:
            try:
                # CRITICAL: current raw broker frames may include an INCOMPLETE forming candle.
                # Truncate to bars CLOSED as of this candidate's signal, not "now".
                df=closed_only(frames[tf],tf,c.signal_bar_end_utc)
                context=latest(df)
                try:vp=compute(df,lookback=int(cfg.get('vp_lookback',200))).asdict()
                except ValueError as exc:vp={'status':'UNAVAILABLE','reason':str(exc)}
                cache[key]=(context,vp,float(df.close.iloc[-1]))
            except Exception as exc:
                cache[key]=({'status':'UNAVAILABLE','reason':str(exc)}, {'status':'UNAVAILABLE','reason':'CONTEXT_DATA_INVALID'},None)
        context,vp,last_close=cache[key];side=1 if c.side=='BUY' else -1
        smc_agrees=bool('bias' in context and context['bias']==side and context.get('last_swing_high') is not None and context.get('last_swing_low') is not None)
        vp_available='poc' in vp
        vp_agrees=vp_available and (last_close>=vp['poc'] if side==1 else last_close<=vp['poc'])
        audit.append({'strategy':c.strategy_id,'smc':context,'vp':vp,'smc_agrees':smc_agrees,'vp_agrees':vp_agrees})
        if cfg.get('smc_gate',False) and not smc_agrees:continue
        if cfg.get('vp_gate',False) and not vp_agrees:continue
        # No re-scoring, no changing existing evidence unless explicitly gated.
        annotated.append(c)
    return annotated,audit
