from tradingagents.research.contracts import GuidanceRules, StrategySpec, content_hash


def guidance_cohorts(specs: dict[str, StrategySpec]) -> list[dict[str, str]]:
    """Freeze matched arms; a changed horizon/risk/universe is another cohort."""
    groups = {}
    for version_id, spec in specs.items():
        if not isinstance(spec.rules, GuidanceRules):
            continue
        comparable = spec.model_dump(mode="json", exclude={"model"})
        comparable["rules"].pop("arm")
        group = groups.setdefault(content_hash(comparable), {})
        if spec.rules.arm in group:
            raise ValueError("Guidance comparison has duplicate identical arms")
        group[spec.rules.arm] = version_id
    for group in groups.values():
        if set(group) != {"guidance_control", "numeric_quality", "astra_challenger"}:
            raise ValueError("Guidance plans require all three arms with identical universe, risk, timing, liquidity and holding rules")
    return list(groups.values())
