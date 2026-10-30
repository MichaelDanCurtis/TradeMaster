"""Container-only LEAN algorithm. Native order tickets and account verification."""
from AlgorithmImports import *

from datetime import datetime
from decimal import Decimal as D, localcontext
import json
import hashlib
from pathlib import Path

from tradingagents.research.contracts import canonical_json, content_hash
from tradingagents.research.engines.base import ReplayRequest, VenueEquity, VenueReceipt
from tradingagents.research.engines.simulation import ClockStep, PortfolioSimulation, VenueStep, whole


class ResearchPrice(PythonData):
    def get_source(self, config, date, is_live):
        if is_live: raise ValueError("Research data has no live provider")
        return SubscriptionDataSource(f"/Inputs/{config.symbol.value}.csv", SubscriptionTransportMedium.LOCAL_FILE)

    def reader(self, config, line, date, is_live):
        if not line.strip(): return None
        stamp, price = line.split(",")
        point = ResearchPrice()
        point.symbol = config.symbol
        point.time = datetime.fromisoformat(stamp)
        point.end_time = point.time
        point.value = float(price)
        return point


class ResearchCommission(FeeModel):
    """Native fee calculation from the venue price and signed order quantity."""
    def __init__(self, scenario):
        self.scenario = scenario

    def get_order_fee(self, parameters):
        with localcontext() as context:
            context.prec = 36
            quantity = D(str(parameters.order.quantity))
            opening = D(str(parameters.security.price))
            slippage = opening * self.scenario.slippage_bps / D(10000)
            price = opening + (slippage if quantity > 0 else -slippage)
            fee = self.scenario.commission_usd + abs(quantity) * price * self.scenario.commission_bps / D(10000)
            return OrderFee(CashAmount(float(fee), "USD"))


class TradeMasterResearch(QCAlgorithm):
    def initialize(self):
        payload = json.loads(Path("/Inputs/request.json").read_text())
        root = Path("/Code/tradingagents/research")
        actual = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.py")}
        if actual != payload["source_manifest"]: raise ValueError("Research source manifest mismatch inside LEAN")
        self.request = ReplayRequest.model_validate(payload["request"])
        if content_hash(self.request) != payload["input_hash"]: raise ValueError("Research input hash mismatch")
        self.set_time_zone(TimeZones.UTC)
        self.set_start_date(self.request.start.year, self.request.start.month, self.request.start.day)
        self.set_end_date(self.request.end.year, self.request.end.month, self.request.end.day)
        self.set_cash(float(self.request.initial_capital_usd))
        self.set_benchmark(lambda at: 1)
        self.clock = self.add_data(ResearchPrice, "CLOCK", Resolution.SECOND, TimeZones.UTC, False, 1).symbol
        self.assets, self.instrument_by_symbol = {}, {}
        self.receivables, self.order_receipts = {}, {}
        self.native_points, self.native_receipts = [], []
        self.result = None
        for instrument, ticker in payload["symbols"].items():
            asset = self.add_data(ResearchPrice, ticker, Resolution.SECOND, TimeZones.UTC, False, 1)
            asset.set_fee_model(ResearchCommission(self.request.scenario))
            asset.set_slippage_model(ConstantSlippageModel(float(self.request.scenario.slippage_bps / D(10000))))
            asset.set_data_normalization_mode(DataNormalizationMode.RAW)
            self.assets[instrument] = asset
            self.instrument_by_symbol[asset.symbol] = instrument
        self.steps = PortfolioSimulation(payload["build"], venue="Pinned LEAN native whole-order market fills on the declared session clock; no broker connection").steps(self.request)
        self.pending = next(self.steps)

    def on_data(self, data):
        if self.pending is None or not data.contains_key(self.clock): return
        with localcontext() as context:
            context.prec = 36
            while self.pending is not None:
                if isinstance(self.pending, ClockStep):
                    if self.pending.at > self.utc_time: return
                    if self.pending.at != self.utc_time: raise ValueError(f"LEAN skipped a required research timestamp: {self.pending.at} != {self.utc_time}")
                    receipt = None
                else:
                    receipt = self.venue_step(self.pending)
                try:
                    self.pending = self.steps.send(receipt)
                except StopIteration as done:
                    self.result, self.pending = done.value, None

    def on_order_event(self, event):
        if event.status != OrderStatus.FILLED: return
        self.order_receipts[event.order_id] = {"quantity": int(event.fill_quantity), "price": D(str(event.fill_price)), "fee": D(str(event.order_fee.value.amount))}

    def cash_delta(self, amount):
        self.portfolio.cash_book["USD"].add_amount(float(amount))

    def update_receivables(self):
        self.portfolio.unsettled_cash_book["USD"].set_amount(float(sum(self.receivables.values(), D(0))))

    def venue_step(self, step: VenueStep):
        data = step.payload
        if step.kind == "order":
            asset = self.assets[data["instrument"]]
            ticket = self.market_order(asset.symbol, data["quantity"], False, data["decision_id"])
            if ticket.status != OrderStatus.FILLED or ticket.order_id not in self.order_receipts:
                raise ValueError(f"LEAN did not fill a permitted whole order: {ticket.status}; {ticket.get_most_recent_order_response()}")
            receipt = self.order_receipts[ticket.order_id]
            self.native_receipts.append({"order_id": ticket.order_id, "decision_id": data["decision_id"], "instrument_id": data["instrument"],
                "at": self.utc_time.isoformat(), "quantity": receipt["quantity"], "price_usd": str(receipt["price"]), "fee_usd": str(receipt["fee"]),
                "cash_usd": str(self.portfolio.cash), "status": "filled"})
            return receipt
        if step.kind == "cash_yield":
            amount = D(str(self.portfolio.cash)) * data["rate"] * D(data["days"]) / D(365)
            self.assert_close(amount, data["amount"], "Cash-yield base")
            self.cash_delta(amount)
        elif step.kind == "action":
            action = data["action"]
            asset = self.assets[action.instrument_id]
            holding = self.portfolio[asset.symbol]
            quantity = int(holding.quantity)
            if action.kind == "split" and quantity:
                exact = D(quantity) * action.split_ratio
                remaining, average = whole(exact), D(str(holding.average_price)) / action.split_ratio
                if exact != remaining:
                    if data["bar"] is None: raise ValueError("Missing opening price for fractional split compensation")
                    self.cash_delta((exact - remaining) * data["bar"].open)
                holding.set_holdings(float(average), remaining)
            elif action.kind in {"dividend", "delisting"}:
                if quantity:
                    self.receivables[action.action_id] = D(quantity) * action.cash_per_share_usd
                    self.update_receivables()
                if action.kind == "delisting": holding.set_holdings(0, 0)
        elif step.kind == "payment":
            amount = self.receivables.pop(data["action_id"])
            self.assert_close(amount, data["amount"], "Receivable settlement")
            self.cash_delta(amount)
            self.update_receivables()
        elif step.kind == "checkpoint":
            point = data["point"]
            quantities = {i: int(self.portfolio[a.symbol].quantity) for i, a in self.assets.items()}
            cash, equity = D(str(self.portfolio.cash)), D(str(self.portfolio.total_portfolio_value))
            receivables = D(str(self.portfolio.unsettled_cash_book.total_value_in_account_currency))
            if quantities != point.quantities: raise ValueError("LEAN quantities differ from the independent ledger")
            self.assert_close(cash, point.cash_usd, "LEAN cash")
            self.assert_close(equity, point.equity_usd, "LEAN equity")
            self.assert_close(receivables, point.receivables_usd, "LEAN receivables")
            self.assert_close(D(str(self.portfolio.total_fees)), point.fees_usd, "LEAN fees")
            basis = sum((D(str(self.portfolio[a.symbol].average_price)) * quantities[i] for i, a in self.assets.items()), D(0))
            self.assert_close(basis, point.cost_basis_usd, "LEAN cost basis")
            self.native_points.append({"at": self.utc_time.isoformat(), "cash_usd": str(cash), "equity_usd": str(equity),
                "receivables_usd": str(receivables), "quantities": quantities, "cost_basis_usd": str(basis)})
        else:
            raise ValueError(f"Unknown venue operation {step.kind}")
        return None

    @staticmethod
    def assert_close(actual, expected, label):
        if abs(actual - expected) > D("0.000001"):
            raise ArithmeticError(f"{label} does not reconcile: {actual} != {expected}")

    def on_end_of_algorithm(self):
        if self.result is None: raise ValueError("LEAN ended before the declared research clock completed")
        self.result.venue_receipts = [VenueReceipt.model_validate(row) for row in self.native_receipts]
        self.result.venue_equity = [VenueEquity.model_validate(row) for row in self.native_points]
        self.result.limitations.append("Custom stable-ID price feeds use the frozen calendar and raw prices. Explicit action/receivable handling bridges native holdings and cash books; no inferred exchange calendar or action factor file is substituted.")
        self.result.limitations.append("Native account checks use a USD 0.000001 absolute tolerance for Python/.NET decimal conversion. These are simulated fills, not broker-paper evidence.")
        Path("/Results/result.json").write_text(canonical_json(self.result))
