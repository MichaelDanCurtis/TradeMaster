"""Reference-stage regression tests: no model weights or MLX required in CI."""
import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('forecast_mlx_child',ROOT/'scripts/research/forecast_mlx_child.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
FIXTURE=json.loads((ROOT/'tests/fixtures/forecast_preprocessing_reference.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['label'])
def test_detrending_matches_captured_pytorch_cpu_stage_exactly(case):
    values=np.asarray([case['values'],*case['covariates']],dtype=np.float32)[None,:,:]
    actual=adapter.reference_detrend(values,np.zeros_like(values,dtype=bool),256)
    for output,key in zip(actual,('m_trend','c_trend','apply_detrend')):
        np.testing.assert_array_equal(output,np.asarray(case[key],dtype=output.dtype))


def test_unsupported_context_does_not_silently_change_reduction_order():
    with pytest.raises(ValueError):adapter.sum_fp32_256(np.zeros((1,32),dtype=np.float32))
    with pytest.raises(ValueError):adapter.reference_detrend(np.zeros((1,1,255)),np.zeros((1,1,255),bool),255)


def test_qualifier_requires_both_mlx_variants():
    # Check the CLI's failure decision against a passing stock summary with a
    # failing auxiliary summary, without running weights inside the unit suite.
    from scripts.research.benchmark_forecast_backends import mlx_qualified
    assert not mlx_qualified([{'device':'mlx','variant':'stock','passed':True}, {'device':'mlx','variant':'market_volume','passed':False}])
    assert not mlx_qualified([{'device':'mlx','variant':'stock','passed':True}])
    assert mlx_qualified([{'device':'mlx','variant':'stock','passed':True}, {'device':'mlx','variant':'market_volume','passed':True}, {'device':'mps','variant':'market_volume','passed':False}])
