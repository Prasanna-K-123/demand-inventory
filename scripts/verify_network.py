"""Bounded driver for environments where loopback is authorized."""
import os,subprocess,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
if __name__=="__main__":
    runtime=Path(sys.argv[1]).resolve();runtime.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env["PYTHONPATH"]=str(BASE/"src");env["PYTHONUTF8"]="1"
    for n in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"]:env[n]="2"
    for cmd,timeout,name in [([sys.executable,"-m","pytest",str(BASE/"tests"),"-q","--junitxml="+str(BASE/"artifacts/tests.xml"),"-o","faulthandler_timeout=20"],120,"tests"),([sys.executable,str(BASE/"scripts/benchmark.py"),"--runtime",str(runtime)],240,"benchmark")]:
        with (runtime/(name+"-execution.log")).open("w",encoding="utf-8") as f:
            try:r=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
            except subprocess.TimeoutExpired:
                print(name,"timed out",flush=True);raise
        print(name,"exit",r.returncode,flush=True)
        if r.returncode:print((runtime/(name+"-execution.log")).read_text());raise SystemExit(r.returncode)
    print("network verification complete",flush=True)
