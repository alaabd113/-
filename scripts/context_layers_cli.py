"""Owner-side switch for OPTIONAL SMC and volume-profile pretrade gates. Not a broker client."""
import argparse,json
from pathlib import Path
from engine.context_integration import SETTINGS,read_settings

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('command',choices=['status','enable','disable']);p.add_argument('layer',nargs='?',choices=['smc','vp'])
    p.add_argument('--file',type=Path,default=SETTINGS)
    a=p.parse_args(argv)
    cfg=read_settings(a.file)
    if a.command=='status':print(json.dumps(cfg,ensure_ascii=False,indent=2));return
    if a.layer is None:p.error('enable/disable requires smc or vp')
    cfg[f'{a.layer}_gate']=(a.command=='enable')
    temp=a.file.with_suffix('.json.tmp');temp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf8');temp.replace(a.file)
    print(f'{a.layer}_gate={cfg[f"{a.layer}_gate"]}')
if __name__=='__main__':main()
