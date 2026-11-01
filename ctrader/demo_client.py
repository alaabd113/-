"""cTrader Open API DEMO-only SDK transport. Offline-tested message logic; live auth NOT tested.
Usage: `python -m ctrader.demo_client --task bars --symbol-id 123 --period M5 --from-ms ... --to-ms ...`
No order submission is wired to CLI by default. The V7 order helper is DISABLED. Use ctrader.demo_worker for protected orders.
Requires `pip install ctrader-open-api`. No market host exists anywhere in this module.
"""
from __future__ import annotations
import argparse,os,json,sys,time,csv
from pathlib import Path
from datetime import datetime,timezone
from .protocol import decode_trendbar,relative_protection
from engine.intent_store import IntentStore

HOST='demo.ctraderapi.com';PORT=5035

class DemoClient:
 def __init__(self,task,account_id,token,client_id,client_secret,symbol_id=0,period='M5',from_ms=0,to_ms=0,count=500,output='data/ctrader_live_bars.csv'):
  if task not in ('account','symbols','bars','quotes','reconcile'):
   raise ValueError('No live-order task on CLI; order operation is separately gated')
  self.task=task;self.account_id=int(account_id);self.token=token;self.client_id=client_id;self.client_secret=client_secret
  self.symbol_id=int(symbol_id);self.period=period;self.from_ms=int(from_ms);self.to_ms=int(to_ms);self.count=int(count);self.output=Path(output)
  self.is_demo_authorized=False;self.latest_quote={};self.latest_symbol_meta=None;self._account_verified=False;self._timeout=45;self._sent_orders=0
 def start(self):
  try:
   from ctrader_open_api import Client,Protobuf,TcpProtocol
   from ctrader_open_api.messages import OpenApiMessages_pb2 as oa
   from ctrader_open_api.messages import OpenApiModelMessages_pb2 as om
   from ctrader_open_api.messages import OpenApiCommonMessages_pb2 as cm
   from twisted.internet import reactor
  except ImportError as e:raise RuntimeError('Install official SDK: pip install ctrader-open-api') from e
  self.oa=oa;self.om=om;self.cm=cm;self.P=Protobuf;self.reactor=reactor
  # Hard-coded demo host. No live endpoint, no user-provided host override.
  client=Client(HOST,PORT,TcpProtocol);self.client=client
  client.setConnectedCallback(self.on_connect)
  client.setDisconnectedCallback(self.on_disconnect)
  client.setMessageReceivedCallback(self.on_message)
  client.startService()
  reactor.callLater(self._timeout,self.stop)
  reactor.callLater(10,self._heartbeat)
  reactor.run()
 def _heartbeat(self):
  if not self.reactor.running:return
  try:
   self.send(self.cm.ProtoHeartbeatEvent())
  except (AttributeError,RuntimeError):
   print('HEARTBEAT_SDK_UNAVAILABLE',file=sys.stderr)
  if self.reactor.running:self.reactor.callLater(10,self._heartbeat)
 def send(self,req):
  return self.client.send(req).addErrback(lambda failure:print('REQUEST_ERROR',str(failure).splitlines()[0][:180],file=sys.stderr))
 def on_connect(self,client):
  request=self.oa.ProtoOAApplicationAuthReq();request.clientId=self.client_id;request.clientSecret=self.client_secret;self.send(request)
 def on_disconnect(self,client,reason):print('DISCONNECT',str(reason)[:80],file=sys.stderr)
 def stop(self):
  if self.reactor.running:self.reactor.stop()
 def on_message(self,client,message):
  try:
   obj=self.P.extract(message);t=type(obj).__name__
   if t in ('ProtoOAApplicationAuthRes',):
    r=self.oa.ProtoOAGetAccountListByAccessTokenReq();r.accessToken=self.token;self.send(r)
   elif t=='ProtoOAGetAccountListByAccessTokenRes':
    found=[a for a in obj.ctidTraderAccount if int(a.ctidTraderAccountId)==self.account_id]
    if not found:raise ValueError('account not authorized in token')
    if bool(found[0].isLive):raise ValueError('live account denied; connect a cTrader demo account')
    self._account_verified=True
    r=self.oa.ProtoOAAccountAuthReq();r.ctidTraderAccountId=self.account_id;r.accessToken=self.token;self.send(r)
   elif t=='ProtoOAAccountAuthRes':
    if not self._account_verified:raise ValueError('account authentication out of order')
    self.is_demo_authorized=True;print('AUTHORIZED_DEMO_ACCOUNT',self.account_id)
    self.after_auth()
   elif t=='ProtoOASymbolByIdRes':
    found=[s for s in obj.symbol if int(s.symbolId)==self.symbol_id]
    if found:
     s=found[0];self.latest_symbol_meta={'symbol_id':int(s.symbolId),'min_volume':int(s.minVolume),'max_volume':int(s.maxVolume),'step_volume':int(s.stepVolume),'lot_size':int(s.lotSize),'digits':int(s.digits),'trade_allowed':int(s.tradingMode)==0,'is_demo_verified':self._account_verified}
     print('BROKER_SYMBOL_METADATA_RECEIVED',self.symbol_id)
     if self.task=='quotes' and 'bid' in self.latest_quote and 'ask' in self.latest_quote:
      print(json.dumps(self.latest_quote));self.stop()
   elif t=='ProtoOASymbolsListRes':
    print(json.dumps([{'symbolId':int(s.symbolId),'symbolName':s.symbolName} for s in obj.symbol],ensure_ascii=False))
    self.stop()
   elif t=='ProtoOAGetTrendbarsRes':
    self.save_bars(obj);self.stop()
   elif t=='ProtoOASpotEvent':
    if self.symbol_id and int(obj.symbolId)!=self.symbol_id:return
    if getattr(obj,'bid',0):self.latest_quote['bid']=float(obj.bid)/100000.
    if getattr(obj,'ask',0):self.latest_quote['ask']=float(obj.ask)/100000.
    ts=int(getattr(obj,'timestamp',0) or 0)  # no invented quote time: 0 blocks trading
    self.latest_quote['timestamp_ms']=ts
    if self.task=='quotes' and self.latest_symbol_meta is not None and 'bid' in self.latest_quote and 'ask' in self.latest_quote:
     print(json.dumps(self.latest_quote));self.stop()
   elif t=='ProtoOAExecutionEvent':
    # Acknowledgement is not assumed from client.send(): only server events may confirm.
    oid=str(getattr(getattr(obj,'order',None),'clientOrderId',''))
    if oid:
     try:
      status=str(getattr(obj,'executionType',''))
      # Explicitly distinguish notifications from broker-confirmed fills.
      if status == str(self.om.ProtoOAExecutionType.Value('ORDER_FILLED')):
       IntentStore(getattr(self,'ledger_path','runtime/intent_ledger.sqlite')).update(oid,'FILLED')
      else:
       print('EXECUTION_UNRESOLVED_RECONCILE_REQUIRED',oid[:16],file=sys.stderr)
     except (KeyError,ValueError,AttributeError):
      print('EXECUTION_STATUS_NOT_CONFIRMED',oid[:16],file=sys.stderr)
    print('EXECUTION_EVENT_RECEIVED',bool(oid))
   elif t=='ProtoOAReconcileRes':
    print(json.dumps({'open_positions':len(obj.position),'pending_orders':len(obj.order)},ensure_ascii=False));self.stop()
   elif t=='ProtoOATraderRes':
    print('TRADER_DETAILS_RETURNED; no secrets printed');self.stop()
   elif t in ('ProtoOAErrorRes','ProtoErrorRes','ProtoOAOrderErrorEvent'):
    print('SERVER_ERROR',str(obj)[:400],file=sys.stderr);self.stop()
  except Exception as e:
   print('PROTOCOL_ERROR',str(e)[:260],file=sys.stderr);self.stop()
 def after_auth(self):
  if self.task=='account':
   r=self.oa.ProtoOATraderReq();r.ctidTraderAccountId=self.account_id;self.send(r)
  elif self.task=='symbols':
   r=self.oa.ProtoOASymbolsListReq();r.ctidTraderAccountId=self.account_id;self.send(r)
  elif self.task=='bars':
   if self.period not in ('M1','M5','M15','M30','H1','H4','D1') or self.symbol_id<=0:raise ValueError('period/symbol invalid')
   if self.from_ms<1 or self.to_ms<=self.from_ms or self.count<1 or self.count>1000:raise ValueError('bad history window/count')
   r=self.oa.ProtoOAGetTrendbarsReq();r.ctidTraderAccountId=self.account_id;r.symbolId=self.symbol_id
   r.period=self.om.ProtoOATrendbarPeriod.Value(self.period)
   r.fromTimestamp=self.from_ms;r.toTimestamp=self.to_ms;r.count=self.count;self.send(r)
  elif self.task=='quotes':
   m=self.oa.ProtoOASymbolByIdReq();m.ctidTraderAccountId=self.account_id;m.symbolId.append(self.symbol_id);self.send(m)
   r=self.oa.ProtoOASubscribeSpotsReq();r.ctidTraderAccountId=self.account_id;r.symbolId.append(self.symbol_id);r.subscribeToSpotTimestamp=True;self.send(r)
  elif self.task=='reconcile':
   r=self.oa.ProtoOAReconcileReq();r.ctidTraderAccountId=self.account_id;self.send(r)
 def save_bars(self,obj):
  # The symbol's digits may be unavailable during bars task: preserve API 1e-5 precision.
  digits=(int(self.latest_symbol_meta['digits']) if self.latest_symbol_meta else 5)
  rows=[decode_trendbar(bar,digits=digits) for bar in obj.trendbar]
  self.output.parent.mkdir(parents=True,exist_ok=True)
  # Upsert by bar timestamp, never silently overwrite historical records from another broker.
  identity={'account_id':self.account_id,'symbol_id':self.symbol_id,'period':self.period,'price_source':'CTRADER_OPEN_API_DEMO'}
  sidecar=self.output.with_name(self.output.name+'.meta.json')
  if self.output.exists():
   if not sidecar.exists():raise ValueError('Existing CSV missing symbol/account identity sidecar; refuse merge')
   if json.loads(sidecar.read_text(encoding='utf8'))!=identity:
    raise ValueError('CSV identity mismatch; refuse mixing symbols/brokers/timeframes')
  old=[]
  if self.output.exists():
   with self.output.open(encoding='utf8') as f:old=list(csv.DictReader(f))
  merged={r['timestamp_utc']:r for r in old}
  for row in rows:merged[row['timestamp_utc']]=row
  with self.output.open('w',newline='',encoding='utf8') as f:
   w=csv.DictWriter(f,fieldnames=['timestamp_utc','open','high','low','close','volume']);w.writeheader();w.writerows([merged[k] for k in sorted(merged)])
  sidecar.write_text(json.dumps(identity,sort_keys=True),encoding='utf8')
  print(json.dumps({'bars_received':len(rows),'stored':len(merged),'path':str(self.output),'has_more':bool(obj.hasMore)}))

# Not exposed in CLI. Call through manually reviewed app with broker metadata + real quote.
def send_ready_demo_order(*args, **kwargs):
    """Deprecated V7 path: intentionally disabled, use ctrader.demo_worker exclusively.

    Prevents a second lower-assurance order route from bypassing the V8 broker
    snapshot, market-range slippage, persisted daily baseline and strategy switches.
    """
    return False,'LEGACY_ORDER_ROUTE_DISABLED_USE_DEMO_WORKER'

def main():
 a=argparse.ArgumentParser(description='cTrader DEMO read-only CLI. No order command.')
 a.add_argument('--task',choices=['account','symbols','bars','quotes','reconcile'],required=True)
 a.add_argument('--symbol-id',type=int,default=0);a.add_argument('--period',default='M5');a.add_argument('--from-ms',type=int,default=0);a.add_argument('--to-ms',type=int,default=0);a.add_argument('--count',type=int,default=500);a.add_argument('--output',default='data/ctrader_live_bars.csv')
 x=a.parse_args();needs=['CTRADER_ACCOUNT_ID','CTRADER_ACCESS_TOKEN','CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET']
 if any(not os.environ.get(k) for k in needs):raise SystemExit('Missing cTrader env secrets; consult docs/CTRADER_AR.md')
 c=DemoClient(x.task,os.environ['CTRADER_ACCOUNT_ID'],os.environ['CTRADER_ACCESS_TOKEN'],os.environ['CTRADER_CLIENT_ID'],os.environ['CTRADER_CLIENT_SECRET'],x.symbol_id,x.period,x.from_ms,x.to_ms,x.count,x.output);c.start()
if __name__=='__main__':main()
