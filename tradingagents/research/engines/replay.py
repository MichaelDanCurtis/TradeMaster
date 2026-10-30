"""Local deterministic driver for the shared portfolio simulation."""
from decimal import localcontext

from tradingagents.research.engines.base import ReplayRequest, ReplayResult, source_build
from tradingagents.research.engines.simulation import PortfolioSimulation


class LocalReplayEngine:
    @property
    def build(self) -> str:
        return source_build("local-replay-v1")

    def run(self, request: ReplayRequest) -> ReplayResult:
        with localcontext() as context:
            context.prec = 36
            steps = PortfolioSimulation(self.build, venue="Deterministic daily local replay, not a LEAN or broker fill").steps(request)
            try:
                while True:
                    next(steps)
            except StopIteration as done:
                return done.value
