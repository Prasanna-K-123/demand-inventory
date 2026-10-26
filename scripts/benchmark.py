"""Actual HTTP loopback benchmark. No external network call or paid service."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import argparse,json,os,platform,socket,subprocess,sys,threading,time,uuid,math
from pathlib import Path
import httpx,numpy as np,psutil
from stockout.common import atomic_json
from stockout.features import served_features
from stockout.model import ModelBundle
from stockout.decisions import allocate

BASE=Path(__file__).resolve().parents[1]
def percentiles(values):
    return {"n":len(values),"p50_ms":float(np.quantile(values,.5)),"p95_ms":float(np.quantile(values,.95)),"p99_ms":float(np.quantile(values,.99)),"max_ms":max(values)}
def stop_owned_server(run_id):
    # Match only a server created by this benchmark, including its unique database name.
    for proc in psutil.process_iter(["pid","cmdline"],ad_value=None):
        cmd=proc.info.get("cmdline") or []
        match_script=any(arg.replace("\\","/").endswith("/stockout-decision-platform/scripts/serve.py") for arg in cmd)
        match_run=any(("benchmark-"+run_id+".sqlite") in arg for arg in cmd)
        if match_script and match_run:
            try:
                children=proc.children(recursive=True)
                for child in children:child.terminate()
                proc.terminate();psutil.wait_procs(children+[proc],timeout=5)
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass

def run(a):
    prior=BASE/"artifacts/benchmark.json"
    if prior.exists():stop_owned_server(json.loads(prior.read_text())["run_id"])
    a.runtime.mkdir(parents=True,exist_ok=True)
    fixture=json.loads((BASE/"fixtures/real_history.json").read_text())["events"]
    keys=sorted({(e["store_id"],e["product_id"]) for e in fixture})
    if not keys:raise RuntimeError("no real history fixture")
    bundle=ModelBundle(BASE/"artifacts");version=bundle.version
    feature=served_features([e for e in fixture if (e["store_id"],e["product_id"])==keys[0]],"2025-05-01","2025-05-01T00:00:00Z")
    expected=bundle.predict([feature])[0]
    run_id=uuid.uuid4().hex[:12];db=a.runtime/f"benchmark-{run_id}.sqlite"
    with socket.socket() as s:s.bind(("127.0.0.1",0));port=s.getsockname()[1]
    url=f"http://127.0.0.1:{port}";env=os.environ.copy();env["PYTHONPATH"]=str(BASE/"src")
    for name in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"]:env[name]="2"
    logpath=a.runtime/f"server-{run_id}.log";log=logpath.open("w",encoding="utf-8")
    server=subprocess.Popen([sys.executable,str(BASE/"scripts/serve.py"),"--db",str(db),"--port",str(port)],env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    stop=threading.Event();memory=[];process_counts=[];errors=[]
    def sampler():
        while not stop.wait(.02):
            try:
                parent=psutil.Process(server.pid);processes=[parent]+parent.children(recursive=True)
                memory.append(sum(proc.memory_info().rss for proc in processes)/1024**2);process_counts.append(len(processes))
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    thread=threading.Thread(target=sampler,daemon=True);thread.start()
    try:
        with httpx.Client(base_url=url,timeout=10,trust_env=False) as client:
            deadline=time.monotonic()+45
            while True:
                try:
                    if client.get("/health").status_code==200:break
                except httpx.HTTPError:pass
                if server.poll() is not None:raise RuntimeError("server exited: "+logpath.read_text())
                if time.monotonic()>deadline:raise TimeoutError("server startup timed out")
                time.sleep(.05)
            batch={"batch_id":"real-demo-history","source_sha256":fixture[0]["source_sha256"],"start_offset":0,"events":fixture}
            response=client.post("/v1/batches",json=batch);response.raise_for_status();ingestion=response.json()
            if ingestion["accepted"]!=len(fixture):raise RuntimeError("fixture ingestion incomplete")
        request_times={"submit":[],"status":[],"result":[]};job_ms=[];parity_errors=[];lock=threading.Lock()
        spec={"series":[{"store_id":keys[0][0],"product_id":keys[0][1]}],"target_date":"2025-05-01","as_of":"2025-05-01T00:00:00Z","model_version":version}
        def one(client,i,measured=True):
            local={"submit":[],"status":[],"result":[]};start=time.perf_counter()
            t=time.perf_counter();r=client.post("/v1/jobs",json=spec,headers={"Idempotency-Key":f"bench-{run_id}-{i}"});local["submit"].append((time.perf_counter()-t)*1000)
            if r.status_code!=202:raise RuntimeError(f"submission status {r.status_code}: {r.text}")
            jid=r.json()["job_id"];deadline=time.monotonic()+30
            while True:
                t=time.perf_counter();r=client.get(f"/v1/jobs/{jid}");local["status"].append((time.perf_counter()-t)*1000);r.raise_for_status();state=r.json()["state"]
                if state=="succeeded":break
                if state=="failed" or time.monotonic()>deadline:raise RuntimeError("job failed or timed out")
                time.sleep(.005)
            t=time.perf_counter();r=client.get(f"/v1/jobs/{jid}/result");local["result"].append((time.perf_counter()-t)*1000);r.raise_for_status();result=r.json()
            duration=(time.perf_counter()-start)*1000;p=result["predictions"][0]
            err=max(abs(p[k]-expected[k]) for k in ["point","lower","upper"])
            if measured:
                with lock:
                    for k,v in local.items():request_times[k].extend(v)
                    job_ms.append(duration);parity_errors.append(err)
            return result
        # Twenty warm-up jobs are excluded from the fixed 200 measured jobs.
        with httpx.Client(base_url=url,timeout=10,trust_env=False) as client:
            for i in range(20):one(client,f"warm-{i}",False)
        def batch_worker(client_number):
            with httpx.Client(base_url=url,timeout=10,trust_env=False) as client:
                for j in range(50):
                    try:one(client,client_number*50+j)
                    except Exception as e:
                        with lock:errors.append(type(e).__name__+": "+str(e))
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(batch_worker,range(4)))
        elapsed=time.perf_counter()-start
        # Exact same model + feature vector, in-process compute only, excluding durable jobs and HTTP.
        direct=[]
        for _ in range(200):
            t=time.perf_counter();bundle.predict([feature]);direct.append((time.perf_counter()-t)*1000)
        # Multi-series request verifies batching parity and finite-grid allocation through HTTP.
        multikeys=[{"store_id":s,"product_id":p} for s,p in keys]
        with httpx.Client(base_url=url,timeout=10,trust_env=False) as client:
            request={**spec,"series":multikeys,"capacity_steps":40}
            r=client.post("/v1/jobs",json=request,headers={"Idempotency-Key":"multi"});r.raise_for_status();jid=r.json()["job_id"]
            deadline=time.monotonic()+30
            while client.get(f"/v1/jobs/{jid}").json()["state"]!="succeeded":
                if time.monotonic()>deadline:raise TimeoutError("batch job")
                time.sleep(.01)
            multi=client.get(f"/v1/jobs/{jid}/result").json()
            expected_batch=bundle.predict([served_features([e for e in fixture if (e["store_id"],e["product_id"])==(s,p)],"2025-05-01","2025-05-01T00:00:00Z") for s,p in keys])
            batch_error=max(abs(actual[k]-expected_[k]) for actual,expected_ in zip(multi["predictions"],expected_batch) for k in ["point","lower","upper"])
            expected_scenarios=[[e["scenario_low"],e["point"],e["scenario_high"]] for e in expected_batch]
            expected_caps=[min(100,math.ceil(1.5*max(e["scenario_high"],.1)/.1)) for e in expected_batch]
            offline_allocation=allocate(expected_scenarios,40,shortage=3,caps=expected_caps)
            allocation_error=abs(offline_allocation["objective"]-multi["allocation"]["objective"])
            allocation_equal=all(offline_allocation[k]==multi["allocation"][k] for k in ["quantity_steps","caps","used_steps","capacity_steps"])
            scenarios_equal=np.allclose(expected_scenarios,multi["allocation"]["scenario_values"],rtol=0,atol=1e-12)
            assert allocation_equal and scenarios_equal and allocation_error<1e-12
            metrics=client.get("/v1/metrics",params={"as_of":"2025-05-01T00:00:00Z"}).json()
        jobstats=percentiles(job_ms);submitstats=percentiles(request_times["submit"]);statusstats=percentiles(request_times["status"])
        peak=max(memory) if memory else None
        result={"run_id":run_id,"model_version":version,"served_configuration_sha256":bundle.manifest["served_configuration_sha256"],"transport":"real HTTP on IPv4 loopback","load":{"warmup_jobs_excluded":20,"measured_single_series_jobs":200,"concurrent_clients":4,"worker_threads":1,"history":"same real 28-day fixture repeatedly; cache-warm tiny local workload","max_series_contract":64,"model_threads":2},
            "environment":{"os":platform.system(),"os_release":platform.release(),"python":platform.python_version(),"logical_cpus":psutil.cpu_count(logical=True),"physical_cpus":psutil.cpu_count(logical=False),"host_ram_gib":round(psutil.virtual_memory().total/1024**3,2),"shared_machine":True,"hardware_model":"not reliably exposed; no dedicated-machine claim"},
            "completed_jobs":len(job_ms),"errors":errors,"error_rate":len(errors)/200,"elapsed_seconds":elapsed,"jobs_per_second":len(job_ms)/elapsed,
            "job_end_to_end":jobstats,"requests":{k:percentiles(v) for k,v in request_times.items()},"direct_model_compute_only":percentiles(direct),
            "peak_server_process_tree_rss_mb":peak,"max_server_processes":max(process_counts) if process_counts else 0,"memory_sampling_scope":"Windows venv launcher plus all Python server descendants; summed working-set RSS may double-count shared pages","memory_sampling_interval_ms":20,"offline_service_max_absolute_error":max(parity_errors),"multi_series_parity_absolute_error":batch_error,"multi_series_items":len(keys),"allocation_policy_id":multi["allocation"]["policy_id"],"offline_service_allocation_identical":allocation_equal,"offline_service_scenarios_identical":bool(scenarios_equal),"offline_service_allocation_objective_error":allocation_error,
            "slo":{"request_p95_below_250ms":max(submitstats["p95_ms"],statusstats["p95_ms"])<=250,"job_p95_below_2000ms":jobstats["p95_ms"]<=2000,"zero_errors":len(errors)==0,"server_process_tree_rss_below_1500mb":peak is not None and 10<peak<1500},
            "ledger_counts":metrics["ledger"],"limitations":"single machine; warmed repeated history, one active model, no multi-host/load-balancer/failover or sustained production claim; whole-machine peak and client memory excluded"}
        atomic_json(BASE/"artifacts/benchmark.json",result);atomic_json(BASE/"artifacts/demo_result.json",multi)
        print(json.dumps(result,indent=2))
        if errors or max(parity_errors)>1e-10 or batch_error>1e-10:raise RuntimeError("benchmark correctness failure")
    finally:
        stop.set();thread.join(timeout=2);stop_owned_server(run_id)
        if server.poll() is None:server.terminate()
        try:server.wait(timeout=15)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
        log.close()
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--runtime",type=Path,required=True);run(ap.parse_args())
