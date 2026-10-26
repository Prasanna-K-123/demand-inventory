from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
import json,os,subprocess,sys,time
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from stockout.contracts import SaleEvent,JobRequest
from stockout.ledger import Ledger,Conflict,Busy,InjectedFault,LeaseLost
from stockout.features import offline_features,served_features,FEATURE_NAMES
from stockout.decisions import allocate,brute_force_oracle
from stockout.model import ModelBundle
from stockout.worker import Worker
from stockout.api import create_app

BASE=Path(__file__).resolve().parents[1]
SHA="a"*64

def event(day="2025-04-30",value=2.,store=1,product=2):
    hours=[0.]*24;hours[10]=value
    return {"source_sha256":SHA,"store_id":store,"product_id":product,"event_date":day,
            "arrived_at":(datetime.fromisoformat(day)+timedelta(days=1)).replace(tzinfo=timezone.utc).isoformat(),
            "sale_amount":value,"hours_sale":hours,"hours_stock_status":[0]*24,"oos_hours":0,"arrival_kind":"synthetic_next_midnight"}

def ledger(tmp_path,name="db.sqlite"):
    db=Ledger(tmp_path/name);db.register_source(SHA,{"kind":"synthetic test only"});return db

def spec(version="0"*16,series=None,target="2025-05-01",capacity=None):
    return JobRequest(series=series or [{"store_id":1,"product_id":2}],target_date=target,
                      as_of=target+"T00:00:00Z",model_version=version,capacity_steps=capacity)

class DummyBundle:
    version="0"*16
    def predict(self,features):
        return [{"point":f["mean_28"],"lower":0.,"upper":f["mean_28"]+1,"seasonal_point":f["seasonal_4week_fallback_mean_28"],"interval_model":"fixture"} for f in features]

def add_history(db,days=28,batch="history"):
    events=[event((date(2025,5,1)-timedelta(days=i)).isoformat(),float(i%7+1)) for i in range(days,0,-1)]
    db.ingest(batch,SHA,0,events);return events

@pytest.mark.parametrize("mutation",[
 lambda x:x.update(sale_amount=-1),lambda x:x.update(sale_amount=float("nan")),
 lambda x:x.update(hours_sale=[0.]*23),lambda x:x.update(oos_hours=1),
 lambda x:x.update(arrived_at="2025-04-30T12:00:00Z"),lambda x:x.update(arrived_at="2025-05-01T00:00:00"),
 lambda x:x.update(store_id=True),lambda x:x.update(unknown_field=123)])
def test_contract_rejects_invalid(mutation):
    e=event();mutation(e)
    with pytest.raises(ValidationError):SaleEvent.model_validate(e)

def test_ingest_conservation_dedup_conflict_quarantine(tmp_path):
    db=ledger(tmp_path);one=event();changed=event(value=3);bad=event(day="2025-04-29");bad["hours_sale"]=[]
    batch=[one,one,changed,bad]
    receipt=db.ingest("b1",SHA,0,batch)
    assert (receipt["received"],receipt["accepted"],receipt["duplicates"],receipt["quarantined"])==(4,1,1,2)
    assert receipt["end_offset"]==4
    before=db.state_digest();assert db.ingest("b1",SHA,0,batch)["replayed"]
    assert db.state_digest()==before
    with pytest.raises(Conflict):db.ingest("b1",SHA,0,[one])
    with pytest.raises(Conflict):db.ingest("bad_checkpoint",SHA,0,[one])
    assert db.state_digest()==before

@pytest.mark.parametrize("fault",["before_commit","after_commit"])
def test_ingest_atomic_crash_replay(tmp_path,fault):
    clean=ledger(tmp_path,"clean.sqlite");clean.ingest("b",SHA,0,[event()])
    crashed=ledger(tmp_path,"crash.sqlite")
    with pytest.raises(InjectedFault):crashed.ingest("b",SHA,0,[event()],fault=fault)
    reopened=Ledger(crashed.path);reopened.ingest("b",SHA,0,[event()])
    assert reopened.state_digest()==clean.state_digest()

@pytest.mark.parametrize("fault,code",[("process_exit_before_commit",91),("process_exit_after_commit",92)])
def test_real_process_exit_ingestion(tmp_path,fault,code):
    clean=ledger(tmp_path,"clean.sqlite");clean.ingest("b",SHA,0,[event()])
    crash=ledger(tmp_path,"crash.sqlite")
    payload=tmp_path/"payload.json";payload.write_text(json.dumps([event()]))
    script="import json,sys;from stockout.ledger import Ledger;d=Ledger(sys.argv[1]);d.ingest('b',sys.argv[2],0,json.load(open(sys.argv[3])),fault=sys.argv[4])"
    r=subprocess.run([sys.executable,"-c",script,str(crash.path),SHA,str(payload),fault],capture_output=True)
    assert r.returncode==code,r.stderr.decode()
    recovered=Ledger(crash.path);recovered.ingest("b",SHA,0,[event()])
    assert recovered.state_digest()==clean.state_digest()

def test_concurrent_idempotency_and_payload_conflict(tmp_path):
    db=ledger(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:db.submit("same-key",spec()),range(24)))
    assert len({r["job_id"] for r in results})==1
    assert sum(not r["deduplicated"] for r in results)==1
    with pytest.raises(Conflict):db.submit("same-key",spec(capacity=2))
    assert db.counters()["jobs"]==1

def test_bounded_queue(tmp_path):
    db=ledger(tmp_path);db.submit("one",spec(),max_queue=1)
    with pytest.raises(Busy):db.submit("two",spec(),max_queue=1)
    assert db.submit("one",spec(),max_queue=1)["deduplicated"]

def test_concurrent_workers_claim_distinct_jobs(tmp_path):
    db=ledger(tmp_path)
    for i in range(20):db.submit(str(i),spec())
    with ThreadPoolExecutor(max_workers=8) as pool:jobs=list(pool.map(lambda i:db.claim(str(i),now=100),range(20)))
    assert len({j["job_id"] for j in jobs})==20
    assert db.claim("extra",now=100) is None

def test_lease_fencing_blocks_stale_publication(tmp_path):
    db=ledger(tmp_path);add_history(db);db.submit("j",spec())
    a=db.claim("a",now=100,lease_seconds=2);b=db.claim("b",now=103,lease_seconds=2)
    worker=Worker(db,DummyBundle());result,features=worker.compute(b)
    with pytest.raises(LeaseLost):db.publish(a,"a",result,features,now=103.5)
    db.publish(b,"b",result,features,now=104)
    assert db.counters()["results"]==1
    assert db.status(b["job_id"])["attempt"]==2

@pytest.mark.parametrize("fault",["before_commit","after_commit"])
def test_atomic_result_and_feature_publication(tmp_path,fault):
    db=ledger(tmp_path);add_history(db);jid=db.submit("j",spec())["job_id"]
    job=db.claim("a",now=100,lease_seconds=2);worker=Worker(db,DummyBundle());result,features=worker.compute(job)
    with pytest.raises(InjectedFault):db.publish(job,"a",result,features,fault=fault,now=101)
    if fault=="before_commit":
        assert db.result(jid) is None and db.counters()["feature_ledger"]==0
        job2=Ledger(db.path).claim("b",now=103);r2,f2=worker.compute(job2)
        assert r2==result and f2==features
        db.publish(job2,"b",r2,f2,now=104)
    else:assert db.claim("b",now=103) is None
    assert db.counters()["results"]==db.counters()["feature_ledger"]==1
    assert db.result(jid)["predictions"]==result["predictions"]

def test_asof_late_arrivals_and_snapshot_are_enforced(tmp_path):
    db=ledger(tmp_path);events=add_history(db)
    jid=db.submit("before",spec())["job_id"]
    original=db.claim("worker",now=100)
    worker=Worker(db,DummyBundle());clean,feature=worker.compute(original)
    # Future event and a fact arriving after as_of preserve source facts but cannot enter history.
    future=event("2025-05-01",999.)
    late=event("2025-04-30",900.,store=9);late["arrived_at"]="2025-05-02T00:00:00Z";late["arrival_kind"]="synthetic_delayed"
    db.ingest("future-and-late",SHA,len(events),[future,late])
    changed,feature2=worker.compute(original)
    assert changed==clean and feature2==feature
    assert db.rows_for(9,2,"2025-05-01","2025-05-01T00:00:00+00:00",999999)==[]
    assert len(db.rows_for(9,2,"2025-05-02","2025-05-02T00:00:00+00:00",999999))==1

def test_future_outcome_and_covariate_tamper_leaves_offline_features_unchanged():
    dates=pd.date_range("2025-04-01","2025-05-10");n=len(dates)
    frame=pd.DataFrame({"store_id":1,"product_id":2,"dt":dates,"sale_amount":np.arange(n)%7+1.,"stock_hour6_22_cnt":0,"avg_temperature":30.})
    clean=offline_features(frame)
    mutated=frame.copy();mutated.loc[mutated.dt>="2025-05-01","sale_amount"]=100000.;mutated["avg_temperature"]=-9999
    changed=offline_features(mutated)
    np.testing.assert_array_equal(clean.loc[clean.dt<="2025-05-01",FEATURE_NAMES],changed.loc[changed.dt<="2025-05-01",FEATURE_NAMES])

def test_missing_calendar_date_is_not_zero_or_previous_row_lag():
    rows=[event((date(2025,5,1)-timedelta(days=i)).isoformat(),float(i)) for i in range(28,0,-1) if i!=7]
    served=served_features(rows,"2025-05-01","2025-05-01T00:00:00Z")
    assert served["count"]==27
    assert served["x"][FEATURE_NAMES.index("missing_lag7")]==1
    assert served["lag_7_fallback_mean_28"]==served["mean_28"]
    assert served["mean_28"]==pytest.approx((sum(range(1,29))-7)/27)

@pytest.mark.requires_model
def test_real_fixture_offline_served_feature_and_model_parity():
    events=json.loads((BASE/"fixtures/real_history.json").read_text())["events"]
    frame=pd.DataFrame(events).rename(columns={"event_date":"dt","oos_hours":"stock_hour6_22_cnt"})
    targets=[]
    for key,g in frame.groupby(["store_id","product_id"]):
        # Placeholder label only creates target row; feature function must exclude it.
        row=g.iloc[-1].to_dict();row.update(dt="2025-05-01",sale_amount=999.)
        targets.append(row)
    full=pd.concat([frame,pd.DataFrame(targets)],ignore_index=True)
    offline=offline_features(full);bundle=ModelBundle(BASE/"artifacts")
    for (store,product),g in frame.groupby(["store_id","product_id"]):
        rows=[e for e in events if e["store_id"]==store and e["product_id"]==product]
        served=served_features(rows,"2025-05-01","2025-05-01T00:00:00Z")
        expected=offline[(offline.store_id==store)&(offline.product_id==product)&(offline.dt=="2025-05-01")].iloc[0]
        np.testing.assert_allclose(served["x"],expected[FEATURE_NAMES].to_numpy(float),rtol=0,atol=1e-12)
        np.testing.assert_allclose(bundle.predict([served])[0]["pooled_point"],bundle.models["poisson"].predict([expected[FEATURE_NAMES].to_numpy(float)])[0]*expected.scale,rtol=0,atol=1e-12)

def test_monitoring_only_counts_available_labels_and_restricts(tmp_path):
    db=ledger(tmp_path);add_history(db)
    # Thirty distinct series labels are needed; repeated jobs must not inflate evidence.
    for i in range(30):
        jid=db.submit(f"j{i}",spec(series=[{"store_id":i+1,"product_id":2}]))["job_id"];j=db.claim("w",now=100+i)
        r,f=Worker(db,DummyBundle()).compute(j)
        r["predictions"][0].update(point=0.,lower=0.,upper=0.,policy="normal")
        db.publish(j,"w",r,f,now=100.1+i)
    assert db.monitoring("2025-05-01T12:00:00+00:00")["available_labels"]==0
    labels=[event("2025-05-01",10.,store=i+1) for i in range(30)]
    db.ingest("labels",SHA,28,labels)
    assert db.monitoring("2025-05-01T23:59:59+00:00")["available_labels"]==0
    monitor=db.monitoring("2025-05-02T00:00:00+00:00")
    assert monitor["available_labels"]==30 and monitor["policy"]=="fallback_seasonal_restrict_allocation"
    db.submit("next",spec(target="2025-05-02",capacity=20));j=db.claim("w",now=200)
    r,_=Worker(db,DummyBundle()).compute(j)
    assert r["predictions"][0]["policy"]=="fallback_seasonal"
    assert r["allocation"] is None and r["allocation_policy"]=="restricted_by_history_or_monitoring"


def test_monitoring_deduplicates_repeated_forecasts(tmp_path):
    db=ledger(tmp_path);add_history(db)
    for i in range(35):
        db.submit(str(i),spec());j=db.claim("w",now=100+i)
        r,f=Worker(db,DummyBundle()).compute(j)
        db.publish(j,"w",r,f,now=100.1+i)
    db.ingest("label",SHA,28,[event("2025-05-01",10.)])
    m=db.monitoring("2025-05-02T00:00:00+00:00")
    assert m["available_labels"]==1 and m["policy"]=="insufficient_labels"

@pytest.mark.parametrize("seed",list(range(12)))
def test_exact_allocation_matches_independent_exhaustive_oracle(seed):
    rng=np.random.default_rng(seed);s=rng.uniform(0,1,(3,3));caps=[4,3,5];capacity=int(rng.integers(0,13))
    optimum=allocate(s,capacity,caps=caps,shortage=3)
    oracle,_=brute_force_oracle(s,capacity,caps,shortage=3)
    assert optimum["objective"]==pytest.approx(oracle,abs=1e-10)
    assert sum(optimum["quantity_steps"])<=capacity
    assert all(q<=cap for q,cap in zip(optimum["quantity_steps"],caps))

@pytest.mark.requires_model
def test_api_limits_invalid_inputs_and_job_flow(tmp_path):
    app=create_app(tmp_path/"api.sqlite",BASE/"artifacts",start_worker=False)
    model=app.state.bundle.version
    with TestClient(app) as client:
        assert client.get("/health").status_code==200
        assert client.post("/v1/jobs",content=b"x"*1_048_577,headers={"content-type":"application/json"}).status_code==413
        req=spec(model).model_dump(mode="json")
        assert client.post("/v1/jobs",json=req).status_code==422
        wrong=deepcopy(req);wrong["series"]*=65
        assert client.post("/v1/jobs",json=wrong,headers={"Idempotency-Key":"x"}).status_code==422
        wrong=deepcopy(req);wrong["model_version"]="0"*16
        assert client.post("/v1/jobs",json=wrong,headers={"Idempotency-Key":"x"}).status_code==409
        wrong=deepcopy(req);wrong["target_date"]="2025-04-30";wrong["as_of"]="2025-04-30T00:00:00Z"
        assert client.post("/v1/jobs",json=wrong,headers={"Idempotency-Key":"x"}).status_code==422
        r=client.post("/v1/jobs",json=req,headers={"Idempotency-Key":"x"});assert r.status_code==202
        jid=r.json()["job_id"]
        assert client.post("/v1/jobs",json=req,headers={"Idempotency-Key":"x"}).json()["job_id"]==jid
        assert client.get(f"/v1/jobs/{jid}/result").status_code==409
        app.state.worker.run_once()
        result=client.get(f"/v1/jobs/{jid}/result").json()
        assert result["predictions"][0]["policy"]=="restricted_insufficient_or_stale_history"
        assert result["predictions"][0]["point"] is None
        assert client.get("/v1/jobs/unknown").status_code==404
        assert client.get("/v1/metrics",params={"as_of":"2025-05-01T00:00:00"}).status_code==422


@pytest.mark.requires_model
def test_model_artifact_corruption_is_rejected_before_deserialization(tmp_path):
    import shutil
    shutil.copyfile(BASE/"artifacts/models.pkl",tmp_path/"models.pkl")
    shutil.copyfile(BASE/"artifacts/model_manifest.json",tmp_path/"model_manifest.json")
    with (tmp_path/"models.pkl").open("r+b") as f:
        f.seek(100);old=f.read(1);f.seek(100);f.write(bytes([old[0]^1]))
    with pytest.raises(ValueError,match="hash mismatch"):ModelBundle(tmp_path)


@pytest.mark.requires_model
def test_real_allocation_uses_locked_raw_scenarios_and_caps(tmp_path):
    events=json.loads((BASE/"fixtures/real_history.json").read_text())["events"]
    bundle=ModelBundle(BASE/"artifacts");db=Ledger(tmp_path/"real.sqlite")
    source=events[0]["source_sha256"];db.register_source(source,{"fixture":"real; synthetic arrival"});db.ingest("real",source,0,events)
    keys=sorted({(e["store_id"],e["product_id"]) for e in events})
    db.submit("allocate",spec(bundle.version,series=[{"store_id":s,"product_id":p} for s,p in keys],capacity=40))
    worker=Worker(db,bundle);job=db.claim(worker.owner);result,_=worker.compute(job)
    features=[served_features([e for e in events if (e["store_id"],e["product_id"])==(s,p)],"2025-05-01","2025-05-01T00:00:00Z") for s,p in keys]
    est=bundle.predict(features);scenarios=[[e["scenario_low"],e["point"],e["scenario_high"]] for e in est]
    import math
    caps=[min(100,math.ceil(1.5*max(e["scenario_high"],.1)/.1)) for e in est]
    direct=allocate(scenarios,40,shortage=3,caps=caps)
    assert result["allocation"]["policy_id"]=="raw-quantile-point-grid-v1"
    assert result["allocation"]["scenario_values"]==scenarios
    for key in ["caps","quantity_steps","objective","used_steps"]:assert result["allocation"][key]==direct[key]


def test_monitoring_snapshot_survives_new_publications_and_reclaim(tmp_path):
    db=ledger(tmp_path);add_history(db)
    db.ingest("known-labels",SHA,28,[event("2025-05-01",10.,store=i+1) for i in range(30)])
    original_id=db.submit("original",spec(target="2025-05-02"))["job_id"]
    original=db.claim("first",now=100,lease_seconds=1)
    worker=Worker(db,DummyBundle());before,features=worker.compute(original)
    assert before["monitoring"]["available_labels"]==0
    assert before["predictions"][0]["policy"]=="normal"
    for i in range(30):
        db.submit(f"past-{i}",spec(series=[{"store_id":i+1,"product_id":2}]))
        job=db.claim("publisher",now=100.1)
        result,fr=worker.compute(job)
        result["predictions"][0].update(point=0.,lower=0.,upper=0.,policy="normal")
        db.publish(job,"publisher",result,fr,now=100.2)
    live=db.monitoring("2025-05-02T00:00:00+00:00",model_version="0"*16)
    assert live["available_labels"]==30 and live["policy"]=="fallback_seasonal_restrict_allocation"
    recovered=db.claim("second",now=102)
    assert recovered["job_id"]==original_id and recovered["attempt"]==2
    after,after_features=worker.compute(recovered)
    assert after==before and after_features==features
    db.publish(recovered,"second",after,after_features,now=102.1)
    # Other model versions cannot inherit those monitoring labels.
    db.submit("other-version",spec(version="f"*16,target="2025-05-02"))
    other=db.claim("other",now=103)
    assert json.loads(other["monitoring_json"])["available_labels"]==0


@pytest.mark.requires_model
def test_manifest_only_mutation_changes_identity_and_is_rejected(tmp_path):
    import shutil
    shutil.copyfile(BASE/"artifacts/models.pkl",tmp_path/"models.pkl")
    manifest=json.loads((BASE/"artifacts/model_manifest.json").read_text())
    manifest["calibration_margin"]+=.25
    (tmp_path/"model_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match="configuration identity mismatch"):ModelBundle(tmp_path)


@pytest.mark.requires_model
def test_feature_implementation_compatibility_is_checked(monkeypatch):
    import stockout.model as module
    original=module.implementation_hashes()
    monkeypatch.setattr(module,"implementation_hashes",lambda:{**original,"features.py":"b"*64})
    with pytest.raises(ValueError,match="implementation compatibility mismatch"):ModelBundle(BASE/"artifacts")


def test_expired_owner_cannot_publish_failure_and_current_owner_can(tmp_path):
    db=ledger(tmp_path);jid=db.submit("lease-fail",spec())["job_id"]
    expired=db.claim("old",now=100,lease_seconds=1)
    assert db.fail(expired,"old","late exception",now=102) is False
    assert db.status(jid)["state"]=="running"
    current=db.claim("new",now=102,lease_seconds=5)
    assert current["job_id"]==jid and current["attempt"]==2
    assert db.fail(expired,"old","stale token",now=103) is False
    assert db.fail(current,"new","current owner error",now=103) is True
    assert db.status(jid)["state"]=="failed"
