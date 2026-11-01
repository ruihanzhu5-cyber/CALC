import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('gaia2_batch', Path(__file__).parents[1] / 'scripts/run_gaia2_batch.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_recovery_selects_only_explicit_unfinished_cases():
    plan = {'calc': ['b', 'c'], 'manta': ['a', 'b', 'c']}
    assert batch.select_tasks(['a', 'b', 'c'], plan=plan) == plan
    assert sum(map(len, plan.values())) == 5


@pytest.mark.parametrize('plan', [{}, {'calc': ['a', 'a']}, {'other': ['a']}, {'calc': []}, {'manta': ['unknown']}])
def test_invalid_recovery_plan_rejected(plan):
    with pytest.raises(ValueError):
        batch.select_tasks(['a', 'b', 'c'], plan=plan)


def test_plan_cannot_mix_with_cli_scope_overrides():
    with pytest.raises(ValueError):
        batch.select_tasks(['a'], methods=['calc'], plan={'manta': ['a']})


def test_default_batch_scope_is_preserved():
    assert batch.select_tasks(['a', 'b']) == {'calc': ['a', 'b'], 'manta': ['a', 'b']}
