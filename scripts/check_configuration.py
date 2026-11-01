import json,os
from pathlib import Path
r=Path(__file__).resolve().parents[1]
c=json.loads((r/'config/settings.json').read_text())
print('Mode:',c['mode'],'Demo send enabled:',c['allow_demo_order'],'Live send enabled:',c['allow_live_order'])
print('Data:',', '.join(p.name for p in sorted((r/'data/ctrader').glob('*ctrader.csv'))))
print('Optional cTrader vars set:',{k:bool(os.getenv(k)) for k in ['CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN','CTRADER_ACCOUNT_ID','CTRADER_SYMBOL_ID']})
if c.get('allow_live_order'):raise SystemExit('FAIL: live trading must remain disabled')
