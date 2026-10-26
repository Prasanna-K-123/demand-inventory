# Actual current-version HTTP correctness smoke, separate from prior performance receipts.
import argparse,json,os,socket,subprocess,sys,time,uuid,math
from pathlib import Path
import httpx,numpy as np
from stockout.common import atomic_json
from stockout.model import ModelBundle
from stockout.features import served_features
from stockout.decisions import allocate
from benchmark import stop_owned_server
BASE=Path(__file__).resolve().parents[1]
def run(runtime):
    runtime.mkdir(parents=True,exist_ok=True);bundle=ModelBundle(BASE/'artifacts')
    fixture=json.loads((BASE/'fixtures/real_history.json').read_text())['events'];keys=sorted({(e['store_id'],e['product_id']) for e in fixture})
    run_id='smoke-'+uuid.uuid4().hex[:10];db=runtime/('benchmark-'+run_id+'.sqlite')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=os.environ.copy();env['PYTHONPATH']=str(BASE/'src')
    with (runtime/(run_id+'.log')).open('w',encoding='utf-8') as log:
        proc=subprocess.Popen([sys.executable,str(BASE/'scripts/serve.py'),'--db',str(db),'--port',str(port)],env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=10,trust_env=False) as client:
                deadline=time.monotonic()+30
                while True:
                    try:
                        if client.get('/health').status_code==200:break
                    except httpx.HTTPError:pass
                    if proc.poll() is not None or time.monotonic()>deadline:raise RuntimeError('server startup failed')
                    time.sleep(.05)
                r=client.post('/v1/batches',json={'batch_id':'fixture','source_sha256':fixture[0]['source_sha256'],'start_offset':0,'events':fixture});r.raise_for_status();assert r.json()['accepted']==56
                req={'series':[{'store_id':s,'product_id':p} for s,p in keys],'target_date':'2025-05-01','as_of':'2025-05-01T00:00:00Z','model_version':bundle.version,'capacity_steps':40}
                r=client.post('/v1/jobs',json=req,headers={'Idempotency-Key':'smoke-job'});r.raise_for_status();jid=r.json()['job_id']
                assert client.post('/v1/jobs',json=req,headers={'Idempotency-Key':'smoke-job'}).json()['job_id']==jid
                deadline=time.monotonic()+15
                while True:
                    status=client.get(f'/v1/jobs/{jid}').json()
                    if status['state']=='succeeded':break
                    if status['state']=='failed' or time.monotonic()>deadline:raise RuntimeError(str(status))
                    time.sleep(.01)
                result=client.get(f'/v1/jobs/{jid}/result').json()
                features=[served_features([e for e in fixture if (e['store_id'],e['product_id'])==(s,p)],'2025-05-01','2025-05-01T00:00:00Z') for s,p in keys]
                predicted=bundle.predict(features)
                forecast_error=max(abs(r[k]-e[k]) for r,e in zip(result['predictions'],predicted) for k in ['point','lower','upper'])
                scenarios=[[e['scenario_low'],e['point'],e['scenario_high']] for e in predicted]
                caps=[min(100,math.ceil(1.5*max(e['scenario_high'],.1)/.1)) for e in predicted]
                direct=allocate(scenarios,40,caps=caps)
                same=all(result['allocation'][k]==direct[k] for k in ['quantity_steps','caps','used_steps','objective'])
                assert forecast_error==0 and same and result['allocation']['scenario_values']==scenarios
                assert result['model_version']==bundle.version and result['monitoring']['model_version']==bundle.version
                receipt={'run_id':run_id,'model_version':bundle.version,'served_configuration_sha256':bundle.manifest['served_configuration_sha256'],'http_transport':'actual IPv4 loopback','fixture_records':56,'series':len(keys),'idempotent_submission':True,'forecast_max_absolute_error':forecast_error,'allocation_identical':same,'monitoring_version_bound':True,'status':'passed','scope':'correctness smoke after expired-failure fencing repair; prior 200-job performance receipt retains its measured version'}
                atomic_json(BASE/'artifacts/http_smoke.json',receipt);atomic_json(BASE/'artifacts/demo_result.json',result);print(json.dumps(receipt,indent=2))
        finally:
            stop_owned_server(run_id)
            if proc.poll() is None:proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,required=True);run(p.parse_args().runtime)
