"""Local-loopback API; request handlers never fit models or run inference."""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime,timezone
import re
from fastapi import FastAPI,HTTPException,Header,Query
from starlette.responses import JSONResponse
from .contracts import BatchRequest,JobRequest,JobStatus,JobSubmission,JobResult,SaleEvent
from .ledger import Ledger,Conflict,Busy
from .model import ModelBundle
from .worker import Worker

class BodyLimitMiddleware:
    def __init__(self,app,limit=1_048_576):self.app=app;self.limit=limit
    async def __call__(self,scope,receive,send):
        if scope["type"]!="http":return await self.app(scope,receive,send)
        headers=dict(scope.get("headers",[]))
        try:declared=int(headers.get(b"content-length",b"0"))
        except ValueError:declared=self.limit+1
        if declared>self.limit:
            return await JSONResponse({"detail":"request body exceeds 1 MiB"},status_code=413)(scope,receive,send)
        body=bytearray()
        while True:
            message=await receive()
            if message["type"]=="http.disconnect":return
            body.extend(message.get("body",b""))
            if len(body)>self.limit:return await JSONResponse({"detail":"request body exceeds 1 MiB"},status_code=413)(scope,receive,send)
            if not message.get("more_body",False):break
        done=False
        async def replay():
            nonlocal done
            if not done:done=True;return {"type":"http.request","body":bytes(body),"more_body":False}
            return await receive()
        await self.app(scope,replay,send)

def create_app(db_path,artifact_dir,start_worker=True):
    ledger=Ledger(db_path);bundle=ModelBundle(artifact_dir)
    for sha in bundle.manifest["source_hashes"]:
        ledger.register_source(sha,{"dataset":"Dingdong-Inc/FreshRetailNet-LT","license":"CC-BY-4.0","arrival_timestamps":"synthetic fixture only"})
    worker=Worker(ledger,bundle)
    @asynccontextmanager
    async def lifespan(app):
        if start_worker:worker.start()
        yield
        if start_worker:worker.stop()
    app=FastAPI(title="Stockout-aware operational decision platform",version="0.1.0",lifespan=lifespan,
                description="Executed local research prototype. Observed normalized sales; synthetic arrivals and capacity costs. Not a production or latent-demand service.")
    app.add_middleware(BodyLimitMiddleware)
    app.state.ledger=ledger;app.state.worker=worker;app.state.bundle=bundle
    @app.get("/health")
    def health():return {"status":"ok","model_version":bundle.version,"worker_threads":int(start_worker),"maturity":"local research prototype"}
    @app.get("/v1/models")
    def models():return bundle.manifest
    @app.get("/v1/contracts/event")
    def contract():return SaleEvent.model_json_schema()
    @app.post("/v1/batches")
    def ingest(batch:BatchRequest):
        try:return ledger.ingest(batch.batch_id,batch.source_sha256,batch.start_offset,batch.events)
        except Conflict as e:raise HTTPException(409,str(e)) from e
        except (ValueError,TypeError) as e:raise HTTPException(422,str(e)) from e
    @app.post("/v1/jobs",response_model=JobSubmission,status_code=202)
    def submit(spec:JobRequest,idempotency_key:str=Header(min_length=1,max_length=80)):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+",idempotency_key):raise HTTPException(422,"invalid idempotency key")
        if spec.model_version!=bundle.version:raise HTTPException(409,"requested model version is unavailable")
        if spec.target_date.isoformat()<"2025-05-01":raise HTTPException(422,"model and calibration artifact not available as-of requested date")
        try:return ledger.submit(idempotency_key,spec)
        except Conflict as e:raise HTTPException(409,str(e)) from e
        except Busy as e:raise HTTPException(429,str(e)) from e
    @app.get("/v1/jobs/{job_id}",response_model=JobStatus)
    def status(job_id:str):
        value=ledger.status(job_id)
        if value is None:raise HTTPException(404,"unknown job")
        return value
    @app.get("/v1/jobs/{job_id}/result",response_model=JobResult)
    def result(job_id:str):
        value=ledger.result(job_id)
        if value is None:
            if ledger.status(job_id) is None:raise HTTPException(404,"unknown job")
            raise HTTPException(409,"job has no published result")
        return value
    @app.get("/v1/metrics")
    def metrics(as_of:datetime=Query()):
        if as_of.tzinfo is None:raise HTTPException(422,"as_of requires timezone")
        return {"ledger":ledger.counters(),"monitoring":ledger.monitoring(as_of.astimezone(timezone.utc).isoformat(),model_version=bundle.version)}
    return app
