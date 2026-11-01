import argparse,os
from ctrader.credentials import authorization_url
p=argparse.ArgumentParser();p.add_argument('--redirect-uri',required=True);p.add_argument('--scope',choices=['accounts','trading'],default='accounts');q=p.parse_args();v=os.getenv('CTRADER_CLIENT_ID')
if not v:raise SystemExit('Set CTRADER_CLIENT_ID environment variable')
print(authorization_url(v,q.redirect_uri,q.scope))
