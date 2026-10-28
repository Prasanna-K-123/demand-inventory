import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('verify_reproduction',Path(__file__).resolve().parents[1]/'scripts/verify_reproduction.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_roundoff_is_distinct_from_model_drift():
    module.compare({'mae':0.45},{'mae':0.45+1e-14})
    with pytest.raises(ValueError,match='numeric drift'):
        module.compare({'mae':0.45},{'mae':0.4501})


def test_counts_and_types_are_exact():
    with pytest.raises(ValueError,match='identity/count/decision changed'):
        module.compare({'n':100},{'n':101})
    with pytest.raises(ValueError,match='type changed'):
        module.compare({'n':100},{'n':100.0})


@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_nonfinite_results_fail(bad):
    with pytest.raises(ValueError,match='nonfinite'):
        module.compare({'mae':0.45},{'mae':bad})


def test_scenario_constants_are_exact():
    with pytest.raises(ValueError,match='scenario assumption changed'):
        module.compare({'shortage_weight':3.0},{'shortage_weight':3.0+1e-14})


def test_interval_sign_cannot_hide_within_roundoff_budget():
    with pytest.raises(ValueError,match='crossed zero'):
        module.compare({'ci95_percentile':[-1e-14,0.2]},{'ci95_percentile':[1e-14,0.2]})


@pytest.mark.parametrize('content',[
    'mae,mae\n0.4,0.8\n',
    'mae,n\n0.4,2,extra\n',
    'mae,n\n0.4\n',
    '',
])
def test_csv_rejects_ambiguous_structure(tmp_path,content):
    path=tmp_path/'invalid.csv';path.write_text(content)
    with pytest.raises(ValueError,match='CSV'):
        module.read_result(path)
