import sys,subprocess
from pathlib import Path
r=Path(__file__).resolve().parents[1]
for cmd in ([sys.executable,'-m','compileall','-q',str(r/'engine'),str(r/'ctrader'),str(r/'research'),str(r/'scripts'),str(r/'strategies')],
            [sys.executable,'-m','unittest','discover','-s',str(r/'tests'),'-v'],
            [sys.executable,'-m','scripts.check_configuration']):
 print('RUN:',cmd,flush=True);x=subprocess.run(cmd,cwd=r)
 if x.returncode:raise SystemExit(x.returncode)
print('ALL_OFFLINE_CHECKS_PASS')
