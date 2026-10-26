"""SQLite WAL ledger: atomic ingest/checkpoint, fenced leases, atomic publish.
This is a one-machine application, not a distributed exactly-once claim.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import json,sqlite3,time,uuid,os
from pathlib import Path
from pydantic import ValidationError
from .common import canonical,digest
from .contracts import SaleEvent,JobRequest
from .features import FEATURE_VERSION

class Conflict(ValueError):pass
class Busy(RuntimeError):pass
class LeaseLost(RuntimeError):pass
class InjectedFault(RuntimeError):pass

def log(event,**fields):
    print(canonical({"event":event,"utc":datetime.now(timezone.utc).isoformat(),**fields}),flush=True)

SCHEMA="""
CREATE TABLE IF NOT EXISTS sources(sha256 TEXT PRIMARY KEY,metadata_json TEXT NOT NULL,next_offset INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT NOT NULL UNIQUE,source_sha256 TEXT NOT NULL REFERENCES sources(sha256),store_id INTEGER NOT NULL,product_id INTEGER NOT NULL,event_date TEXT NOT NULL,arrived_at TEXT NOT NULL,sale_amount REAL NOT NULL,oos_hours INTEGER NOT NULL,payload_hash TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_history ON events(store_id,product_id,event_date,arrived_at);
CREATE TABLE IF NOT EXISTS batches(batch_id TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL REFERENCES sources(sha256),payload_hash TEXT NOT NULL,start_offset INTEGER NOT NULL,end_offset INTEGER NOT NULL,accepted INTEGER NOT NULL,duplicates INTEGER NOT NULL,quarantined INTEGER NOT NULL,receipt_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quarantine(id INTEGER PRIMARY KEY AUTOINCREMENT,batch_id TEXT NOT NULL,row_index INTEGER NOT NULL,event_key TEXT,reason TEXT NOT NULL,payload_hash TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,spec_hash TEXT NOT NULL,spec_json TEXT NOT NULL,model_version TEXT NOT NULL,feature_version TEXT NOT NULL,snapshot_seq INTEGER NOT NULL,monitoring_json TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed')),created_at REAL NOT NULL,attempt INTEGER NOT NULL DEFAULT 0,lease_owner TEXT,lease_token INTEGER NOT NULL DEFAULT 0,lease_until REAL,error TEXT);
CREATE TABLE IF NOT EXISTS feature_ledger(job_id TEXT NOT NULL REFERENCES jobs(job_id),series_key TEXT NOT NULL,feature_version TEXT NOT NULL,feature_hash TEXT NOT NULL,history_hash TEXT NOT NULL,feature_json TEXT NOT NULL,PRIMARY KEY(job_id,series_key));
CREATE TABLE IF NOT EXISTS results(job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),run_id TEXT NOT NULL,model_version TEXT NOT NULL,feature_version TEXT NOT NULL,result_hash TEXT NOT NULL,result_json TEXT NOT NULL,published_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS forecasts(job_id TEXT NOT NULL REFERENCES jobs(job_id),store_id INTEGER NOT NULL,product_id INTEGER NOT NULL,target_date TEXT NOT NULL,issued_as_of TEXT NOT NULL,point REAL,lower_bound REAL,upper_bound REAL,policy TEXT NOT NULL,PRIMARY KEY(job_id,store_id,product_id));
"""
class Ledger:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL");c.execute("PRAGMA synchronous=FULL");c.executescript(SCHEMA)
            columns={r[1] for r in c.execute("PRAGMA table_info(jobs)")}
            if "monitoring_json" not in columns:
                if c.execute("select count(*) from jobs").fetchone()[0]:
                    raise ValueError("legacy jobs lack frozen monitoring state; use a fresh database or explicit migration")
                c.execute("ALTER TABLE jobs ADD COLUMN monitoring_json TEXT NOT NULL DEFAULT '{}'")
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=15,isolation_level=None)
        c.row_factory=sqlite3.Row;c.execute("PRAGMA foreign_keys=ON");c.execute("PRAGMA busy_timeout=15000");c.execute("PRAGMA synchronous=FULL")
        try:
            yield c
            if c.in_transaction:c.commit()
        except BaseException:
            if c.in_transaction:c.rollback()
            raise
        finally:c.close()
    def register_source(self,sha,metadata):
        body=canonical(metadata)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=c.execute("select metadata_json from sources where sha256=?",(sha,)).fetchone()
            if old and old[0]!=body:raise Conflict("immutable source manifest conflict")
            c.execute("insert or ignore into sources(sha256,metadata_json) values(?,?)",(sha,body))
    def ingest(self,batch_id,source_sha256,start_offset,records,fault=None):
        if not 1<=len(records)<=1000:raise ValueError("batch limit is 1..1000 records")
        payload_hash=digest({"source":source_sha256,"start_offset":start_offset,"events":records})
        counts={"accepted":0,"duplicates":0,"quarantined":0}
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=c.execute("select payload_hash,receipt_json from batches where batch_id=?",(batch_id,)).fetchone()
            if old:
                if old[0]!=payload_hash:raise Conflict("batch id reused with different payload")
                receipt=json.loads(old[1]);receipt["replayed"]=True;return receipt
            source=c.execute("select next_offset from sources where sha256=?",(source_sha256,)).fetchone()
            if source is None:raise Conflict("unregistered source")
            if int(source[0])!=start_offset:raise Conflict("noncontiguous source checkpoint")
            for i,raw in enumerate(records):
                raw_json=canonical(raw);raw_hash=digest(raw);event_key=None;reason=None
                try:
                    event=SaleEvent.model_validate(raw)
                    if event.source_sha256!=source_sha256:raise ValueError("batch/event source mismatch")
                    event_key=event.key;obj=event.model_dump(mode="json");encoded=canonical(obj);eh=digest(obj)
                    oldevent=c.execute("select payload_hash from events where event_key=?",(event_key,)).fetchone()
                    if oldevent:
                        if oldevent[0]==eh:counts["duplicates"]+=1;continue
                        reason="conflicting immutable event"
                    else:
                        c.execute("insert into events(event_key,source_sha256,store_id,product_id,event_date,arrived_at,sale_amount,oos_hours,payload_hash,payload_json) values(?,?,?,?,?,?,?,?,?,?)",(event_key,source_sha256,event.store_id,event.product_id,event.event_date.isoformat(),event.arrived_at.isoformat(),event.sale_amount,event.oos_hours,eh,encoded))
                        counts["accepted"]+=1;continue
                except (ValidationError,ValueError,TypeError) as e:reason=str(e)[:1000]
                counts["quarantined"]+=1
                c.execute("insert into quarantine(batch_id,row_index,event_key,reason,payload_hash,payload_json) values(?,?,?,?,?,?)",(batch_id,i,event_key,reason,raw_hash,raw_json))
            end_offset=start_offset+len(records)
            receipt={"batch_id":batch_id,"source_sha256":source_sha256,"start_offset":start_offset,"end_offset":end_offset,"received":len(records),**counts,"replayed":False}
            assert len(records)==sum(counts.values())
            c.execute("insert into batches values(?,?,?,?,?,?,?,?,?)",(batch_id,source_sha256,payload_hash,start_offset,end_offset,counts["accepted"],counts["duplicates"],counts["quarantined"],canonical(receipt)))
            c.execute("update sources set next_offset=? where sha256=?",(end_offset,source_sha256))
            if fault=="process_exit_before_commit":os._exit(91)
            if fault=="before_commit":raise InjectedFault("ingest before commit")
        if fault=="process_exit_after_commit":os._exit(92)
        if fault=="after_commit":raise InjectedFault("ingest after commit")
        log("batch_committed",run_id=batch_id,**counts,checkpoint=end_offset)
        return receipt
    def submit(self,key,spec:JobRequest,max_queue=256):
        body=canonical(spec.model_dump(mode="json"));sh=digest(spec.model_dump(mode="json"))
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=c.execute("select * from jobs where idempotency_key=?",(key,)).fetchone()
            if old:
                if old["spec_hash"]!=sh:raise Conflict("idempotency key reused with different request")
                return {"job_id":old["job_id"],"state":old["state"],"deduplicated":True}
            active=c.execute("select count(*) from jobs where state in ('queued','running')").fetchone()[0]
            if active>=max_queue:raise Busy("bounded job queue full")
            snapshot=c.execute("select coalesce(max(seq),0) from events").fetchone()[0]
            monitor=self._monitoring(c,spec.as_of.isoformat(),snapshot,spec.model_version,FEATURE_VERSION)
            jid=uuid.uuid4().hex
            c.execute("insert into jobs(job_id,idempotency_key,spec_hash,spec_json,model_version,feature_version,snapshot_seq,monitoring_json,state,created_at) values(?,?,?,?,?,?,?,?,'queued',?)",(jid,key,sh,body,spec.model_version,FEATURE_VERSION,snapshot,canonical(monitor),time.time()))
        log("job_submitted",run_id=jid,model_version=spec.model_version,snapshot_seq=snapshot)
        return {"job_id":jid,"state":"queued","deduplicated":False}
    def claim(self,owner,now=None,lease_seconds=30):
        now=time.time() if now is None else now
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("select * from jobs where state='queued' or (state='running' and lease_until<=?) order by created_at,job_id limit 1",(now,)).fetchone()
            if row is None:return None
            c.execute("update jobs set state='running',lease_owner=?,lease_token=lease_token+1,lease_until=?,attempt=attempt+1,error=NULL where job_id=?",(owner,now+lease_seconds,row["job_id"]))
            job=dict(c.execute("select * from jobs where job_id=?",(row["job_id"],)).fetchone())
        log("job_claimed",run_id=job["job_id"],attempt=job["attempt"],lease_token=job["lease_token"])
        return job
    def rows_for(self,store,product,target,as_of,snapshot_seq):
        begin=(datetime.fromisoformat(target)-timedelta(days=28)).date().isoformat()
        with self.connect() as c:
            rows=c.execute("select * from events where store_id=? and product_id=? and event_date>=? and event_date<? and arrived_at<=? and seq<=? order by event_date",(store,product,begin,target,as_of,snapshot_seq)).fetchall()
            return [dict(r) for r in rows]
    def monitoring(self,as_of,snapshot_seq=None,model_version=None,feature_version=FEATURE_VERSION):
        with self.connect() as c:
            return self._monitoring(c,as_of,snapshot_seq,model_version,feature_version)
    def _monitoring(self,c,as_of,snapshot_seq=None,model_version=None,feature_version=FEATURE_VERSION):
        limit=2**63-1 if snapshot_seq is None else snapshot_seq
        rows=c.execute("""with eligible as (
            select f.point,f.lower_bound,f.upper_bound,e.sale_amount,f.target_date,
            row_number() over(partition by f.store_id,f.product_id,f.target_date order by f.issued_as_of desc,j.created_at desc,f.job_id desc) chosen
            from forecasts f join jobs j on j.job_id=f.job_id join events e on e.store_id=f.store_id and e.product_id=f.product_id and e.event_date=f.target_date
            where e.arrived_at<=? and f.issued_as_of<=? and e.seq<=? and f.point is not null
              and (? is null or j.model_version=?) and j.feature_version=?)
            select * from eligible where chosen=1 order by target_date desc limit 1000""",(as_of,as_of,limit,model_version,model_version,feature_version)).fetchall()
        scope={"model_version":model_version,"feature_version":feature_version,"policy_version":"unique-label-coverage-v2","threshold":"fallback if >=30 labelled forecasts and coverage<0.60"}
        if not rows:return {"available_labels":0,"coverage80":None,"mae":None,"policy":"insufficient_labels",**scope}
        valid=[r for r in rows if r["lower_bound"] is not None and r["upper_bound"] is not None]
        coverage=sum(r["lower_bound"]<=r["sale_amount"]<=r["upper_bound"] for r in valid)/len(valid) if valid else None
        policy="fallback_seasonal_restrict_allocation" if len(valid)>=30 and coverage<.60 else "normal" if len(valid)>=30 else "insufficient_labels"
        return {"available_labels":len(rows),"interval_labels":len(valid),"coverage80":coverage,"mae":sum(abs(r["point"]-r["sale_amount"]) for r in rows)/len(rows),"policy":policy,**scope}
    def publish(self,job,owner,result,features,fault=None,now=None):
        now=time.time() if now is None else now
        rh=digest(result);result={**result,"result_hash":rh}
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            live=c.execute("select * from jobs where job_id=?",(job["job_id"],)).fetchone()
            if not live or live["state"]!="running" or live["lease_owner"]!=owner or live["lease_token"]!=job["lease_token"] or live["lease_until"]<=now:raise LeaseLost("stale worker cannot publish")
            for f in features:
                c.execute("insert into feature_ledger values(?,?,?,?,?,?)",(job["job_id"],f["series_key"],FEATURE_VERSION,f["feature_hash"],f["history_hash"],canonical(f["features"])))
            c.execute("insert into results values(?,?,?,?,?,?,?)",(job["job_id"],result["run_id"],job["model_version"],FEATURE_VERSION,rh,canonical(result),now))
            for r in result["predictions"]:
                c.execute("insert into forecasts values(?,?,?,?,?,?,?,?,?)",(job["job_id"],r["store_id"],r["product_id"],r["target_date"],result["as_of"],r["point"],r["lower"],r["upper"],r["policy"]))
            c.execute("update jobs set state='succeeded',lease_owner=NULL,lease_until=NULL where job_id=?",(job["job_id"],))
            if fault=="process_exit_before_commit":os._exit(93)
            if fault=="before_commit":raise InjectedFault("publish before commit")
        if fault=="process_exit_after_commit":os._exit(94)
        if fault=="after_commit":raise InjectedFault("publish after commit")
        log("job_published",run_id=job["job_id"],result_hash=rh,items=len(result["predictions"]))
        return result
    def fail(self,job,owner,message,now=None):
        now=time.time() if now is None else now
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            updated=c.execute("update jobs set state='failed',error=?,lease_owner=NULL,lease_until=NULL where job_id=? and state='running' and lease_owner=? and lease_token=? and lease_until>?",(message[:500],job["job_id"],owner,job["lease_token"],now))
            return updated.rowcount==1
    def status(self,jid):
        with self.connect() as c:
            r=c.execute("select job_id,state,attempt,model_version,feature_version,snapshot_seq,error from jobs where job_id=?",(jid,)).fetchone()
            return dict(r) if r else None
    def result(self,jid):
        with self.connect() as c:
            r=c.execute("select result_json from results where job_id=?",(jid,)).fetchone()
            return json.loads(r[0]) if r else None
    def counters(self):
        with self.connect() as c:
            counts={name:c.execute("select count(*) from "+name).fetchone()[0] for name in ["events","batches","quarantine","jobs","results","feature_ledger"]}
            counts["states"]={r[0]:r[1] for r in c.execute("select state,count(*) from jobs group by state").fetchall()}
            return counts
    def state_digest(self):
        """Logical event/batch/quarantine state; excludes machine/run timing."""
        with self.connect() as c:
            state={"events":[dict(r) for r in c.execute("select event_key,payload_hash from events order by event_key")],"batches":[dict(r) for r in c.execute("select batch_id,payload_hash,start_offset,end_offset,accepted,duplicates,quarantined from batches order by batch_id")],"sources":[dict(r) for r in c.execute("select sha256,next_offset from sources order by sha256")],"quarantine":[dict(r) for r in c.execute("select batch_id,row_index,reason,payload_hash from quarantine order by batch_id,row_index")]}
        return digest(state)
