"""Pure message builders/converters: testable WITHOUT credentials or SDK/network.
Actual SDK protobuf classes are imported by ctrader/demo_client.py. This module is only value semantics.
"""
from datetime import datetime,timezone
from math import isfinite

def decode_trendbar(bar,digits=5):
 low=bar.low/100000.0
 p={'open':(bar.low+bar.deltaOpen)/100000.0,'high':(bar.low+bar.deltaHigh)/100000.0,'low':low,'close':(bar.low+bar.deltaClose)/100000.0,'volume':int(bar.volume),'timestamp_utc':datetime.fromtimestamp(bar.utcTimestampInMinutes*60,tz=timezone.utc).isoformat()}
 p.update({k:round(p[k],digits) for k in ['open','high','low','close']})
 if not(p['low']<=p['open']<=p['high'] and p['low']<=p['close']<=p['high']):raise ValueError('invalid trendbar OHLC')
 return p

def relative_protection(entry,stop,target,side):
 d=1 if side=='BUY' else -1
 a=d*(entry-stop);b=d*(target-entry)
 if a<=0 or b<=0 or not all(map(isfinite,(a,b))):raise ValueError('invalid SL/TP geometry')
 sl=round(a*100000);tp=round(b*100000)
 if sl<=0 or tp<=0:raise ValueError('relative protection rounded to zero')
 return {'relativeStopLoss':sl,'relativeTakeProfit':tp}

def normalize_volume(requested_protocol,min_protocol,step_protocol,max_protocol):
 if requested_protocol<min_protocol or min_protocol<=0 or step_protocol<=0 or max_protocol<min_protocol:raise ValueError('invalid broker volume')
 n=min(requested_protocol,max_protocol)
 return min_protocol+((n-min_protocol)//step_protocol)*step_protocol
