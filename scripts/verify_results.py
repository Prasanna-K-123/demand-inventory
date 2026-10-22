import json,sys
from pathlib import Path
import joblib,numpy as np
from sklearn.metrics import mean_pinball_loss
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from demand_inventory.core import features,coherent,QUANTILES,targets,pinball,allocate
from train_and_freeze import load_data,code_meta,x_at,ORIGINS,baseline_points,baseline_quantiles
from evaluate_final import verify_freeze
from prepare_data import dump

def run():
    freeze=verify_freeze();y,p,dt,meta=load_data();b=joblib.load(ROOT/'artifacts/forecast.joblib');code,_=code_meta(meta,b['vocabulary'])
    orig=ORIGINS['test'];xx=np.concatenate([x_at(y,p,dt,code,o,b['price_median']) for o in orig])
    fresh=coherent(np.column_stack([m.predict(xx) for m in b['models']])).reshape(len(orig),len(meta),4)
    saved=np.load(ROOT/'data/processed/test_forecasts.npz')['global_quantiles'];np.testing.assert_array_equal(fresh,saved)
    actual=np.concatenate([targets(y,o) for o in orig]);own=pinball(actual,saved.reshape(-1,4))
    for j,q in enumerate(QUANTILES):
        expected=mean_pinball_loss(actual,saved.reshape(-1,4)[:,j],alpha=q)
        assert abs(expected-own[:,j].mean())<1e-12
    for o in [int(orig[0]),int(orig[7]),int(orig[-1])]:
        base=features(y,p,dt,code,o);yy=y.copy();pp=p.copy();yy[:,o:]=9999;pp[:,o:]=9999
        np.testing.assert_equal(base,features(yy,pp,dt,code,o))
    data=json.loads((ROOT/'reports/final.json').read_text());violations=0
    for case,models in data['operating'].items():
        for name,r in models.items():
            for row in r['rows']:
                assert row['procurement_spend']<=row['budget']+1e-6
                assert row['ordered_units']<=row['capacity_units']
                assert row['ending_inventory_units']>=0
            # No initial stock or write-offs: purchases = filled + ending stock + outstanding.
            ordered=sum(x['ordered_units'] for x in r['rows'])
            assert abs(ordered-r['filled_units']-r['ending_inventory_units']-r['ending_pipeline_units'])<1e-6
            assert r['unknown_price_demand_units']==0
    # Force no order when the price is missing and verify exact integer budget edge.
    np.testing.assert_array_equal(allocate([5,5],[np.nan,2],[np.nan,1],[0,0],['x','y'],3.99,100),[0,1])
    summary={'checks_passed':True,'original_scientific_unit_tests':9,'unit_tests_run_by_this_script':False,'saved_model_prediction_equality':'all final quantiles bitwise equal',
        'pinball_reconciled_to_sklearn':True,'future_sales_price_feature_invariance_origins':[int(orig[0]),int(orig[7]),int(orig[-1])],
        'inventory_budget_capacity_conservation_all_scenarios':True,'unknown_final_price_costs':0,
        'frozen_input_model_hashes':len(freeze['sha256']),'bootstrap_independent_units':'Origin blocks, not series rows',
        'independent_external_review':False}
    dump(ROOT/'reports/verification.json',summary);print(json.dumps(summary,indent=2))

if __name__=='__main__':run()
