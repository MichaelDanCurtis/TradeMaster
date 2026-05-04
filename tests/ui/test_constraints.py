from tradingagents.ui.constraints import (
    ConstraintContext,
    PortfolioConstraintPolicy,
    SymbolicConstraintEngine,
    TradeProposal,
)


def test_constraint_engine_allows_trade_inside_policy_limits():
    engine = SymbolicConstraintEngine()

    decision = engine.evaluate(
        TradeProposal(
            symbol="NVDA",
            side="buy",
            notional=5_000,
            environment="paper",
            sector="Semiconductors",
        ),
        ConstraintContext(
            account_equity=100_000,
            current_position_notional=10_000,
            sector_exposure_notional=20_000,
            daily_turnover_notional=5_000,
            current_drawdown_percent=2,
        ),
        PortfolioConstraintPolicy(
            max_position_percent=20,
            max_sector_percent=40,
            max_daily_turnover_percent=25,
            max_drawdown_percent=10,
            paper_mode_required=True,
        ),
    )

    assert decision.passed is True
    assert decision.violations == []


def test_constraint_engine_vetoes_position_sector_turnover_drawdown_and_live_trade():
    engine = SymbolicConstraintEngine()

    decision = engine.evaluate(
        TradeProposal(
            symbol="NVDA",
            side="buy",
            notional=30_000,
            environment="live",
            sector="Semiconductors",
        ),
        ConstraintContext(
            account_equity=100_000,
            current_position_notional=10_000,
            sector_exposure_notional=35_000,
            daily_turnover_notional=10_000,
            current_drawdown_percent=12,
        ),
        PortfolioConstraintPolicy(
            max_position_percent=20,
            max_sector_percent=40,
            max_daily_turnover_percent=25,
            max_drawdown_percent=10,
            paper_mode_required=True,
        ),
    )

    assert decision.passed is False
    assert [violation.rule for violation in decision.violations] == [
        "paper_mode_required",
        "max_position_percent",
        "max_sector_percent",
        "max_daily_turnover_percent",
        "max_drawdown_percent",
    ]
