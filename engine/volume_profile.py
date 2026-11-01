"""OHLCV tick-volume *approximation* of volume-at-price.
No real per-trade-by-price tape is available in cTrader trendbars. Do not call
these rows exchange volume, CVD, order flow, or true bid/ask delta.
The feature FAILS CLOSED without positive measured volume.
"""
from dataclasses import dataclass,asdict
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class Profile:
    poc:float
    vah:float
    val:float
    total_tick_volume:float
    rows:int
    bars:int
    source:str='CTRADER_TICK_VOLUME_OHLC_DISTRIBUTED_ESTIMATE'
    def asdict(self):return asdict(self)

def compute(df:pd.DataFrame,*,lookback=200,rows=40,value_area=0.70)->Profile:
    if not 10<=lookback<=10000 or not 4<=rows<=300 or not .5<=value_area<1:
        raise ValueError('Invalid profile settings')
    if 'volume' not in df.columns:
        raise ValueError('NO_VOLUME_DATA: legacy historical OHLC cannot produce volume profile')
    d=df.tail(lookback)
    if len(d)<10 or not {'high','low','open','close'}<=set(d.columns):raise ValueError('OHLCV history insufficient')
    a=d[['low','high','volume']].apply(pd.to_numeric,errors='coerce').to_numpy()
    if not np.isfinite(a).all() or (a[:,1]<a[:,0]).any() or (a[:,2]<0).any() or a[:,2].sum()<=0:
        raise ValueError('Invalid/missing tick volume')
    mn=float(a[:,0].min());mx=float(a[:,1].max())
    if not mx>mn:raise ValueError('Flat price range')
    step=(mx-mn)/rows
    hist=np.zeros(rows,dtype=float)
    for lo,hi,volume in a:
        if not volume:continue
        if hi==lo:hist[min(rows-1,max(0,int((lo-mn)/step)))]+=volume;continue
        # Allocate candle's tick volume proportional to overlap with its range.
        jlo=max(0,int((lo-mn)/step));jhi=min(rows-1,int((hi-mn)/step))
        for j in range(jlo,jhi+1):
            overlap=max(0,min(hi,mn+(j+1)*step)-max(lo,mn+j*step))
            hist[j]+=volume*overlap/(hi-lo)
    peak=int(hist.argmax());left=right=peak;total=float(hist.sum());covered=float(hist[peak]);target=total*value_area
    while covered<target and (left>0 or right<rows-1):
        aleft=hist[left-1] if left>0 else -1
        aright=hist[right+1] if right<rows-1 else -1
        if aright>aleft:right+=1;covered+=hist[right]
        else:left-=1;covered+=hist[left]
    return Profile(round(mn+(peak+.5)*step,6),round(mn+(right+1)*step,6),round(mn+left*step,6),total,rows,len(d))
