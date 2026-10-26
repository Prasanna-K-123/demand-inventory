# Bounded final correctness checks, without repeating performance measurement.
import os,subprocess,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
runtime=Path(sys.argv[1]).resolve();runtime.mkdir(parents=True,exist_ok=True)
env=os.environ.copy();env['PYTHONPATH']=str(BASE/'src');env['PYTHONUTF8']='1'
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:env[name]='2'
for name,cmd,timeout in [('final-tests',[sys.executable,'-m','pytest',str(BASE/'tests'),'-q','--junitxml='+str(BASE/'artifacts/tests.xml'),'-o','faulthandler_timeout=20'],120),('final-http-smoke',[sys.executable,str(BASE/'scripts/http_smoke.py'),'--runtime',str(runtime)],90)]:
    path=runtime/(name+'.log')
    with path.open('w',encoding='utf-8') as f:r=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    print(name,'exit',r.returncode,flush=True)
    if r.returncode:print(path.read_text());raise SystemExit(r.returncode)
