"""Actual process-exit tests around the atomic result publication transaction."""
import argparse,json,os,subprocess,sys,time,uuid
from pathlib import Path
from stockout.common import atomic_json,digest
from stockout.contracts import JobRequest
from stockout.ledger import Ledger
from stockout.model import ModelBundle
from stockout.worker import Worker
BASE=Path(__file__).resolve().parents[1]

def semantic(result):return {k:v for k,v in result.items() if k not in ["job_id","run_id","result_hash"]}
def run(a):
    if a.child:
        db=Ledger(a.db);bundle=ModelBundle(BASE/"artifacts");worker=Worker(db,bundle)
        job=db.claim("crash-worker",lease_seconds=1.0);result,features=worker.compute(job)
        db.publish(job,"crash-worker",result,features,fault=a.child)
        raise AssertionError("process exit did not occur")
    a.runtime.mkdir(parents=True,exist_ok=True);fixture=json.loads((BASE/"fixtures/real_history.json").read_text())["events"]
    first=fixture[0];events=[e for e in fixture if e["store_id"]==first["store_id"] and e["product_id"]==first["product_id"]]
    bundle=ModelBundle(BASE/"artifacts")
    spec=JobRequest(series=[{"store_id":first["store_id"],"product_id":first["product_id"]}],target_date="2025-05-01",as_of="2025-05-01T00:00:00Z",model_version=bundle.version)
    def make(name):
        db=Ledger(a.runtime/(name+"-"+uuid.uuid4().hex[:8]+".sqlite"))
        db.register_source(first["source_sha256"],{"dataset":"real reduced fixture","arrival":"synthetic next midnight"})
        db.ingest("fixture",first["source_sha256"],0,events);jid=db.submit("job",spec)["job_id"]
        return db,jid
    clean,jid=make("clean");worker=Worker(clean,bundle);worker.run_once();expected=semantic(clean.result(jid))
    rows=[]
    for phase,code in [("process_exit_before_commit",93),("process_exit_after_commit",94)]:
        for repetition in range(2):
            db,jid=make(phase);start=time.perf_counter()
            child=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--child",phase,"--db",str(db.path)],capture_output=True,timeout=30)
            if child.returncode!=code:raise RuntimeError(child.stderr.decode()+child.stdout.decode())
            crash_finished=time.perf_counter();post_crash=db.counters();status=db.status(jid)
            if phase=="process_exit_before_commit":
                assert post_crash["results"]==0 and post_crash["feature_ledger"]==0 and status["state"]=="running"
                recover=Worker(Ledger(db.path),bundle);deadline=time.monotonic()+4
                while not recover.run_once():
                    if time.monotonic()>deadline:raise TimeoutError("lease recovery")
                    time.sleep(.01)
            else:assert post_crash["results"]==1 and post_crash["feature_ledger"]==1 and status["state"]=="succeeded"
            result=db.result(jid);equal=semantic(result)==expected
            assert equal and db.counters()["results"]==1
            rows.append({"phase":phase,"repetition":repetition,"process_exit_code":code,"recovery_seconds_after_process_exit":time.perf_counter()-crash_finished,"total_seconds_including_child_startup":time.perf_counter()-start,"post_crash_counts":post_crash,"final_attempt":db.status(jid)["attempt"],"semantic_equivalence_to_clean_run":equal,"result_semantic_sha256":digest(semantic(result))})
    atomic_json(BASE/"artifacts/recovery_receipt.json",{"lease_seconds":1.,"trials":rows,"all_semantically_equal":all(r["semantic_equivalence_to_clean_run"] for r in rows),"scope":"actual abrupt Python process exits around SQLite result commit; clean versus crash/restart outputs excluding run identifiers; one Windows host; no distributed failover claim"})
    print(json.dumps(rows,indent=2))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--runtime",type=Path);p.add_argument("--child");p.add_argument("--db",type=Path);run(p.parse_args())
