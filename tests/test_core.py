import unittest
import numpy as np
from demand_inventory.core import sba_path,features,targets,pinball,coherent,allocate,simulate

class CoreTests(unittest.TestCase):
    def test_sba_zero_constant_and_intervals(self):
        np.testing.assert_array_equal(sba_path(np.zeros(20)),0.)
        np.testing.assert_allclose(sba_path(np.full(20,2.)),1.9)
        self.assertAlmostEqual(sba_path([0,2,0,2])[-1],.95)

    def test_feature_sales_and_price_future_invariance(self):
        y=np.arange(300,dtype=float).reshape(3,100)%5;p=np.full((3,100),2.);dt=np.arange(18000,18100);ids=np.array([[0,0,0],[1,0,1],[2,1,2]])
        first=features(y,p,dt,ids,70)
        y[:,70:]=9999;p[:,70:]=9999
        np.testing.assert_array_equal(features(y,p,dt,ids,70),first)
        self.assertEqual(first[0,6],np.sum((np.arange(100)%5)[63:70]))

    def test_exact_target_cutoff(self):
        y=np.arange(100).reshape(1,-1)
        self.assertEqual(targets(y,70)[0],sum(range(70,84)))
        with self.assertRaises(ValueError):targets(y,90)

    def test_quantile_score_and_coherence(self):
        self.assertAlmostEqual(pinball(np.array([10]),np.array([[8,10,12,15]])).mean(),(.2+0+.4+.5)/4)
        np.testing.assert_array_equal(coherent([[4,-2,3,1]]),[[0,1,3,4]])

    def test_common_budget_capacity_integer_orders(self):
        o=allocate([10,10],[2,3],[1,1],[0,0],['a','b'],7,10)
        np.testing.assert_array_equal(o,[3,0]);self.assertLessEqual(float(o@np.array([2,3])),7)
        o=allocate([10,10],[2,3],[1,1],[0,0],['a','b'],100,3)
        self.assertEqual(o.sum(),3)

    def test_unknown_cost_never_orders(self):
        o=allocate([10,10],[np.nan,2],[np.nan,1],[0,0],['a','b'],10,100)
        np.testing.assert_array_equal(o,[0,5])

    def test_arrival_delay_and_stock_conservation(self):
        y=np.ones((1,100));p=np.ones_like(y);orig=[56,63,70];q=np.full((3,1,4),14.)
        r=simulate(y,p,orig,q,['a'],budget_multiplier=100)
        self.assertEqual(r['rows'][0]['filled_units'],0)
        self.assertEqual(r['rows'][1]['filled_units'],7)
        self.assertEqual(r['rows'][2]['filled_units'],7)
        self.assertEqual(sum(x['ordered_units'] for x in r['rows']),r['filled_units']+r['ending_inventory_units']+r['ending_pipeline_units'])

    def test_tighter_budget_changes_actual_orders(self):
        y=np.ones((2,100));p=np.ones_like(y);q=np.full((3,2,4),14.);orig=[56,63,70]
        a=simulate(y,p,orig,q,['a','b'],budget_multiplier=.5)
        b=simulate(y,p,orig,q,['a','b'],budget_multiplier=2)
        self.assertLess(a['rows'][0]['ordered_units'],b['rows'][0]['ordered_units'])
        self.assertLessEqual(a['unit_fill_rate'],b['unit_fill_rate'])

    def test_censor_and_longer_lead_diagnostics(self):
        y=np.ones((1,100));y[:,56:63]=0;p=np.ones_like(y);orig=[56,63,70];q=np.full((3,1,4),14.)
        a=simulate(y,p,orig,q,['a'],censor=True,budget_multiplier=100)
        b=simulate(y,p,orig,q,['a'],lead_weeks=2,budget_multiplier=100)
        self.assertGreater(a['rows'][0]['demand_proxy_units'],0)
        self.assertEqual(b['rows'][1]['filled_units'],0)

if __name__=='__main__':unittest.main()
