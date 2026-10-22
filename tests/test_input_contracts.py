"""Boundary regressions and valid-input equivalence to the frozen study."""
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from demand_inventory.core import sba_path, targets, allocate, simulate
from source_integrity import REVISIONS, research_digest, verify_revision


class InputContracts(unittest.TestCase):
    def setUp(self):
        self.sales = np.ones((2, 100))
        self.price = np.ones_like(self.sales)
        self.origins = np.array([56, 63, 70])
        self.quantiles = np.full((3, 2, 4), 14.)
        self.ids = ['a', 'b']

    def run_case(self, **changes):
        args = dict(sales=self.sales, price=self.price, origins=self.origins,
                    quantiles=self.quantiles, ids=self.ids)
        args.update(changes)
        return simulate(**args)

    def test_sba_missing_sales_are_errors(self):
        for values in [[1, np.nan, 1], [1, np.inf], [1, -1], [1 + 2j]]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                sba_path(values)

    def test_sba_alpha_is_finite_real_scalar(self):
        for alpha in [np.nan, np.inf, 0, 1, -.1, [0.1], True, .1 + .1j]:
            with self.subTest(alpha=alpha), self.assertRaises(ValueError):
                sba_path([0, 1, 2], alpha)

    def test_target_windows_cannot_wrap_or_truncate(self):
        for origin, horizon in [(-1, 7), (0, 0), (0, -1), (0, 1.5),
                                (90, 14), (True, 7), (0, True)]:
            with self.subTest(origin=origin, horizon=horizon), self.assertRaises(ValueError):
                targets(self.sales, origin, horizon)
        np.testing.assert_array_equal(targets(self.sales, np.int64(93), 7), [7, 7])

    def test_orders_require_positive_integer_lead_times(self):
        for lead in [0, -1, .5, 1.5, np.nan, np.inf, True, [1]]:
            with self.subTest(lead=lead), self.assertRaises(ValueError):
                self.run_case(lead_weeks=lead)
        result = self.run_case(lead_weeks=np.int64(1), budget_multiplier=100)
        self.assertEqual(result['rows'][1]['filled_units'], 14)

    def test_simulation_requires_contiguous_weekly_origins(self):
        for origins in [[], [56., 63., 70.], [56, 70], [63, 56], [56, 56],
                        [27, 34], [91, 98]]:
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                self.run_case(origins=origins)

    def test_simulation_rejects_misaligned_nonfinite_data(self):
        bad_sales = self.sales.copy(); bad_sales[0, 60] = np.nan
        bad_price = self.price.copy(); bad_price[0, 55] = np.inf
        zero_price = self.price.copy(); zero_price[0, 55] = 0
        for changes in [dict(sales=bad_sales), dict(price=bad_price), dict(price=zero_price),
                        dict(price=self.price[:1]), dict(sales=self.sales.ravel()),
                        dict(ids=['a']), dict(ids=['a', 'a'])]:
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                self.run_case(**changes)

    def test_simulation_requires_valid_quantiles_and_scenarios(self):
        for value in [np.nan, np.inf, -1.0]:
            quantiles = self.quantiles.copy(); quantiles[0, 0, 2] = value
            with self.subTest(quantile=value), self.assertRaises(ValueError):
                self.run_case(quantiles=quantiles)
        crossed = self.quantiles.copy(); crossed[0, 0] = [0, 2, 1, 3]
        for changes in [dict(quantiles=crossed), dict(quantiles=self.quantiles[:, :1]),
                        dict(budget_multiplier=np.nan), dict(budget_multiplier=-1),
                        dict(shortage_fraction=np.inf), dict(shortage_fraction=-.1),
                        dict(censor='false')]:
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                self.run_case(**changes)

    def test_allocation_checks_aligned_inputs_and_unique_ids(self):
        base = dict(desired=[10, 10], cost=[2, 3], penalty=[1, 1],
                    coverage=[0, 0], ids=['a', 'b'], budget=7, capacity=10)
        for change in [dict(desired=[np.nan, 10]), dict(penalty=[np.nan, 1]),
                       dict(coverage=[np.inf, 0]), dict(cost=[2]), dict(ids=['a', 'a']),
                       dict(budget=np.nan), dict(capacity=np.inf)]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                allocate(**(base | change))
        np.testing.assert_array_equal(allocate(**(base | dict(cost=[np.nan, 3], penalty=[np.nan, 1]))), [0, 2])

    def test_valid_cases_match_preserved_original_and_conserve_stock(self):
        spec = importlib.util.spec_from_file_location('frozen_inventory_core', ROOT / 'reproducibility/original_core.py')
        original = importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
        rng = np.random.default_rng(20261022)
        for case in range(80):
            n = 1 + case % 5
            sales = rng.poisson(2, (n, 100)).astype(float)
            prices = rng.uniform(.5, 8, sales.shape)
            if case % 4 == 0:
                prices[0] = np.nan
            quantiles = np.sort(rng.uniform(0, 50, (3, n, 4)), axis=2)
            keys = [f'series-{j}' for j in range(n)]
            kwargs = dict(budget_multiplier=[0, .5, 1, 2][case % 4],
                          lead_weeks=1 + case % 3, shortage_fraction=[0, .2, .4, .8][case % 4],
                          censor=bool(case % 2))
            args = (sales, prices, [56, 63, 70], quantiles, keys)
            actual = simulate(*args, **kwargs)
            self.assertEqual(actual, original.simulate(*args, **kwargs))
            ordered = sum(row['ordered_units'] for row in actual['rows'])
            self.assertAlmostEqual(ordered, actual['filled_units'] + actual['ending_inventory_units'] + actual['ending_pipeline_units'])
            np.testing.assert_array_equal(sba_path(sales[0]), original.sba_path(sales[0]))
            np.testing.assert_array_equal(targets(sales, 56), original.targets(sales, 56))

    def test_original_freeze_and_exact_revision_are_both_enforced(self):
        self.assertEqual(research_digest(ROOT, 'src/demand_inventory/core.py'),
                         REVISIONS['src/demand_inventory/core.py']['original_sha256'])
        self.assertEqual(len(verify_revision(ROOT)['checked_revisions']), 3)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            paths = ['reproducibility/input_contract_revision_20261022.patch',
                     'src/demand_inventory/_contracts.py']
            for path, revision in REVISIONS.items():
                paths.extend([path, revision['preserved_path']])
            for path in paths:
                output = target / path; output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, output)
            verify_revision(target)
            with (target / 'src/demand_inventory/core.py').open('a') as stream:
                stream.write('\n# unrecorded change\n')
            with self.assertRaises(RuntimeError):
                verify_revision(target)


if __name__ == '__main__':
    unittest.main()
