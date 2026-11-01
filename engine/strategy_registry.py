"""User toggles: strategies are ENABLED for paper signals by default,
not authorized for broker execution. Atomic config writes; CLI can disable any strategy.
"""
from __future__ import annotations
from pathlib import Path
import json, os, tempfile
from strategies.catalog import SPECS
ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'config/strategy_switches.json'

def defaults():
    return {'schema':1,'market':'XAUUSD','execution_mode':'DEMO',
      'strategies':{sid:{'enabled':True,'allow_demo':True,'research_only':False,'stop_cap':spec.stop_cap,
        'timeframe':spec.timeframe,'source':spec.source,'source_type':spec.source_type}
        for sid,spec in sorted(SPECS.items())}}

def read(path=PATH):
    path=Path(path)
    if not path.exists():return defaults()
    config=json.loads(path.read_text(encoding='utf8'))
    if config.get('execution_mode') not in ('SHADOW','DEMO'):
        raise ValueError('Only SHADOW/DEMO allowed')
    expected=set(SPECS)
    if set(config.get('strategies',{})) != expected:
        raise ValueError('Strategy registry does not match installed generators')
    for sid,v in config['strategies'].items():
        if type(v.get('enabled')) is not bool or type(v.get('allow_demo')) is not bool:
            raise ValueError('Invalid strategy switch '+sid)
        if v['allow_demo'] and v.get('research_only', True):
            raise ValueError('Research-only strategy cannot be allowed demo execution: '+sid)
    return config

def save(config,path=PATH):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    read_temp=dict(config)
    if set(read_temp['strategies'])!=set(SPECS): raise ValueError('Invalid registry ids')
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False,encoding='utf8') as f:
        json.dump(config,f,ensure_ascii=False,indent=2);f.write('\n');name=f.name
    os.replace(name,path)

def toggle(sid,enabled,path=PATH):
    cfg=read(path)
    if sid not in SPECS:raise ValueError('Unknown strategy '+sid)
    cfg['strategies'][sid]['enabled']=bool(enabled)
    save(cfg,path)
    return cfg['strategies'][sid]

def active(path=PATH):
    conf=read(path)
    return {sid:spec for sid,spec in SPECS.items() if conf['strategies'][sid]['enabled']}
