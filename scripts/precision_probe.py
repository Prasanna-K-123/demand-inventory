"""Controlled refit sensitivity; does not change the frozen study or its outputs."""
from pathlib import Path
import argparse,hashlib,json,math,sys,time
import duckdb,numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits,threadpool_info

BASE=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--features',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
sys.path.insert(0,str(BASE/'src'))
from stockout.features import FEATURE_NAMES
from stockout.model import ModelBundle

def hash_array(x):return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()

frame=duckdb.sql("select * from read_parquet('"+str(args.features.resolve())+"')").fetchdf()
train=frame[(frame.split=='fit')&(frame.identity_split=='fitting_identities')]
test=frame[(frame.split=='final')&(frame.identity_split=='fitting_identities')]
X=train[FEATURE_NAMES].to_numpy();y=train.sale_amount.to_numpy()/train.scale.to_numpy()
E=test[FEATURE_NAMES].to_numpy();scale=test.scale.to_numpy();truth=test.sale_amount.to_numpy()
baseline=ModelBundle(BASE/'artifacts').models
kwargs=dict(max_iter=160,max_leaf_nodes=15,min_samples_leaf=40,learning_rate=.05,l2_regularization=3.,early_stopping=False,random_state=42)
report={'scope':'Controlled precision and thread sensitivity, not identification of historical Windows root cause',
        'training_x_sha256':hash_array(X),'training_y_sha256':hash_array(y),'final_x_sha256':hash_array(E),
        'threadpools':[{k:v for k,v in item.items() if k!='filepath'} for item in threadpool_info()],'experiments':[]}

def scalar_transforms(x,rows):
    z=x.copy()
    z[:,0]=[math.log1p(s) for s in rows.scale]
    dow=np.asarray(rows.dt.dt.dayofweek);doy=np.asarray(rows.dt.dt.dayofyear)
    for col,fun,vals,period in [(17,math.sin,dow,7),(18,math.cos,dow,7),(19,math.sin,doy,365.25),(20,math.cos,doy,365.25)]:
        z[:,col]=[fun(2*np.pi*d/period) for d in vals]
    return z

for experiment,threads in [('same_input_one_thread',1),('scalar_libm_two_threads',2)]:
    tx,ex=(X,E) if experiment.startswith('same') else (scalar_transforms(X,train),scalar_transforms(E,test))
    changes=np.abs(tx-X)
    record={'experiment':experiment,'threads':threads,'input_max_abs_change':float(changes.max()),'input_cells_changed':int((changes!=0).sum()),'models':{}}
    with threadpool_limits(limits=threads):
        for name,loss,q in [('poisson','poisson',None),('q10','quantile',.1),('q90','quantile',.9)]:
            t=time.monotonic();m=HistGradientBoostingRegressor(loss=loss,quantile=q,**kwargs).fit(tx,y)
            p=m.predict(ex)*scale;b=baseline[name].predict(E)*scale
            original_bins=baseline[name]._bin_mapper.transform(X)
            new_bins=m._bin_mapper.transform(tx)
            record['models'][name]={'fit_seconds':time.monotonic()-t,'prediction_max_abs_change':float(np.abs(p-b).max()),
                'prediction_changed_rows':int((p!=b).sum()),'mean_abs_prediction_change':float(np.abs(p-b).mean()),
                'final_mae':float(np.abs(truth-p).mean()),'baseline_final_mae':float(np.abs(truth-b).mean()),
                'training_bin_changes':int((original_bins!=new_bins).sum()),
                'baseline_nodes_sha256':hash_array(np.concatenate([t[0].nodes for t in baseline[name]._predictors])),
                'new_nodes_sha256':hash_array(np.concatenate([t[0].nodes for t in m._predictors]))}
            print(experiment,name,json.dumps(record['models'][name]),flush=True)
    report['experiments'].append(record)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
