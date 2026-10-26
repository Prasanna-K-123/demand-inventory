from __future__ import annotations
import json,threading,time,uuid,math
from .common import digest
from .contracts import JobRequest,JobResult
from .features import FEATURE_VERSION,served_features
from .decisions import allocate
from .ledger import InjectedFault,LeaseLost,log

class Worker:
    def __init__(self,ledger,bundle,lease_seconds=30):
        self.ledger=ledger;self.bundle=bundle;self.owner="worker-"+uuid.uuid4().hex[:12];self.lease_seconds=lease_seconds
        self.stop_event=threading.Event();self.thread=None
    def compute(self,job):
        spec=JobRequest.model_validate_json(job["spec_json"])
        if spec.model_version!=self.bundle.version:raise ValueError("job model version unavailable")
        asof=spec.as_of.isoformat();target=spec.target_date.isoformat()
        if target<"2025-05-01":raise ValueError("artifact unavailable before calibration end")
        monitoring=json.loads(job["monitoring_json"])
        features=[];records=[];sources=set()
        for key in spec.series:
            rows=self.ledger.rows_for(key.store_id,key.product_id,target,asof,job["snapshot_seq"])
            feature=served_features(rows,target,asof)
            hh=digest([(r["event_key"],r["payload_hash"]) for r in rows]);fh=digest({"version":FEATURE_VERSION,"values":feature})
            sources.update(r["source_sha256"] for r in rows)
            records.append({"series_key":f"{key.store_id}:{key.product_id}","feature_hash":fh,"history_hash":hh,"features":feature})
            features.append(feature)
        estimates=self.bundle.predict(features);predictions=[]
        for key,f,rec,est in zip(spec.series,features,records,estimates):
            if f["count"]<7 or f["last_age"]>2:policy="restricted_insufficient_or_stale_history"
            elif f["count"]<14 or monitoring["policy"]=="fallback_seasonal_restrict_allocation":policy="fallback_seasonal"
            else:policy="normal"
            normal=policy=="normal";fallback=policy=="fallback_seasonal"
            predictions.append({"store_id":key.store_id,"product_id":key.product_id,"target_date":target,
                "point":est["point"] if normal else est["seasonal_point"] if fallback else None,
                "lower":est["lower"] if normal else None,"upper":est["upper"] if normal else None,
                "policy":policy,"decision_allowed":normal,"feature_hash":rec["feature_hash"],"history_hash":rec["history_hash"],
                "history_rows":int(f["count"]),"last_age_days":int(f["last_age"]),"interval_model":est["interval_model"] if normal else "withheld"})
        allocation=None;allocation_policy="not_requested"
        if spec.capacity_steps is not None:
            if all(p["decision_allowed"] for p in predictions):
                scenarios=[[est["scenario_low"],p["point"],est["scenario_high"]] for p,est in zip(predictions,estimates)]
                caps=[min(100,math.ceil(1.5*max(est["scenario_high"],.1)/.1)) for est in estimates]
                allocation=allocate(scenarios,spec.capacity_steps,shortage=spec.shortage_weight,caps=caps)
                allocation["policy_id"]="raw-quantile-point-grid-v1"
                allocation["scenario_definition"]="raw learned q10 / selected point forecast / raw learned q90; equal scenario weights are an explicit finite-distribution assumption, not calibrated masses"
                allocation["scenario_values"]=scenarios
                allocation["shortage_weight"]=spec.shortage_weight
                allocation["excess_weight"]=1.0
                allocation_policy="finite_grid_simulation"
            else:allocation_policy="restricted_by_history_or_monitoring"
        result={"job_id":job["job_id"],"run_id":job["job_id"],"model_version":self.bundle.version,"feature_version":FEATURE_VERSION,
                "snapshot_seq":job["snapshot_seq"],"source_sha256s":sorted(sources),"as_of":asof,"predictions":predictions,
                "allocation":allocation,"allocation_policy":allocation_policy,"monitoring":monitoring}
        JobResult.model_validate(result)
        return result,records
    def run_once(self):
        job=self.ledger.claim(self.owner,lease_seconds=self.lease_seconds)
        if not job:return False
        try:
            result,records=self.compute(job)
            self.ledger.publish(job,self.owner,result,records)
        except (InjectedFault,LeaseLost) as e:log("worker_recoverable",run_id=job["job_id"],error=str(e))
        except Exception as e:
            changed=self.ledger.fail(job,self.owner,type(e).__name__+": "+str(e));log("worker_failed" if changed else "worker_failure_not_published",run_id=job["job_id"],error=type(e).__name__)
        return True
    def _loop(self):
        while not self.stop_event.is_set():
            try:
                if not self.run_once():self.stop_event.wait(.02)
            except Exception as e:
                log("worker_loop_error",run_id=self.owner,error=type(e).__name__);self.stop_event.wait(.25)
    def start(self):
        if self.thread is not None:raise RuntimeError("worker already started")
        self.thread=threading.Thread(target=self._loop,name=self.owner,daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=35)
