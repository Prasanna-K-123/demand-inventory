import argparse,os
from pathlib import Path
import uvicorn
from stockout.api import create_app

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--db",type=Path,default=Path("runtime/ledger.sqlite"));p.add_argument("--port",type=int,default=8765);a=p.parse_args()
    base=Path(__file__).resolve().parents[1]
    # Loopback binding is deliberate. Authentication/TLS/rate limiting are not implemented.
    uvicorn.run(create_app(a.db,base/"artifacts"),host="127.0.0.1",port=a.port,log_level="warning",access_log=False)
