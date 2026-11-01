"""Complete official browser OAuth; write tokens privately, never print them."""
from urllib.parse import urlparse,parse_qs
from pathlib import Path
import argparse,os
from ctrader.local_secrets import load_env,save_tokens
from ctrader.credentials import exchange_code
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description='Finish cTrader OAuth via a redirect URL (not a secret printed to console)')
    p.add_argument('--redirect-url',required=True,help='URL you saw after consenting')
    p.add_argument('--registered-redirect-uri',required=True,help='exact OAuth redirect URI in cTrader app')
    a=p.parse_args();load_env(ROOT/'.env')
    codes=parse_qs(urlparse(a.redirect_url).query).get('code',[])
    if len(codes)!=1:raise SystemExit('No unique OAuth authorization code in redirect URL')
    for name in ('CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET'):
        if not os.environ.get(name):raise SystemExit('Missing '+name+' in .env')
    result=exchange_code(os.environ['CTRADER_CLIENT_ID'],os.environ['CTRADER_CLIENT_SECRET'],a.registered_redirect_uri,codes[0])
    save_tokens(ROOT/'.env',result)
    print('DEMO_OAUTH_TOKENS_SAVED_PRIVATELY')
if __name__=='__main__':main()
