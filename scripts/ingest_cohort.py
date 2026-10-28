"""Materialize every selected real record through the typed durable ingestion path.
Arrival times are a declared synthetic next-midnight schedule, never original data.
"""
import argparse,json,time,sqlite3,platform
from datetime import date,timedelta,datetime,timezone
from pathlib import Path
import duckdb
from stockout.common import atomic_json,file_hash
from stockout.ledger import Ledger

BASE=Path(__file__).resolve().parents[1]
def main(a):
    t=time.perf_counter();manifest=json.loads((BASE/"artifacts/model_manifest.json").read_text())
    hashes=json.loads((BASE/"protocol.json").read_text())["source"]
    con=duckdb.connect();con.execute("set threads=2")
    frame=con.execute("select * from read_parquet(?) order by dt,store_id,product_id",[str(a.cohort)]).fetchdf()
    db=Ledger(a.db)
    for split in ["train","eval"]:
        db.register_source(hashes[split+"_sha256"],{"dataset":"Dingdong-Inc/FreshRetailNet-LT","license":"CC-BY-4.0","arrival_timestamps":"synthetic fixture only"})
    counts={"accepted":0,"duplicates":0,"quarantined":0,"received":0};replay_probes=[]
    for split in ["train","eval"]:
        sub=frame[frame.dt<="2025-07-13"] if split=="train" else frame[frame.dt>="2025-07-14"]
        sha=hashes[split+"_sha256"];events=[];offset=0
        def flush(events,offset):
            bid=f"cohort-{split}-{offset:08d}"
            receipt=db.ingest(bid,sha,offset,events)
            for k in counts:counts[k]+=receipt[k]
            if offset==0 or offset+len(events)==len(sub):replay_probes.append((bid,sha,offset,events))
        for row in sub.itertuples():
            events.append({"source_sha256":sha,"store_id":int(row.store_id),"product_id":int(row.product_id),"event_date":row.dt,
                "arrived_at":(date.fromisoformat(row.dt)+timedelta(days=1)).isoformat()+"T00:00:00Z",
                "sale_amount":float(row.sale_amount),"hours_sale":row.hours_sale.tolist(),"hours_stock_status":row.hours_stock_status.tolist(),
                "oos_hours":int(row.stock_hour6_22_cnt),"arrival_kind":"synthetic_next_midnight"})
            if len(events)==1000:flush(events,offset);offset+=len(events);events=[]
        if events:flush(events,offset)
    seconds=time.perf_counter()-t;before=db.state_digest()
    for bid,sha,offset,events in replay_probes:assert db.ingest(bid,sha,offset,events)["replayed"]
    after=db.state_digest();assert before==after
    with db.connect() as c:
        actual_count,actual_sum=c.execute("select count(*),sum(sale_amount) from events").fetchone()
        bysource=[dict(r) for r in c.execute("select source_sha256,count(*) rows,sum(sale_amount) normalized_sales_sum from events group by source_sha256")]
        checkpoints=[dict(r) for r in c.execute("select sha256,next_offset from sources order by sha256")]
        integrity=[row[0] for row in c.execute("pragma integrity_check")]
        foreign_keys=c.execute("pragma foreign_key_check").fetchall()
        journal_mode=c.execute("pragma journal_mode").fetchone()[0]
        synchronization=c.execute("pragma synchronous").fetchone()[0]
        if integrity!=["ok"] or foreign_keys or journal_mode!="delete" or synchronization!=2:
            raise RuntimeError("durable ledger integrity/journal contract failed")
    source_sum=float(frame.sale_amount.sum());delta=float(actual_sum-source_sum)
    assert actual_count==len(frame) and abs(delta)<1e-6 and counts["quarantined"]==0
    out={"cohort_rows":len(frame),"derived_cohort_sha256":file_hash(a.cohort),"source_manifest_hashes":manifest["source_hashes"],
         "ingestion_counts":counts,"durable_rows":actual_count,"source_normalized_sales_sum":source_sum,"durable_normalized_sales_sum":actual_sum,
         "conservation_absolute_delta":abs(delta),"source_checkpoints":checkpoints,"by_source":bysource,"logical_state_sha256":before,
         "replay_probe_batches":len(replay_probes),"replay_unchanged":before==after,"sqlite_integrity":integrity[0],"foreign_key_violations":len(foreign_keys),"journal_mode":journal_mode,"synchronous":synchronization,"sqlite_version":sqlite3.sqlite_version,"executed_utc":datetime.now(timezone.utc).isoformat(),"platform":platform.platform(),
         "seconds":seconds,"records_per_second":len(frame)/seconds,"database_bytes":a.db.stat().st_size,
         "arrival_policy":"SYNTHETIC next UTC midnight following operational date; source contains no actual arrival timestamps",
         "checkpoint_scope":"offsets in deterministic projected-cohort stream per immutable raw-source hash, not original parquet physical row offsets"}
    atomic_json(BASE/"artifacts/ledger_ingestion_receipt.json",out);print(json.dumps({"completed":True,**out}))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--cohort",type=Path,required=True);p.add_argument("--db",type=Path,required=True);main(p.parse_args())
