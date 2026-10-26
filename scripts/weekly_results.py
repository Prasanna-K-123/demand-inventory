"""Locked addendum: disjoint seven-day summaries without refitting."""
from pathlib import Path
import json
import numpy as np,pandas as pd
from stockout.common import atomic_json,file_hash
BASE=Path(__file__).resolve().parents[1]
f=pd.read_csv(BASE/"artifacts/forecast_results.csv.gz",parse_dates=["dt"])
final=f[f.split=="final"].copy();final["block"]=(final.dt-pd.Timestamp("2025-05-01")).dt.days//7
rows=[]
for (identity,block),g in final.groupby(["identity_split","block"]):
    dates=g.dt.nunique()
    for model in ["last_observation","lag_7_fallback_mean_28","mean_28","seasonal_4week_fallback_mean_28","pooled_poisson"]:
        err=np.abs(g.sale_amount-g[model])
        rows.append({"identity_split":identity,"block":int(block),"start":g.dt.min().date().isoformat(),"end":g.dt.max().date().isoformat(),"observed_dates":int(dates),"full_seven_day_block":dates==7,"rows":len(g),"model":model,"mae":float(err.mean()),"wape":float(err.sum()/g.sale_amount.sum())})
w=pd.DataFrame(rows);w.to_csv(BASE/"artifacts/weekly_metrics.csv",index=False)
p=w[(w.identity_split=="fitting_identities")&w.full_seven_day_block].pivot(index="block",columns="model",values="mae")
summary={"addendum_sha256":file_hash(BASE/"protocol-addendum.json"),"full_disjoint_seven_day_blocks":len(p),"pooled_beats_seasonal_blocks":int((p.pooled_poisson<p.seasonal_4week_fallback_mean_28).sum()),"pooled_best_of_all_five_blocks":int((p.idxmin(axis=1)=="pooled_poisson").sum()),"window_definition":"2025-05-01 anchored consecutive non-overlapping 7-day blocks; partial final block reported separately","fixed_fit":"No refits per origin; observed prior-day lags updated. One-day-ahead forecast, not fixed-origin seven-day prediction."}
atomic_json(BASE/"artifacts/weekly_summary.json",summary);print(json.dumps(summary))
