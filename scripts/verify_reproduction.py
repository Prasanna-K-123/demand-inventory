"""Compare an executed reference-environment study without hiding model drift."""
from pathlib import Path
import argparse,csv,hashlib,json,math,re
from stockout.model import ModelBundle

BASE=Path(__file__).resolve().parents[1]
FILES=['cohort.csv','attrition.json','forecast_metrics.csv','interval_metrics.json',
       'bootstrap.json','artificial_masking.json','decision_summary.json','weekly_summary.json','weekly_metrics.csv']

def csv_value(value):
    if re.fullmatch(r'-?\d+',value):return int(value)
    try:return float(value)
    except ValueError:return value

def read_result(path):
    if path.suffix=='.csv':
        with path.open(newline='') as handle:
            reader=csv.DictReader(handle)
            headers=reader.fieldnames
            if not headers or any(not key.strip() for key in headers) or len(set(headers))!=len(headers):
                raise ValueError(str(path)+': missing or duplicate CSV headers')
            rows=[]
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(str(path)+': malformed CSV row width')
                rows.append({key:csv_value(value) for key,value in row.items()})
            return rows
    return json.loads(path.read_text())

def compare(expected,actual,path='root'):
    """Tight roundoff budget only; historical cross-platform model drift fails."""
    if type(expected) is not type(actual):raise ValueError(path+': type changed')
    if isinstance(expected,dict):
        if expected.keys()!=actual.keys():raise ValueError(path+': keys changed')
        for key in expected:compare(expected[key],actual[key],path+'.'+key)
    elif isinstance(expected,list):
        if len(expected)!=len(actual):raise ValueError(path+': length changed')
        for i,(a,b) in enumerate(zip(expected,actual)):compare(a,b,f'{path}[{i}]')
    elif isinstance(expected,float):
        if not math.isfinite(expected) or not math.isfinite(actual):raise ValueError(path+': nonfinite value')
        if path.rsplit('.',1)[-1] in {'shortage_weight','step'} and expected!=actual:
            raise ValueError(path+': scenario assumption changed')
        if 'ci95' in path and expected!=actual and min(expected,actual)<=0<=max(expected,actual):
            raise ValueError(path+': confidence interval endpoint crossed zero')
        if not math.isclose(expected,actual,rel_tol=1e-12,abs_tol=1e-12):
            raise ValueError(f'{path}: numeric drift ({expected!r} versus {actual!r}); investigate, do not enlarge tolerance')
    elif expected!=actual:raise ValueError(path+': identity/count/decision changed')

def main(output):
    reference=json.loads((BASE/'references/linux_reference_20261028.json').read_text())
    for name,expected in reference['source_and_protocol_sha256'].items():
        actual=hashlib.sha256((BASE/name).read_bytes()).hexdigest()
        if actual!=expected:raise ValueError(name+': source/protocol identity changed')
    for name in FILES:compare(reference['results'][name],read_result(BASE/'artifacts'/name),name)
    bundle=ModelBundle(BASE/'artifacts')
    for key,value in reference['model_contract'].items():compare(value,bundle.manifest[key],'manifest.'+key)
    receipt={'status':'passed','scope':'Pinned Linux numerical reference; no universal cross-platform identity claim',
             'files':FILES,'relative_tolerance':1e-12,'absolute_tolerance':1e-12,
             'model_version':bundle.version,'artifact_sha256':bundle.manifest['artifact_sha256']}
    if output:
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    main(parser.parse_args().output)
