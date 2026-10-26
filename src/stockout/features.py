"""One authoritative past-only feature definition for offline and served inference.
Missing calendar dates remain NaN internally; they never become observed zero.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
import hashlib
import warnings
import numpy as np
import pandas as pd

FEATURE_VERSION = "history-v1"
FEATURE_NAMES = ["log_scale", "mean7_ratio", "sd28_ratio", "last_ratio", "seasonal_ratio",
                 "lag1_ratio", "lag7_ratio", "lag14_ratio", "lag28_ratio",
                 "missing_lag1", "missing_lag7", "missing_lag14", "missing_lag28",
                 "history28_fraction", "history7_fraction", "oos28_fraction", "last_age",
                 "dow_sin", "dow_cos", "year_sin", "year_cos"]

def transform(hist: np.ndarray, oos: np.ndarray, dates: pd.DatetimeIndex):
    """hist[:, -1] is yesterday; hist[:, 0] is 28 calendar days ago."""
    hist=np.asarray(hist,dtype=float); oos=np.asarray(oos,dtype=float)
    count=np.isfinite(hist).sum(axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean=np.nanmean(hist,axis=1); mean=np.nan_to_num(mean, nan=0.0)
        mean7=np.nanmean(hist[:,-7:],axis=1); mean7=np.where(np.isfinite(mean7),mean7,mean)
        sd=np.nan_to_num(np.nanstd(hist,axis=1),nan=0.0)
        seasonal=np.nanmean(hist[:,[0,7,14,21]],axis=1)
        seasonal=np.where(np.isfinite(seasonal),seasonal,mean)
        stock=np.nan_to_num(np.nanmean(oos,axis=1)/16.0,nan=0.0)
    scale=np.maximum(mean,0.1)
    ages=np.where(np.isfinite(hist),np.arange(28,0,-1),99).min(axis=1)
    last=np.zeros(len(hist))
    valid=count>0
    last[valid]=hist[np.flatnonzero(valid),28-ages[valid]]
    lags=hist[:,[27,21,14,0]]
    missing=(~np.isfinite(lags)).astype(float)
    lags=np.where(np.isfinite(lags),lags,mean[:,None])
    dow=np.asarray(dates.dayofweek); doy=np.asarray(dates.dayofyear)
    x=np.column_stack([np.log1p(scale),mean7/scale,sd/scale,last/scale,seasonal/scale,
                       lags/scale[:,None],missing,count/28,np.isfinite(hist[:,-7:]).sum(axis=1)/7,
                       stock,ages,np.sin(2*np.pi*dow/7),np.cos(2*np.pi*dow/7),
                       np.sin(2*np.pi*doy/365.25),np.cos(2*np.pi*doy/365.25)])
    return {"x":x,"scale":scale,"count":count,"last_age":ages,"mean_28":mean,
            "last_observation":last,"lag_7_fallback_mean_28":lags[:,1],
            "seasonal_4week_fallback_mean_28":seasonal}

def offline_features(frame: pd.DataFrame) -> pd.DataFrame:
    blocks=[]
    for (store,product),g in frame.groupby(["store_id","product_id"],sort=True):
        g=g.sort_values("dt").copy(); g["dt"]=pd.to_datetime(g["dt"])
        if g["dt"].duplicated().any(): raise ValueError("duplicate event dates")
        dates=pd.date_range(g.dt.min(),g.dt.max(),freq="D")
        dense=g.set_index("dt").reindex(dates)
        y=dense.sale_amount.to_numpy(float); s=dense.stock_hour6_22_cnt.to_numpy(float)
        hist=np.lib.stride_tricks.sliding_window_view(np.r_[np.full(28,np.nan),y],28)[:-1]
        oos=np.lib.stride_tricks.sliding_window_view(np.r_[np.full(28,np.nan),s],28)[:-1]
        t=transform(hist,oos,dates)
        out=pd.DataFrame(t.pop("x"),columns=FEATURE_NAMES,index=dates)
        for k,v in t.items():out[k]=v
        out["store_id"]=int(store); out["product_id"]=int(product)
        out["sale_amount"]=y; out["stock_hour6_22_cnt"]=s
        out["dt"]=dates
        blocks.append(out.loc[dense.sale_amount.notna()].reset_index(drop=True))
    return pd.concat(blocks,ignore_index=True)

def served_features(rows: list[dict], target_date: str, as_of: str | None = None):
    target=pd.Timestamp(target_date).normalize()
    hist=np.full((1,28),np.nan); stock=np.full((1,28),np.nan)
    seen=set()
    cutoff=pd.Timestamp(as_of) if as_of else None
    for row in rows:
        day=pd.Timestamp(row["event_date"]).normalize()
        if day>=target:continue
        if cutoff is not None and pd.Timestamp(row["arrived_at"])>cutoff:continue
        age=(target-day).days
        if not 1<=age<=28:continue
        if day in seen:raise ValueError("duplicate event date in feature history")
        seen.add(day); hist[0,28-age]=row["sale_amount"]; stock[0,28-age]=row["oos_hours"]
    result=transform(hist,stock,pd.DatetimeIndex([target]))
    return {k:(v[0].tolist() if k=="x" else float(v[0])) for k,v in result.items()}
