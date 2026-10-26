# Run the included attributed fixture through a local API.
import argparse,json,time
from pathlib import Path
from urllib.parse import urlparse
import httpx
BASE=Path(__file__).resolve().parents[1]
def main(url):
    if urlparse(url).hostname not in ['127.0.0.1','localhost','::1']:raise ValueError('demo client is intended for loopback only')
    events=json.loads((BASE/'fixtures/real_history.json').read_text())['events']
    with httpx.Client(base_url=url,timeout=15,trust_env=False) as c:
        version=c.get('/v1/models').json()['model_version']
        r=c.post('/v1/batches',json={'batch_id':'demo-history-v1','source_sha256':events[0]['source_sha256'],'start_offset':0,'events':events});r.raise_for_status()
        keys=sorted({(e['store_id'],e['product_id']) for e in events})
        req={'series':[{'store_id':s,'product_id':p} for s,p in keys],'target_date':'2025-05-01','as_of':'2025-05-01T00:00:00Z','model_version':version,'capacity_steps':40}
        r=c.post('/v1/jobs',json=req,headers={'Idempotency-Key':'demo-'+version});r.raise_for_status();jid=r.json()['job_id'];deadline=time.monotonic()+30
        while True:
            state=c.get(f'/v1/jobs/{jid}').json()
            if state['state']=='succeeded':break
            if state['state']=='failed' or time.monotonic()>deadline:raise RuntimeError(str(state))
            time.sleep(.05)
        r=c.get(f'/v1/jobs/{jid}/result');r.raise_for_status();print(json.dumps(r.json(),indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765');main(p.parse_args().url)
