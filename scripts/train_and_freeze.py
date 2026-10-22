import hashlib,json,sys,platform
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from demand_inventory.core import FEATURES,QUANTILES,features,targets,sba_path,coherent,metrics
from prepare_data import dump
from source_integrity import research_digest
ORIGINS={'train':np.arange(364,1597,7),'calibration':np.arange(1624,1716,7),
         'development':np.arange(1743,1800,7),'test':np.arange(1827,1926,7)}

def load_data():
    a=np.load(ROOT/'data/processed/panel.npz');meta=pd.read_csv(ROOT/'data/processed/series.csv')
    return a['sales'],a['price'],a['dates'],meta

def code_meta(meta,vocabulary=None):
    columns=['item_id','dept_id','store_id']
    voc=vocabulary or {c:sorted(meta[c].unique().tolist()) for c in columns}
    codes=[]
    for c in columns:
        d={v:i for i,v in enumerate(voc[c])};s=meta[c].map(d)
        if s.isna().any():raise ValueError('Unknown training category: '+c)
        codes.append(s.to_numpy())
    return np.column_stack(codes),voc

def x_at(y,p,dt,code,origin,price_median=None):
    x=features(y,p,dt,code,int(origin))
    if price_median is not None:x[~np.isfinite(x[:,15]),15]=price_median
    return x

def baseline_points(y,origins,sba):
    return {name:np.stack([2*y[:,o-7:o].sum(axis=1) if name=='seasonal_naive' else 14*sba[:,o-1] for o in origins])
            for name in ['seasonal_naive','croston_sba']}

def baseline_quantiles(y,origins,points,calibration,dept):
    scale=np.stack([np.maximum(y[:,o-28:o].sum(axis=1)/2,1) for o in origins])
    return {name:coherent((pt[:,:,None]+scale[:,:,None]*np.stack([np.asarray(calibration[name][str(d)]) for d in dept])[None,:,:]).reshape(-1,4)).reshape(len(origins),len(dept),4)
            for name,pt in points.items()}

def run():
    y,p,dt,meta=load_data();code,voc=code_meta(meta);n=len(meta)
    report=ROOT/'reports';(ROOT/'artifacts').mkdir(exist_ok=True)
    protocol_paths=['PROTOCOL.md','src/demand_inventory/core.py','scripts/prepare_data.py','scripts/train_and_freeze.py']
    design={f:research_digest(ROOT,f) for f in protocol_paths}
    pre=report/'protocol_freeze.json'
    if pre.exists():
        if json.loads(pre.read_text())['sha256']!=design:raise RuntimeError('Frozen modelling design changed')
    else:dump(pre,{'sha256':design,'status':'Frozen before fitting and development/test scoring','origins':{k:v.tolist() for k,v in ORIGINS.items()}})
    train=ORIGINS['train'];x=np.concatenate([x_at(y,p,dt,code,o) for o in train]);target=np.concatenate([targets(y,o) for o in train])
    med=float(np.nanmedian(x[:,15]));x[~np.isfinite(x[:,15]),15]=med
    fitted=[]
    for q in QUANTILES:
        model=HistGradientBoostingRegressor(loss='quantile',quantile=float(q),learning_rate=.08,max_iter=150,
            max_leaf_nodes=15,min_samples_leaf=50,l2_regularization=5,max_bins=128,early_stopping=False,
            categorical_features=[0,1,2],random_state=20261017)
        model.fit(x,target);fitted.append(model);print('Fitted quantile',q,'rows',len(target),flush=True)
    sba=np.stack([sba_path(row) for row in y]);dep=meta.dept_id.to_numpy();cal_orig=ORIGINS['calibration']
    cal_point=baseline_points(y,cal_orig,sba);cal_y=np.stack([targets(y,o) for o in cal_orig]);cal_scale=np.stack([np.maximum(y[:,o-28:o].sum(axis=1)/2,1) for o in cal_orig])
    residual={}
    for name,pt in cal_point.items():
        e=(cal_y-pt)/cal_scale;residual[name]={d:np.quantile(e[:,dep==d].ravel(),QUANTILES).tolist() for d in sorted(set(dep))}
    predictions={};cross={}
    for split in ['development','test']:
        origins=ORIGINS[split];b=baseline_quantiles(y,origins,baseline_points(y,origins,sba),residual,dep)
        xx=np.concatenate([x_at(y,p,dt,code,o,med) for o in origins])
        raw=np.column_stack([m.predict(xx) for m in fitted]);cross[split]=float(np.any(np.diff(raw,axis=1)<0,axis=1).mean())
        b['global_quantiles']=coherent(raw).reshape(len(origins),n,4);predictions[split]=b
    dy=np.concatenate([targets(y,o) for o in ORIGINS['development']]);dev={name:metrics(dy,v.reshape(-1,4)) for name,v in predictions['development'].items()}
    baseline=min(['seasonal_naive','croston_sba'],key=lambda k:(round(dev[k]['mean_pinball'],8),0 if k=='seasonal_naive' else 1))
    selected='global_quantiles' if dev['global_quantiles']['mean_pinball']<dev[baseline]['mean_pinball']-1e-8 else baseline
    bundle={'models':fitted,'vocabulary':voc,'price_median':med,'residual_quantiles':residual,
            'selected_baseline':baseline,'selected_forecast':selected,'features':FEATURES,'quantiles':QUANTILES.tolist()}
    joblib.dump(bundle,ROOT/'artifacts/forecast.joblib',compress=3)
    for split,b in predictions.items():np.savez_compressed(ROOT/f'data/processed/{split}_forecasts.npz',**b)
    dump(report/'development.json',{'metrics':dev,'selected_baseline':baseline,'selected_forecast':selected,
        'quantile_crossing_before_sort':cross,'training_rows':len(target),'training_price_median':med,
        'fitted_iterations':[m.n_iter_ for m in fitted],'feature_names':FEATURES,'origins':{k:v.tolist() for k,v in ORIGINS.items()},
        'test_labels_scored':False,'development_label_end':int(max(ORIGINS['development'])+14),
        'first_test_origin':int(min(ORIGINS['test']))})
    frozen=protocol_paths+['artifacts/forecast.joblib','reports/protocol_freeze.json','reports/development.json',
         'data/processed/panel.npz','data/processed/series.csv','data/processed/development_forecasts.npz','data/processed/test_forecasts.npz']
    dump(report/'model_freeze.json',{'sha256':{f:research_digest(ROOT,f) for f in frozen},
        'selection':{'baseline':baseline,'forecast':selected},'python':platform.python_version(),
        'status':'Fitted artifacts and all final forecasts frozen before final scoring; no test labels used in selection'})
    print(json.dumps({'development':dev,'baseline':baseline,'selected_forecast':selected,'crossing':cross},indent=2))

if __name__=='__main__':run()
