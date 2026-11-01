"""cTrader DEMO-only one-shot SDK worker.

Designed to be launched by scripts.run_demo. Every submit reconnects and independently
checks the token's DEMO account, symbol, real Bid/Ask, account currency and
open positions. It reserves the order ID in SQLite BEFORE sending.

The SDK/network integration requires an actual Spotware demo OAuth token. We
exercise protocol/state transitions in tests with fake messages; this file
cannot honestly be certified against a broker without that account.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace

from engine.pipeline import Candidate, Account, Quote, BrokerSymbol, assess
from engine.intent_store import IntentStore
from engine.strategy_registry import read as read_switches
from ctrader.protocol import relative_protection

HOST, PORT = 'demo.ctraderapi.com', 5035

class DemoWorker:
    def __init__(self, task: str, symbol_id: int, intent_path: str | None = None,
                 ledger_path: str = 'runtime/demo_intents.sqlite'):
        if task not in ('snapshot', 'submit'):
            raise ValueError('Unsupported task')
        self.task, self.symbol_id = task, int(symbol_id)
        self.intent_path, self.ledger_path = intent_path, ledger_path
        self.account_id = int(os.environ['CTRADER_ACCOUNT_ID'])
        self.token = os.environ['CTRADER_ACCESS_TOKEN']
        self.client_id = os.environ['CTRADER_CLIENT_ID']
        self.client_secret = os.environ['CTRADER_CLIENT_SECRET']
        if self.account_id <= 0 or self.symbol_id <= 0:
            raise ValueError('Invalid IDs')
        self.demo_verified = False
        self.fields = {}
        self.parts = set()
        self.saw_order = False
        self.finish_status = None
        self._result = None

    def run(self):
        try:
            from ctrader_open_api import Client, Protobuf, TcpProtocol
            from ctrader_open_api.messages import OpenApiMessages_pb2 as oa
            from ctrader_open_api.messages import OpenApiModelMessages_pb2 as om
            from ctrader_open_api.messages import OpenApiCommonMessages_pb2 as cm
            from twisted.internet import reactor
        except ImportError as exc:
            raise RuntimeError('SDK missing: pip install -r requirements-ctrader.txt') from exc
        self.oa, self.om, self.cm, self.pb, self.reactor = oa, om, cm, Protobuf, reactor
        self.client = Client(HOST, PORT, TcpProtocol)
        self.client.setConnectedCallback(self.connected)
        self.client.setDisconnectedCallback(self.disconnected)
        self.client.setMessageReceivedCallback(self.received)
        self.client.startService()
        reactor.callLater(35, self.expire)
        reactor.callLater(10, self.heartbeat)
        reactor.run()
        if self.finish_status is None:
            raise RuntimeError('SDK worker stopped without result')
        if self.finish_status != 'OK':
            raise RuntimeError(self.finish_status)
        return self._result

    def send(self, message):
        df = self.client.send(message)
        def on_error(failure):
            self.complete('SEND_FAILURE')
            return None
        df.addErrback(on_error)
        return df

    def heartbeat(self):
        if not self.reactor.running: return
        try: self.send(self.cm.ProtoHeartbeatEvent())
        except Exception: self.complete('HEARTBEAT_FAILED'); return
        self.reactor.callLater(10, self.heartbeat)

    def connected(self, _client):
        req = self.oa.ProtoOAApplicationAuthReq()
        req.clientId = self.client_id
        req.clientSecret = self.client_secret
        self.send(req)

    def disconnected(self, _client, _reason):
        if self.finish_status is None: self.complete('DISCONNECTED_UNCERTAIN')

    def complete(self, status, result=None):
        if self.finish_status is not None: return
        self.finish_status, self._result = status, result
        if hasattr(self, 'reactor') and self.reactor.running:
            self.reactor.callLater(0, self.reactor.stop)

    def expire(self):
        self.complete('TIMEOUT_UNCERTAIN' if self.saw_order else 'TIMEOUT_NO_RESPONSE')

    def _request(self, cls, **fields):
        msg = getattr(self.oa, cls)()
        for k, v in fields.items(): setattr(msg, k, v)
        self.send(msg)

    def after_account_auth(self):
        aid = self.account_id
        for typ in ('ProtoOATraderReq', 'ProtoOAAssetListReq', 'ProtoOASymbolsListReq',
                    'ProtoOAReconcileReq'):
            self._request(typ, ctidTraderAccountId=aid)
        q = self.oa.ProtoOASymbolByIdReq()
        q.ctidTraderAccountId = aid
        q.symbolId.append(self.symbol_id)
        self.send(q)
        q = self.oa.ProtoOASubscribeSpotsReq()
        q.ctidTraderAccountId = aid
        q.symbolId.append(self.symbol_id)
        q.subscribeToSpotTimestamp = True
        self.send(q)

    def received(self, _client, message):
        try:
            obj = self.pb.extract(message)
            name = type(obj).__name__
            if name == 'ProtoOAApplicationAuthRes':
                self._request('ProtoOAGetAccountListByAccessTokenReq', accessToken=self.token)
            elif name == 'ProtoOAGetAccountListByAccessTokenRes':
                accounts = [a for a in obj.ctidTraderAccount
                            if int(a.ctidTraderAccountId) == self.account_id]
                if len(accounts) != 1: raise ValueError('DEMO_ACCOUNT_NOT_AUTHORIZED')
                if bool(accounts[0].isLive): raise ValueError('LIVE_ACCOUNT_REFUSED')
                self.demo_verified = True
                self._request('ProtoOAAccountAuthReq', ctidTraderAccountId=self.account_id,
                              accessToken=self.token)
            elif name == 'ProtoOAAccountAuthRes':
                if not self.demo_verified: raise ValueError('ACCOUNT_NOT_VERIFIED')
                self.after_account_auth()
            elif name == 'ProtoOATraderRes':
                a = obj.trader
                if int(a.ctidTraderAccountId) != self.account_id: raise ValueError('WRONG_TRADER')
                self.fields['balance'] = float(a.balance) / (10 ** int(a.moneyDigits))
                self.fields['deposit_asset_id'] = int(a.depositAssetId)
                self.fields['full_access'] = int(a.accessRights) == 0
                self.fields['limited_risk'] = bool(a.isLimitedRisk)
                self.parts.add('trader')
            elif name == 'ProtoOAAssetListRes':
                self.fields['asset_map'] = {int(a.assetId):str(a.name).upper() for a in obj.asset}
                self.parts.add('assets')
            elif name == 'ProtoOASymbolsListRes':
                matches = [s for s in obj.symbol if int(s.symbolId)==self.symbol_id]
                if len(matches)!=1: raise ValueError('SYMBOL_NOT_ON_ACCOUNT')
                self.fields['symbol_name'] = matches[0].symbolName
                self.parts.add('name')
            elif name == 'ProtoOASymbolByIdRes':
                matches = [s for s in obj.symbol if int(s.symbolId)==self.symbol_id]
                if len(matches)!=1: raise ValueError('SYMBOL_DETAILS_NOT_FOUND')
                s = matches[0]
                self.fields['symbol'] = {
                    'symbol_id':int(s.symbolId), 'min_volume':int(s.minVolume),
                    'max_volume':int(s.maxVolume), 'step_volume':int(s.stepVolume),
                    'lot_size':int(s.lotSize), 'digits':int(s.digits),
                    'trade_allowed':int(s.tradingMode)==0,
                    'short_allowed':bool(s.enableShortSelling),
                    'limited_risk_symbol':bool(s.guaranteedStopLoss),
                    'sl_distance':int(s.slDistance), 'tp_distance':int(s.tpDistance),
                    'distance_set_in':int(s.distanceSetIn),
                }
                self.parts.add('symbol')
            elif name == 'ProtoOAReconcileRes':
                # Reject new trades if *any* position / pending order exists on this account.
                self.fields['open_positions'] = len(obj.position)
                self.fields['pending_orders'] = len(obj.order)
                self.parts.add('positions')
            elif name == 'ProtoOASpotEvent':
                if int(obj.symbolId) != self.symbol_id: return
                q = self.fields.setdefault('quote', {})
                if int(getattr(obj, 'bid', 0)) > 0: q['bid'] = int(obj.bid)/1e5
                if int(getattr(obj, 'ask', 0)) > 0: q['ask'] = int(obj.ask)/1e5
                if int(getattr(obj, 'timestamp', 0)) > 0:
                    raw_ts=int(obj.timestamp)
                    q['timestamp_ms'] = raw_ts*1000 if raw_ts < 100_000_000_000 else raw_ts
                if all(k in q for k in ('bid','ask','timestamp_ms')):
                    self.parts.add('quote')
            elif name == 'ProtoOAExecutionEvent':
                if not self.saw_order: return
                order = getattr(obj, 'order', None)
                order_id = str(getattr(order, 'clientOrderId', ''))
                if order_id != self.expected_order_id: return
                # numeric protocol values: accepted=2, filled=3, rejected=7, partial=11
                t = int(obj.executionType)
                if t == 3:
                    IntentStore(self.ledger_path).update(order_id, 'FILLED')
                    self.complete('OK', {'event':'ORDER_FILLED', 'client_order_id':order_id,
                                         'position_id':int(getattr(getattr(obj,'position',None),'positionId',0))})
                elif t == 7:
                    IntentStore(self.ledger_path).update(order_id, 'REJECTED')
                    self.complete('OK', {'event':'ORDER_REJECTED','client_order_id':order_id})
                elif t == 11:
                    # Partial is not a final state; fail closed / reconciliation required.
                    self.complete('PARTIAL_FILL_RECONCILIATION_REQUIRED')
            elif name in ('ProtoOAErrorRes','ProtoErrorRes','ProtoOAOrderErrorEvent'):
                self.complete('BROKER_ERROR:'+str(getattr(obj,'errorCode', 'UNKNOWN'))[:80])
                return
            if self.demo_verified and self.task in ('snapshot','submit') and not self.saw_order:
                self._maybe_ready()
        except Exception as exc:
            self.complete('PROTOCOL_ERROR:'+str(exc)[:140])

    def _snapshot(self):
        if not {'trader','assets','name','symbol','positions','quote'} <= self.parts: return None
        f = self.fields
        currency = f['asset_map'].get(f['deposit_asset_id'], 'UNKNOWN')
        return {'account_id':self.account_id, 'is_live':False,
                'currency':currency, 'balance_usd':f['balance'],
                'full_access':f['full_access'], 'limited_risk':f['limited_risk'],
                'open_positions':f['open_positions'], 'pending_orders':f['pending_orders'],
                'symbol':{**f['symbol'],'symbol_name':f['symbol_name']}, 'quote':f['quote']}

    def _maybe_ready(self):
        snap = self._snapshot()
        if snap is None: return
        if snap['currency'] != 'USD': self.complete('UNSUPPORTED_ACCOUNT_CURRENCY');return
        if snap['limited_risk']: self.complete('LIMITED_RISK_ACCOUNT_UNSUPPORTED');return
        if not snap['symbol']['symbol_name'].upper().replace('/','').startswith(('XAUUSD','GOLD')):
            self.complete('NOT_XAUUSD_SYMBOL');return
        if not snap['full_access']: self.complete('ACCOUNT_NOT_TRADE_ENABLED');return
        if not snap['symbol']['trade_allowed']: self.complete('SYMBOL_TRADING_DISABLED');return
        if self.task == 'snapshot':
            self.complete('OK', {'event':'SNAPSHOT','snapshot':snap});return
        self._submit_with_fresh_quote(snap)

    def _submit_with_fresh_quote(self, snap):
        if self.saw_order: return
        if os.environ.get('CTRADER_ALLOW_DEMO_ORDER')!='YES' or os.environ.get('CTRADER_DEMO_CONFIRMED')!='YES':
            self.complete('ORDER_FLAGS_NOT_ENABLED');return
        if snap['open_positions'] or snap['pending_orders']:
            self.complete('BROKER_ALREADY_HAS_EXPOSURE');return
        if not self.intent_path or not Path(self.intent_path).is_file():
            self.complete('MISSING_INTENT');return
        payload = json.loads(Path(self.intent_path).read_text(encoding='utf8'))
        row = payload['candidate']; cfg = payload['config']
        switch = read_switches()['strategies'].get(row['strategy_id'])
        if not switch or not switch['enabled'] or not switch['allow_demo'] or switch['research_only']:
            self.complete('STRATEGY_NO_LONGER_ENABLED');return
        cfg['approved_strategy_ids'] = [k for k,v in read_switches()['strategies'].items()
                                        if v['enabled'] and v['allow_demo'] and not v['research_only']]
        cfg['enabled_strategy_ids'] = cfg['approved_strategy_ids']
        candidate = Candidate(strategy_id=row['strategy_id'], symbol_name=snap['symbol']['symbol_name'],
                              timeframe=row['timeframe'],
                              signal_bar_end_utc=datetime.fromisoformat(row['signal_bar_end_utc']),
                              side=row['side'],stop_price=float(row['stop_price']),target_price=float(row['target_price']),
                              pivot_confirmed=bool(row['pivot_confirmed']),source_data_ok=bool(row['source_data_ok']),
                              market_regime=row['market_regime'],signals=row['signals'])
        q = snap['quote']
        now = datetime.now(timezone.utc)
        quote = Quote(float(q['bid']),float(q['ask']),datetime.fromtimestamp(int(q['timestamp_ms'])/1000,timezone.utc))
        account = Account(self.account_id,False,snap['balance_usd'],float(payload['day_start_balance_usd']),
                          snap['open_positions']+snap['pending_orders'],snap['currency'])
        meta = snap['symbol']
        bs = BrokerSymbol(self.symbol_id,meta['symbol_name'],meta['min_volume'],meta['step_volume'],
                          meta['max_volume'],meta['lot_size'],meta['digits'],meta['trade_allowed'])
        cfg['max_sl_price_usd'] = min(float(cfg['max_sl_price_usd']),float(switch['stop_cap']))
        result = assess(candidate,quote,account,bs,cfg,now)
        if result.status != 'DEMO_READY': self.complete('DECISION_'+result.reason);return
        order = result.order
        if order['client_order_id']!=payload['order_id']:
            self.complete('ORDER_ID_CHANGED');return
        side=order['side'];price=quote.ask if side=='BUY' else quote.bid
        sl_dist=abs(price-order['stop_price']);tp_dist=abs(order['target_price']-price)
        if side=='SELL' and not meta['short_allowed']:
            self.complete('SHORT_NOT_ALLOWED');return
        if meta['distance_set_in']==1:
            point=10**(-meta['digits'])
            if sl_dist < meta['sl_distance']*point or tp_dist<meta['tp_distance']*point:
                self.complete('BROKER_MIN_STOP_DISTANCE');return
        elif meta['distance_set_in']==2:
            # percentage mode is in hundredths of a percentage point
            if sl_dist < price*meta['sl_distance']/10000 or tp_dist < price*meta['tp_distance']/10000:
                self.complete('BROKER_MIN_STOP_DISTANCE');return
        elif not (meta['sl_distance']==0 and meta['tp_distance']==0):
            self.complete('UNKNOWN_BROKER_DISTANCE_UNITS');return
        ledger=IntentStore(self.ledger_path)
        if not ledger.reserve(order): self.complete('DUPLICATE_ORDER');return
        protect=relative_protection(price,order['stop_price'],order['target_price'],side)
        req=self.oa.ProtoOANewOrderReq()
        req.ctidTraderAccountId=self.account_id;req.symbolId=self.symbol_id
        req.orderType=self.om.ProtoOAOrderType.Value('MARKET_RANGE')
        req.baseSlippagePrice=price
        req.slippageInPoints=max(1,round(0.20*10**meta['digits']))
        req.tradeSide=self.om.ProtoOATradeSide.Value(side)
        req.volume=order['volume_cent_units'];req.clientOrderId=order['client_order_id']
        req.relativeStopLoss=protect['relativeStopLoss'];req.relativeTakeProfit=protect['relativeTakeProfit']
        req.label='GS8-DEMO';req.comment=order['client_order_id']
        self.saw_order=True;self.expected_order_id=order['client_order_id']
        self.send(req)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--task', choices=['snapshot','submit'],required=True)
    p.add_argument('--symbol-id',type=int,default=None)
    p.add_argument('--intent-file',default=None)
    p.add_argument('--ledger',default='runtime/demo_intents.sqlite')
    a=p.parse_args()
    for name in ('CTRADER_ACCOUNT_ID','CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN','CTRADER_SYMBOL_ID'):
        if not os.getenv(name):raise SystemExit('Missing credential or symbol setting: '+name)
    w=DemoWorker(a.task,a.symbol_id or int(os.environ['CTRADER_SYMBOL_ID']),a.intent_file,a.ledger)
    try:
        result=w.run(); print('RESULT_JSON:'+json.dumps(result,ensure_ascii=False,sort_keys=True))
    except Exception as exc:
        print('WORKER_FAILED:'+str(exc)[:180],file=sys.stderr)
        raise SystemExit(2)
if __name__=='__main__':main()
