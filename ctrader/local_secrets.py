"""Load operator's private .env; never show token values in logs."""
from __future__ import annotations
from pathlib import Path
import os,tempfile

def load_env(path='.env'):
    path=Path(path)
    if not path.exists(): return False
    for raw in path.read_text(encoding='utf8').splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        key,val=line.split('=',1)
        key=key.strip();val=val.strip().strip('"').strip("'")
        if key.startswith(('CTRADER_','GOLD_TELEGRAM_')) and key.replace('_','').isalnum():
            os.environ[key]=val
    return True

def save_tokens(path,tokens):
    """Atomic token rotation, restrictive permissions; preserve unrelated operator keys."""
    path=Path(path); values={}
    if path.exists():
        for line in path.read_text(encoding='utf8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1);values[k.strip()]=v
    if not tokens.get('accessToken') or not tokens.get('refreshToken'):
        raise ValueError('Missing rotated tokens')
    values['CTRADER_ACCESS_TOKEN']=tokens['accessToken']
    values['CTRADER_REFRESH_TOKEN']=tokens['refreshToken']
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=str(path.parent),prefix='.token-',text=True)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf8') as stream:
            for k,v in values.items():
                if any(ch in str(v) for ch in ('\n','\r','\0')):
                    raise ValueError('Unusual character in environment value: '+k)
                stream.write(f'{k}={v}\n')
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
    os.environ['CTRADER_ACCESS_TOKEN']=tokens['accessToken']
    os.environ['CTRADER_REFRESH_TOKEN']=tokens['refreshToken']
