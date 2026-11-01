"""OAuth convenience: never print, log, or commit access/refresh tokens."""
from urllib.parse import urlencode
from urllib.request import urlopen
import json,os

def authorization_url(client_id,redirect_uri,scope='accounts'):
 if scope not in ('accounts','trading'):raise ValueError('only official scopes')
 return 'https://id.ctrader.com/my/settings/openapi/grantingaccess/?'+urlencode({'client_id':client_id,'redirect_uri':redirect_uri,'scope':scope,'product':'web'})

def exchange_code(client_id,client_secret,redirect_uri,code):
 params=urlencode({'grant_type':'authorization_code','client_id':client_id,'client_secret':client_secret,'redirect_uri':redirect_uri,'code':code})
 with urlopen('https://openapi.ctrader.com/apps/token?'+params,timeout=12) as resp:r=json.load(resp)
 if not r.get('accessToken') or not r.get('refreshToken'):raise RuntimeError('token exchange failed')
 return r # do not print returned object; store in secure secret vault

def refresh_token(client_id,client_secret,refresh_token):
 params=urlencode({'grant_type':'refresh_token','client_id':client_id,'client_secret':client_secret,'refresh_token':refresh_token})
 with urlopen('https://openapi.ctrader.com/apps/token?'+params,timeout=12) as resp:r=json.load(resp)
 if not r.get('accessToken'):raise RuntimeError('refresh failed')
 return r
