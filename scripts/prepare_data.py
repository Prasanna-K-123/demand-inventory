import hashlib,json,zipfile,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')

def run():
    raw=ROOT/'data/raw';out=ROOT/'data/processed';out.mkdir(parents=True,exist_ok=True)
    zpath=raw/'m5.zip';sha=hashlib.sha256(zpath.read_bytes()).hexdigest()
    if sha!='cc704ba15d6802f8262e6ec7d4c6041e4ad6366a94365e8c84f721e450eed774':raise ValueError('Source ZIP bytes changed')
    hashes={};members={}
    with zipfile.ZipFile(zpath) as z:
        for f in z.infolist():
            h=hashlib.sha256()
            with z.open(f) as r:
                while b:=r.read(1048576):h.update(b)
            hashes[f.filename]=h.hexdigest();members[f.filename]=f.file_size
        meta=pd.read_csv(z.open('sales_train_evaluation.csv'),usecols=['item_id','dept_id','cat_id','store_id','state_id'])
        source_rows=len(meta)
        items=[]
        for dept,g in meta.groupby('dept_id',sort=True):items.extend(sorted(g.item_id.unique())[:10])
        if len(items)!=70:raise ValueError('Sample item count')
        stores=['CA_1','TX_1','WI_1'];parts=[]
        for chunk in pd.read_csv(z.open('sales_train_evaluation.csv'),chunksize=500):
            sub=chunk[chunk.item_id.isin(items)&chunk.store_id.isin(stores)]
            if len(sub):parts.append(sub)
        s=pd.concat(parts);s['id']=s.item_id+'__'+s.store_id
        s=s.sort_values('id').reset_index(drop=True)
        if len(s)!=210 or s.id.duplicated().any():raise ValueError('Sample keys')
        cols=[f'd_{j}' for j in range(1,1942)];y=s[cols].to_numpy(dtype=np.float64)
        if np.any(~np.isfinite(y)) or np.any(y<0) or np.any(y!=np.floor(y)):raise ValueError('Invalid unit sales')
        cal=pd.read_csv(z.open('calendar.csv'))
        if 'd' not in cal:cal['d']=[f'd_{j}' for j in range(1,len(cal)+1)]
        if cal.d.duplicated().any():raise ValueError('Duplicate calendar')
        cal=cal.set_index('d').loc[cols].reset_index();dates=pd.to_datetime(cal.date)
        if not np.all(np.diff(dates.values).astype('timedelta64[D]').astype(int)==1):raise ValueError('Calendar gaps')
        # Every selected weekly origin is the final observed day of a source price week.
        all_origins=np.r_[np.arange(364,1597,7),np.arange(1624,1716,7),np.arange(1743,1800,7),np.arange(1827,1926,7)]
        for origin in all_origins:
            if cal.iloc[origin-1].wm_yr_wk==cal.iloc[origin].wm_yr_wk:raise ValueError('Weekly average price not fully observed at origin')
        prices=[]
        for chunk in pd.read_csv(z.open('sell_prices.csv'),chunksize=200000):
            sub=chunk[chunk.item_id.isin(items)&chunk.store_id.isin(stores)]
            if len(sub):prices.append(sub)
        pr=pd.concat(prices)
        if pr.duplicated(['store_id','item_id','wm_yr_wk']).any() or (pr.sell_price<=0).any():raise ValueError('Price keys or domain')
        lookup={(store,item):g.set_index('wm_yr_wk').sell_price for (store,item),g in pr.groupby(['store_id','item_id'])}
        daily=[]
        for r in s.itertuples():
            v=lookup[(r.store_id,r.item_id)].reindex(cal.wm_yr_wk).to_numpy()
            daily.append(pd.Series(v).ffill().to_numpy())
        price=np.array(daily)
        meta=s[['id','item_id','dept_id','cat_id','store_id','state_id']]
        meta.to_csv(out/'series.csv',index=False);cal.to_csv(out/'calendar.csv',index=False)
        # Canonical subset lets source snapshots be recovered without redistributing the entire benchmark.
        s.to_csv(out/'sales_subset.csv',index=False);pr.sort_values(['store_id','item_id','wm_yr_wk']).to_csv(out/'prices_subset.csv',index=False)
        np.savez_compressed(out/'panel.npz',sales=y,price=price,dates=dates.to_numpy(dtype='datetime64[D]').astype('int64'))
    flags={'series':210,'items':70,'departments':7,'stores':stores,'days':1941,'source_sales_rows':source_rows,
        'date_range':[str(dates.iloc[0].date()),str(dates.iloc[-1].date())],
        'zero_fraction':float((y==0).mean()),'total_units':int(y.sum()),'duplicate_series_keys':0,
        'negative_or_noninteger_sales':0,'price_week_complete_at_all_origins':True,
        'missing_prices_first_test_origin':int(np.isnan(price[:,1826]).sum()),
        'raw_zip_sha256':sha,'raw_zip_bytes':zpath.stat().st_size,'member_sha256':hashes,'member_bytes':members,
        'raw_zip_all_members_crc_read':True,'price_rows_selected':len(pr),
        'official_purpose':'M5 organizers publish files for replication and research; Nixtla supplies ZIP version of that same linked collection',
        'source_links':['https://github.com/Mcompetitions/M5-methods','https://github.com/Nixtla/m5-forecasts','https://nixtla.github.io/datasetsforecast/m5.html'],
        'reuse_boundary':'Research/replication; no unrestricted raw-data redistribution or commercial-use license claimed',
        'latent_demand_inventory_costs_observed':False,
        'sample_selection':'First10 lexicographic itemIDs per department crossed with CA_1/TX_1/WI_1; no outcome filters',
        'mirror_schema_normalization':'Nixtla ZIP omits competition id and calendar d: stable item__store key and sequential d_1... labels are explicitly constructed; no sales values modified'}
    flags['processed_sha256']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.iterdir()) if f.is_file()}
    dump(ROOT/'reports/data_audit.json',flags);print(json.dumps({k:flags[k] for k in ['series','items','departments','days','date_range','zero_fraction','missing_prices_first_test_origin','price_rows_selected']},indent=2))

if __name__=='__main__':run()
