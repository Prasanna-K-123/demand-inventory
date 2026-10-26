"""Reproduce the locked study. No network or API credential required."""
from __future__ import annotations
import argparse,hashlib,json,math,pickle,sys,time,warnings,platform
from datetime import datetime,timezone
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_pinball_loss
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from stockout.common import file_hash,atomic_json,digest
from stockout.features import offline_features,FEATURE_VERSION,FEATURE_NAMES
from stockout.decisions import allocate,loss
from stockout.model import bind_manifest

BASE=Path(__file__).resolve().parents[1]
ART=BASE/"artifacts"
SPLITS={"fit":("2023-06-05","2024-12-31"),"validation":("2025-01-01","2025-02-28"),
 "calibration":("2025-03-01","2025-04-30"),"final":("2025-05-01","2025-07-13"),
 "official_external":("2025-07-14","2025-07-20")}
BASELINES=["last_observation","lag_7_fallback_mean_28","mean_28","seasonal_4week_fallback_mean_28"]
def report(stage,**kw):print(json.dumps({"stage":stage,**kw}),flush=True)
def sqlpath(p):return str(p.resolve()).replace("\\","/").replace("'","''")
def source_audit(con,path,expected):
    actual=file_hash(path)
    if actual!=expected:raise ValueError("source hash mismatch: "+str(path))
    view="read_parquet('"+sqlpath(path)+"')"
    schema=[{"name":r[0],"type":r[1]} for r in con.execute("describe select * from "+view).fetchall()]
    q="""select count(*) rows,min(dt) first_date,max(dt) last_date,
      count(distinct (store_id,product_id)) series,
      sum(case when store_id is null or product_id is null or try_cast(dt as date) is null or sale_amount is null or not isfinite(sale_amount) or sale_amount<0 then 1 else 0 end) bad_scalar,
      sum(case when hours_sale is null or len(hours_sale)!=24 or hours_stock_status is null or len(hours_stock_status)!=24 then 1 else 0 end) bad_array_length,
      sum(case when len(list_filter(hours_sale,lambda x: x is null or not isfinite(x) or x<0))>0 or len(list_filter(hours_stock_status,lambda x: x is null or x not in (0,1)))>0 then 1 else 0 end) bad_array_value,
      sum(case when abs(list_sum(hours_sale)-sale_amount)>0.000001 then 1 else 0 end) daily_hourly_mismatch,
      max(abs(list_sum(hours_sale)-sale_amount)) max_daily_hourly_delta,
      sum(case when stock_hour6_22_cnt is null or stock_hour6_22_cnt<0 or stock_hour6_22_cnt>16 or list_sum(list_slice(hours_stock_status,7,22))!=stock_hour6_22_cnt then 1 else 0 end) stock_count_mismatch,
      sum(sale_amount) normalized_sales_sum,
      sum(list_sum(hours_sale)) hourly_normalized_sales_sum,
      sum(case when stock_hour6_22_cnt>0 then 1 else 0 end) rows_with_business_hour_stockout
      from """+view
    rec=con.execute(q).fetchdf().iloc[0].to_dict()
    rec={k:(int(v) if isinstance(v,(np.integer,)) else float(v) if isinstance(v,np.floating) else v) for k,v in rec.items()}
    rec["duplicate_keys"]=con.execute("select count(*)-count(distinct (store_id,product_id,dt)) from "+view).fetchall()[0][0]
    rec.update(sha256=actual,bytes=path.stat().st_size,schema=schema)
    return rec

def metrics(y,p):
    y=np.asarray(y);p=np.asarray(p);err=y-p
    return {"n":len(y),"mae":float(np.mean(np.abs(err))),"rmse":float(np.sqrt(np.mean(err**2))),
            "wape":float(np.abs(err).sum()/y.sum()) if y.sum()>0 else None}

def block_bootstrap(frame):
    z=frame.assign(delta=np.abs(frame.sale_amount-frame.pooled_poisson)-np.abs(frame.sale_amount-frame.seasonal_4week_fallback_mean_28)).groupby("dt").delta.mean()
    vals=z.to_numpy();n=len(vals);rng=np.random.default_rng(410);draw=[]
    for _ in range(500):
        starts=rng.integers(0,max(1,n-7+1),size=math.ceil(n/7))
        ids=np.concatenate([np.arange(s,min(s+7,n)) for s in starts])[:n]
        draw.append(float(vals[ids].mean()))
    return {"daily_average_mae_difference_pooled_minus_seasonal":float(vals.mean()),"ci95_percentile":np.quantile(draw,[.025,.975]).tolist(),"dates":n,"replicates":500,"block_days":7,"interpretation":"exploratory paired moving-block bootstrap; not an IID or causal guarantee"}

def run(args):
    start=time.perf_counter();ART.mkdir(exist_ok=True);args.runtime.mkdir(parents=True,exist_ok=True)
    protocol=json.loads((BASE/"protocol.json").read_text());ph=file_hash(BASE/"protocol.json")
    if ph!=(BASE/"protocol.sha256").read_text().split()[0]:raise ValueError("locked protocol changed")
    con=duckdb.connect();con.execute("SET threads=2")
    audits={}
    for split in ("train","eval"):
        path=args.data/f"fresh-lt-{split}.parquet"
        audits[split]=source_audit(con,path,protocol["source"][split+"_sha256"])
        report("source_audit",split=split,rows=audits[split]["rows"],bad_scalar=audits[split]["bad_scalar"],daily_hourly_mismatch=audits[split]["daily_hourly_mismatch"],stock_count_mismatch=audits[split]["stock_count_mismatch"])
    atomic_json(ART/"source_audit.json",audits)
    for a in audits.values():
        if any(a[k] for k in ["bad_scalar","bad_array_length","bad_array_value","stock_count_mismatch","duplicate_keys"]):
            raise ValueError("source contract failure; audit retained for investigation")
    train="read_parquet('"+sqlpath(args.data/'fresh-lt-train.parquet')+"')"
    eligible=con.execute("""select store_id,product_id,count(*) history_rows,
      sum(case when dt>='2024-10-01' then 1 else 0 end) recent_rows
      from """+train+" where dt<='2024-12-31' group by store_id,product_id having count(*)>=180 and recent_rows>=60").fetchdf()
    eligible["identity_hash"]=[hashlib.sha256(f"stockout-v1|{s}|{p}".encode()).hexdigest() for s,p in zip(eligible.store_id,eligible.product_id)]
    cohort=eligible.sort_values("identity_hash").head(1024).copy()
    cohort["identity_split"]=["transfer_holdout" if int(h,16)%5==0 else "fitting_identities" for h in cohort.identity_hash]
    cohort.to_csv(ART/"cohort.csv",index=False)
    atomic_json(ART/"cohort_receipt.json",{"eligible_series":len(eligible),"selected_series":len(cohort),"fitting_identities":int((cohort.identity_split=="fitting_identities").sum()),"transfer_holdout":int((cohort.identity_split=="transfer_holdout").sum()),"cohort_sha256":file_hash(ART/"cohort.csv"),"protocol_sha256":ph,"selection_used":"training identity and date availability only"})
    con.register("cohort_ids",cohort)
    frames=[]
    columns="a.store_id,a.product_id,a.dt,a.sale_amount,a.hours_sale,a.hours_stock_status,a.stock_hour6_22_cnt,c.identity_split,c.identity_hash"
    for split in ("train","eval"):
        src="read_parquet('"+sqlpath(args.data/f'fresh-lt-{split}.parquet')+"')"
        frames.append(con.execute(f"select {columns} from {src} a inner join cohort_ids c using(store_id,product_id)").fetchdf())
    raw=pd.concat(frames,ignore_index=True).sort_values(["store_id","product_id","dt"]).reset_index(drop=True)
    if raw.duplicated(["store_id","product_id","dt"]).any():raise ValueError("cross-source duplicate keys")
    con.register("raw_cohort",raw)
    cohort_path=args.runtime/"cohort.parquet"
    con.execute("copy raw_cohort to '"+sqlpath(cohort_path)+"' (format parquet)")
    report("cohort",rows=len(raw),series=len(cohort))
    feature=offline_features(raw)
    feature=feature.merge(cohort[["store_id","product_id","identity_split","identity_hash"]],on=["store_id","product_id"],validate="many_to_one")
    feature["split"]=""
    for name,(a,b) in SPLITS.items():feature.loc[feature.dt.between(a,b),"split"]=name
    attr=[]
    for identity in ("fitting_identities","transfer_holdout"):
        expected=int((cohort.identity_split==identity).sum())
        for name,(a,b) in SPLITS.items():
            g=feature[(feature.identity_split==identity)&(feature.split==name)]
            usable=g[g["count"]>=14]
            attr.append({"identity_split":identity,"split":name,"selected_identities":expected,"observed_identities":int(g[["store_id","product_id"]].drop_duplicates().shape[0]),"observed_rows":len(g),"expected_calendar_rows":expected*len(pd.date_range(a,b)),"usable_rows":len(usable),"usable_identities":int(usable[["store_id","product_id"]].drop_duplicates().shape[0])})
    atomic_json(ART/"attrition.json",attr)
    feature=feature[feature["count"]>=14].reset_index(drop=True)
    fit=feature[(feature.split=="fit")&(feature.identity_split=="fitting_identities")]
    x=fit[FEATURE_NAMES].to_numpy(); y=fit.sale_amount.to_numpy()/fit.scale.to_numpy()
    kwargs=dict(max_iter=160,max_leaf_nodes=15,min_samples_leaf=40,learning_rate=.05,l2_regularization=3.,early_stopping=False,random_state=42)
    models={};timings={}
    for name,lossname,q in [("poisson","poisson",None),("q10","quantile",.1),("q90","quantile",.9)]:
        report("fit_start",model=name,rows=len(fit));t=time.perf_counter()
        model=HistGradientBoostingRegressor(loss=lossname,quantile=q,**kwargs).fit(x,y)
        models[name]=model;timings[name]=time.perf_counter()-t
        report("fit_end",model=name,seconds=timings[name])
    evalframe=feature[feature.split!="fit"].copy()
    xe=evalframe[FEATURE_NAMES].to_numpy();scale=evalframe.scale.to_numpy()
    evalframe["pooled_poisson"]=np.maximum(0,models["poisson"].predict(xe)*scale)
    l=np.maximum(0,models["q10"].predict(xe)*scale);u=np.maximum(0,models["q90"].predict(xe)*scale)
    evalframe["q10_raw"]=np.minimum(l,u);evalframe["q90_raw"]=np.maximum(l,u)
    calibration=evalframe[(evalframe.split=="calibration")&(evalframe.identity_split=="fitting_identities")]
    scores=np.maximum(calibration.q10_raw-calibration.sale_amount,calibration.sale_amount-calibration.q90_raw).to_numpy()
    rank=min(len(scores),math.ceil((len(scores)+1)*.8));margin=float(np.sort(scores)[rank-1])
    # A nonnegative expansion avoids turning already-wide intervals into crossed intervals.
    # CQR score can be negative; retaining zero instead is conservative, declared in deviations if needed.
    margin_used=max(0.,margin)
    evalframe["lower"]=np.maximum(0,evalframe.q10_raw-margin_used)
    evalframe["upper"]=np.maximum(evalframe.lower,evalframe.q90_raw+margin_used)
    validation=evalframe[(evalframe.split=="validation")&(evalframe.identity_split=="fitting_identities")]
    candidates=["seasonal_4week_fallback_mean_28","pooled_poisson"]
    selected=min(candidates,key=lambda n:float(np.abs(validation.sale_amount-validation[n]).mean()))
    evalframe["selected_point"]=evalframe[selected]
    modelpath=ART/"models.pkl"
    with modelpath.open("wb") as f:pickle.dump(models,f,protocol=5)
    artifact_sha=file_hash(modelpath)
    manifest={"model_version":artifact_sha[:16],"artifact_sha256":artifact_sha,"feature_version":FEATURE_VERSION,"feature_names":FEATURE_NAMES,"protocol_sha256":ph,"cohort_sha256":file_hash(ART/"cohort.csv"),"selected_point_model":selected,"selection_split":"validation only","training_rows":len(fit),"training_end":"2024-12-31","calibration_start":"2025-03-01","calibration_end":"2025-04-30","calibration_rows":len(calibration),"calibration_raw_margin":margin,"calibration_margin":margin_used,"fit_seconds":timings,"source_hashes":[a["sha256"] for a in audits.values()],"poisson_interpretation":"mean model using Poisson loss on normalized non-integer quantities; not a calibrated count distribution","serialization":"trusted local pickle only; verify digest before loading"}
    manifest=bind_manifest(manifest)
    atomic_json(ART/"model_manifest.json",manifest)
    summary=[]
    for (split,identity),g in evalframe.groupby(["split","identity_split"]):
        for stratum,sub in [("all_observed",g),("no_business_hour_stockout",g[g.stock_hour6_22_cnt==0]),("business_hour_stockout",g[g.stock_hour6_22_cnt>0])]:
            for model in BASELINES+["pooled_poisson"]:
                if not len(sub):continue
                summary.append({"split":split,"identity_split":identity,"stratum":stratum,"model":model,**metrics(sub.sale_amount,sub[model])})
    interval=[]
    for (split,identity),g in evalframe.groupby(["split","identity_split"]):
        interval.append({"split":split,"identity_split":identity,"n":len(g),"coverage80":float(((g.sale_amount>=g.lower)&(g.sale_amount<=g.upper)).mean()) if split!="validation" else None,"mean_width":float((g.upper-g.lower).mean()) if split!="validation" else None,"evaluation_role":"raw quantile validation only; CQR calibration unavailable as-of" if split=="validation" else "in-sample calibration diagnostic" if split=="calibration" else "held-out temporal evaluation","pinball10_raw":float(mean_pinball_loss(g.sale_amount,g.q10_raw,alpha=.1)),"pinball90_raw":float(mean_pinball_loss(g.sale_amount,g.q90_raw,alpha=.9))})
    final=evalframe[(evalframe.split=="final")&(evalframe.identity_split=="fitting_identities")]
    bootstrap=block_bootstrap(final)
    # Conditional artificial masking experiment; true business-hour full subtotal is observed.
    profile_rows=raw[(raw.identity_split=="fitting_identities")&(raw.dt<="2024-12-31")&(raw.stock_hour6_22_cnt==0)]
    hours=np.vstack(profile_rows.hours_sale.to_numpy())[:,6:22]
    share=(hours.sum(axis=0)+1e-12)/(hours.sum()+16e-12)
    maskrows=raw[(raw.dt>="2025-05-01")&(raw.dt<="2025-07-13")&(raw.stock_hour6_22_cnt==0)]
    masking=[]
    for identity,g in maskrows.groupby("identity_split"):
        h=np.vstack(g.hours_sale.to_numpy())[:,6:22];truth=h.sum(axis=1)
        for hide in [4,8]:
            observed=h[:,:16-hide].sum(axis=1)
            for name,estimate in [("zero_fill",observed),("uniform_exposure",observed*16/(16-hide)),("training_hourly_share",observed/share[:16-hide].sum())]:
                masking.append({"identity_split":identity,"hidden_last_hours":hide,"method":name,**metrics(truth,estimate),"bias":float(np.mean(estimate-truth))})
    atomic_json(ART/"artificial_masking.json",{"fit_rows":len(profile_rows),"hour_share_6_to_21":share.tolist(),"results":masking,"meaning":"artificially hidden values on conditional fully in-stock days; organic missing demand remains unidentified"})
    # Finite-grid decision experiment, fixed identity ranking and explicit synthetic costs.
    decisions=[]
    for day,g in final.groupby("dt"):
        g=g.sort_values("identity_hash").head(8)
        if len(g)<8:continue
        scenarios=np.column_stack([g.q10_raw.to_numpy(),g.selected_point.to_numpy(),g.q90_raw.to_numpy()])
        budget=int(np.floor(.8*np.maximum(g.mean_28.to_numpy(),.1).sum()/.1))
        cap=np.minimum(100,np.ceil(1.5*np.maximum(g.q90_raw.to_numpy(),.1)/.1).astype(int))
        point=np.maximum(0,g.selected_point.to_numpy());prop=np.floor((point/point.sum() if point.sum() else np.full(8,1/8))*budget).astype(int);prop=np.minimum(prop,cap)
        truth=g.sale_amount.to_numpy()
        for shortage in [1.,3.,5.]:
            opt=allocate(scenarios,budget,shortage=shortage,caps=cap)
            oracle=allocate(truth[:,None],budget,shortage=shortage,caps=cap)
            for name,qs,obj in [("scenario_dp",np.array(opt["quantities"]),opt["objective"]),("proportional_point",prop*.1,None),("zero_capacity",np.zeros(8),None),("hindsight_grid_oracle",np.array(oracle["quantities"]),oracle["objective"])]:
                realized=float(np.sum(shortage*np.maximum(truth-qs,0)+np.maximum(qs-truth,0)))
                decisions.append({"date":day.date().isoformat(),"shortage_weight":shortage,"policy":name,"realized_proxy_cost":realized,"scenario_objective":obj,"capacity_steps":budget,"used_steps":int(round(qs.sum()/.1)),"items":8,"shortage_proxy":float(np.maximum(truth-qs,0).sum()),"excess_proxy":float(np.maximum(qs-truth,0).sum())})
    decisionframe=pd.DataFrame(decisions);decisionframe.to_csv(ART/"decision_days.csv",index=False)
    decision_summary=decisionframe.groupby(["shortage_weight","policy"]).agg(days=("date","count"),mean_proxy_cost=("realized_proxy_cost","mean"),mean_shortage=("shortage_proxy","mean"),mean_excess=("excess_proxy","mean")).reset_index().to_dict(orient="records")
    # Rounding any feasible continuous allocation down loses at most shortage * step per item.
    grid_bound={"step":.1,"items_per_day":8,"upper_bound_continuous_optimality_gap_per_day":{"shortage1":.8,"shortage3":2.4,"shortage5":4.0},"derivation":"For identical per-item caps and capacity, round continuous q down to grid. Feasibility preserved; loss increases by at most shortage_weight * step per item. Bound concerns declared scenario objective, not realized retailer outcomes."}
    columns=["store_id","product_id","dt","identity_split","split","sale_amount","stock_hour6_22_cnt",*BASELINES,"pooled_poisson","selected_point","q10_raw","q90_raw","lower","upper","count","last_age"]
    export=evalframe[columns].copy()
    export["interval_available_asof"]=export.split.isin(["final","official_external"])
    export["interval_evaluation_role"]=export.split.map({"validation":"unavailable_asof_retrospective_values_suppressed","calibration":"in_sample_calibration_diagnostic","final":"held_out_temporal_evaluation","official_external":"held_out_short_external_check"})
    export.loc[export.split=="validation",["lower","upper"]]=np.nan
    export.to_csv(ART/"forecast_results.csv.gz",index=False,compression="gzip")
    pd.DataFrame(summary).to_csv(ART/"forecast_metrics.csv",index=False)
    atomic_json(ART/"interval_metrics.json",interval)
    atomic_json(ART/"bootstrap.json",bootstrap)
    atomic_json(ART/"decision_summary.json",{"results":decision_summary,"grid_bound":grid_bound})
    con.register("feature_table",feature)
    con.execute("copy feature_table to '"+sqlpath(args.runtime/"features.parquet")+"' (format parquet)")
    # Real, attributed fixture: first two fitting identities, last 28 pre-final days.
    ids=cohort[cohort.identity_split=="fitting_identities"].head(2)[["store_id","product_id"]]
    fixture=raw.merge(ids,on=["store_id","product_id"])
    fixture=fixture[(fixture.dt>="2025-04-03")&(fixture.dt<="2025-04-30")]
    records=[]
    for row in fixture.itertuples():
        records.append({"source_sha256":audits["train"]["sha256"],"store_id":int(row.store_id),"product_id":int(row.product_id),"event_date":row.dt,"arrived_at":(pd.Timestamp(row.dt)+pd.Timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),"sale_amount":float(row.sale_amount),"hours_sale":row.hours_sale.tolist(),"hours_stock_status":row.hours_stock_status.tolist(),"oos_hours":int(row.stock_hour6_22_cnt),"arrival_kind":"synthetic_next_midnight"})
    atomic_json(BASE/"fixtures/real_history.json",{"attribution":"Dingdong-Inc FreshRetailNet-LT v1.0 (2026-02-02), CC BY 4.0; reduced fields; arrival timestamps are synthetic","source_url":"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-LT","events":records})
    # Plot saved tables; no browser/UI QA claimed.
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11,"axes.spines.top":False,"axes.spines.right":False})
    fig,ax=plt.subplots(figsize=(9,4.8),layout="constrained")
    m=pd.DataFrame(summary);m=m[(m.split=="final")&(m.identity_split=="fitting_identities")&(m.stratum=="all_observed")]
    labels=["Last observed","Weekly lag","28-day mean","4-week seasonal","Pooled Poisson"]
    ax.barh(labels,m.set_index("model").loc[BASELINES+["pooled_poisson"],"mae"],color=["#9caeb8"]*4+["#106e6b"])
    ax.set_xlabel("MAE · normalized sales quantity");ax.set_title("Observed next-day sales · final historical test")
    fig.savefig(ART/"forecast_mae.png",dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.8),layout="constrained")
    for model,label in [("seasonal_4week_fallback_mean_28","Seasonal"),("pooled_poisson","Pooled")]:
        daily=final.assign(error=np.abs(final.sale_amount-final[model])).groupby("dt").error.mean().rolling(7,min_periods=1).mean()
        ax.plot(daily.index,daily,label=label)
    ax.legend();ax.set_ylabel("7-day mean absolute error");ax.set_title("Errors over time · fitting identities, held-out dates")
    fig.savefig(ART/"error_over_time.png",dpi=160);plt.close(fig)
    receipt={"run_id":"research-"+ph[:12],"finished_utc":datetime.now(timezone.utc).isoformat(),"protocol_sha256":ph,"cohort_rows":len(raw),"feature_rows":len(feature),"fit_rows":len(fit),"evaluation_rows":len(evalframe),"selected_model":selected,"total_seconds":time.perf_counter()-start,"source_covered_rows":sum(a["rows"] for a in audits.values()),"protocol_deviations":["Capacity middle scenario is the selected point/mean forecast, not an estimated q50; scenario labels corrected without refitting."]+(["Conformal margin floored at zero to avoid narrowing; raw margin retained. Conservative interval expansion."] if margin<0 else []),"bootstrap":bootstrap,"maturity":"executed local research prototype; no production use or retailer impact established"}
    atomic_json(ART/"research_receipt.json",receipt)
    report("complete",**receipt)

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--data",type=Path,required=True);ap.add_argument("--runtime",type=Path,required=True);run(ap.parse_args())
