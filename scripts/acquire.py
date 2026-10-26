"""Acquire public data with a locked byte digest; refuse changed source bytes."""
import argparse,hashlib,json,os
from pathlib import Path
import requests
BASE=Path(__file__).resolve().parents[1]
def main(dest):
    dest.mkdir(parents=True,exist_ok=True)
    protocol=json.loads((BASE/"protocol.json").read_text())
    for split in ["train","eval"]:
        expected=protocol["source"][split+"_sha256"]
        target=dest/f"fresh-lt-{split}.parquet";partial=target.with_suffix(".part")
        if target.exists():
            from stockout.common import file_hash
            if file_hash(target)==expected:print("verified",target.name);continue
            raise RuntimeError("Existing source digest mismatch; refusing overwrite")
        url=f"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-LT/resolve/main/data/{split}.parquet"
        with requests.get(url,stream=True,timeout=(20,120)) as response:
            response.raise_for_status();h=hashlib.sha256()
            with partial.open("wb") as f:
                for chunk in response.iter_content(1024*1024):
                    if chunk:f.write(chunk);h.update(chunk)
                f.flush();os.fsync(f.fileno())
        if h.hexdigest()!=expected:raise RuntimeError("Downloaded source changed; partial retained for inspection")
        os.replace(partial,target);print("downloaded and verified",target.name)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--dest",type=Path,required=True);main(p.parse_args().dest)
