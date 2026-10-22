import hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from demand_inventory.core import metrics,pinball,targets,simulate,allocate
from train_and_freeze import load_data,ORIGINS
from prepare_data import dump
from source_integrity import research_digest, verify_revision

def verify_freeze():
    verify_revision(ROOT)
    f=json.loads((ROOT/'reports/model_freeze.json').read_text())
    for p,h in f['sha256'].items():
        if research_digest(ROOT,p)!=h:raise RuntimeError('Frozen input/model changed: '+p)
    return f

def block_bootstrap(delta,draws=2000):
    a=np.asarray(delta);rng=np.random.default_rng(20261017);n=len(a);stats=[]
    for _ in range(draws):
        starts=rng.integers(0,n,size=(n+1)//2);idx=np.column_stack([starts,(starts+1)%n]).ravel()[:n]
        stats.append(float(a[idx].mean()))
    return np.quantile(stats,[.025,.975]).tolist()

def run():
    freeze=verify_freeze();y,p,dt,meta=load_data();orig=ORIGINS['test'];n=len(meta)
    forecasts=dict(np.load(ROOT/'data/processed/test_forecasts.npz'));actual=np.stack([targets(y,int(o)) for o in orig])
    baseline=freeze['selection']['baseline'];score={k:metrics(actual.ravel(),v.reshape(-1,4)) for k,v in forecasts.items()}
    perorigin={k:pinball(actual.ravel(),v.reshape(-1,4)).reshape(len(orig),n,4).mean(axis=(1,2)) for k,v in forecasts.items()}
    delta=perorigin['global_quantiles']-perorigin[baseline];ci=block_bootstrap(delta)
    groups={}
    for column in ['store_id','dept_id']:
        groups[column]={}
        for g in sorted(meta[column].unique()):
            mask=meta[column].to_numpy()==g
            groups[column][g]={k:metrics(actual[:,mask].ravel(),v[:,mask,:].reshape(-1,4)) for k,v in forecasts.items()}
    # Every policy receives the same exogenous budget, not a budget proportional to its desired orders.
    scenarios={'budget_half':{'budget_multiplier':.5},'primary':{'budget_multiplier':1.},
               'budget_double':{'budget_multiplier':2.},'lead_two_weeks':{'lead_weeks':2},
               'shortage_low':{'shortage_fraction':.2},'shortage_high':{'shortage_fraction':.8},
               'censor_proxy':{'censor':True}}
    operating={};ids=meta.id.to_numpy()
    for s,kw in scenarios.items():
        operating[s]={k:simulate(y,p,orig,v,ids,**kw) for k,v in forecasts.items()}
        allbudgets=[np.array([r['budget'] for r in v['rows']]) for v in operating[s].values()]
        if not all(np.array_equal(b,allbudgets[0]) for b in allbudgets):raise RuntimeError('Model-dependent budget')
    first_orders={}
    o=int(orig[0]);cost=.6*p[:,o-1];pen=.4*p[:,o-1]
    for s in ['budget_half','primary','budget_double']:
        first_orders[s]={}
        for k,f in forecasts.items():
            rr=operating[s][k]['rows'][0];desire=np.ceil(f[0,:,2])
            orders=allocate(desire,cost,pen,np.zeros(n),ids,rr['budget'],rr['capacity_units'])
            first_orders[s][k]=orders.tolist()
    decision={'development_selected_forecast':freeze['selection']['forecast'],'selected_baseline':baseline,
              'paired_pinball_difference':float(delta.mean()),'bootstrap95':ci,
              'conditional_test_improvement_established':bool(ci[1]<0),
              'bootstrap':'2000 circular moving-block draws,2weekly origins per block, all stores/items resampled together',
              'forecast_ranking':sorted(score,key=lambda k:score[k]['mean_pinball']),
              'primary_operating_ranking':sorted(forecasts,key=lambda k:operating['primary'][k]['total_penalty']),
              'operating_ranking_is_descriptive_not_new_model_selection':True}
    dump(ROOT/'reports/final.json',{'metrics':score,'decision':decision,'groups':groups,'origins':orig.tolist(),
        'per_origin_pinball':{k:v.tolist() for k,v in perorigin.items()},'paired_origin_differences':delta.tolist(),
        'operating':operating,'first_order_vectors':first_orders,'series_ids':ids.tolist(),
        'limitations':['Only15weekly test origins; conditional block uncertainty','Sales proxy can be censored by stockouts',
                       'Costs/lead times/capital/capacity invented as explicit scenarios, not retailer outcomes',
                       'Prediction intervals are marginal;14day target windows overlap','Frozen model weights with updated observed lags; no rolling refits']})
    verify_freeze();print(json.dumps({'metrics':score,'decision':decision,
        'primary_operating':{k:{m:v[m] for m in ['total_penalty','unit_fill_rate','procurement_spend','ending_inventory_units','ending_pipeline_units']} for k,v in operating['primary'].items()}},indent=2))

if __name__=='__main__':run()
