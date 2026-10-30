from copy import deepcopy

import pytest
from pydantic import ValidationError

from tradingagents.research.contracts import ResearchPlanInput, SnapshotManifest, StrategySpec
from tests.research.conftest import plan_payload, snapshot_payload, spec_payload


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(mode="live"),
    lambda p: p["risk"].update(max_position_fraction="50"),
    lambda p: p["risk"].update(cash_reserve_fraction="1"),
    lambda p: p["rules"].update(kind="arbitrary_python"),
    lambda p: p["rules"].update(lookbacks_sessions=[4, 2]),
    lambda p: p["universe"].append(deepcopy(p["universe"][0])),
    lambda p: p["risk"].update(max_drawdown_fraction="NaN"),
])
def test_rejects_ambiguous_or_unauthorized_strategy_inputs(mutation):
    payload = spec_payload()
    mutation(payload)
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(payload)


@pytest.mark.parametrize("mutation", [
    lambda p: p["split"].update(validation_start="2020-03-01"),
    lambda p: p["split"].update(holdout_end="2099-01-01"),
    lambda p: p["scenarios"][1].update(slippage_bps="5"),
    lambda p: p["scenarios"][2].update(execution_delay_sessions=0),
    lambda p: p.update(criteria={}),
])
def test_plan_requires_chronology_cost_stress_and_explicit_criteria(mutation):
    payload = plan_payload("s", "v")
    mutation(payload)
    with pytest.raises(ValidationError):
        ResearchPlanInput.model_validate(payload)


def test_unknown_availability_cannot_be_disguised_as_prospective():
    payload = snapshot_payload()
    payload.update(evidence_kind="prospective", availability="verified_publication")
    with pytest.raises(ValidationError):
        SnapshotManifest.model_validate(payload)


def test_proportional_commission_is_bounded_and_stressed_without_changing_old_hashes():
    from tradingagents.research.contracts import CostScenario, content_hash
    old={'name':'base','slippage_bps':'10','commission_usd':'1','execution_delay_sessions':0}
    assert content_hash(CostScenario.model_validate(old))==content_hash(old)
    payload=plan_payload('s','v')
    baseline=ResearchPlanInput.model_validate(payload).model_dump(mode='json')
    assert all('commission_bps' not in row for row in baseline['scenarios'])
    for row,bps in zip(payload['scenarios'],['1','2','1']):row['commission_bps']=bps
    approved=ResearchPlanInput.model_validate(payload)
    assert approved.scenarios[0].model_dump(mode='json')['commission_bps']=='1'
    for index,bps in [(0,'-1'),(0,'NaN'),(0,'1001'),(1,'1.9'),(2,'0.9')]:
        invalid=deepcopy(payload);invalid['scenarios'][index]['commission_bps']=bps
        with pytest.raises(ValidationError):ResearchPlanInput.model_validate(invalid)
