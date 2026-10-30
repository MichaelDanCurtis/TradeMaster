from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from math import isfinite
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from tradingagents.ui.brokers.base import BrokerOrder, OrderSide
from tradingagents.ui.secrets import SecretStore
from tradingagents.ui.models import now_utc
from tradingagents.research.accounting_contracts import AccountActivity, AccountActivityBatch, AccountOrderFamily, ProtectiveChild
from tradingagents.research.contracts import content_hash
from tradingagents.research.execution_contracts import (
    AccountPosition, ExactPaperOrder, OpenPaperOrder, PaperAccountIdentity, PaperAccountSnapshot,
    PaperOrderObservation, TERMINAL,
)


class HttpResponse(Protocol):
    def json(self) -> dict[str, Any]: ...

    def raise_for_status(self) -> None: ...


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> HttpResponse:
        ...


class SnapshotConsistencyError(ValueError):
    """Bounded read-only snapshot collection could not obtain consistent marks."""
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(f"Broker marks did not reconcile after {len(diagnostics)} read-only observations; "
                         f"last equity residual {diagnostics[-1]['residual_usd']} USD. No tolerance was widened")


class AlpacaPaperBroker:
    broker_name = "alpaca"
    environment = "paper"

    def __init__(
        self,
        *,
        secret_store: SecretStore,
        secret_ref: str,
        price_estimator: Callable[[str], float],
        http_client: HttpClient | None = None,
        base_url: str = "https://paper-api.alpaca.markets",
        timeout: float = 15.0,
        drawdown_observer: Callable[[str, Decimal], Decimal | None] | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._secret_ref = secret_ref
        self._price_estimator = price_estimator
        self._http_client = http_client or requests
        self._base_url = base_url.rstrip("/").removesuffix("/v2")
        endpoint = urlsplit(self._base_url)
        official_paper = self._base_url == "https://paper-api.alpaca.markets"
        # Non-routable test endpoints require an explicitly injected client.
        test_endpoint = http_client is not None and endpoint.hostname is not None and (endpoint.hostname.endswith(".test") or endpoint.hostname in {"localhost", "127.0.0.1", "::1"})
        if not (official_paper or test_endpoint) or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("Paper execution requires the official Alpaca paper endpoint")
        self._evidence_kind = "broker_paper" if official_paper else "fixture"
        self._timeout = timeout
        self._drawdown_observer = drawdown_observer
        self._credential_headers: dict[str, str] | None = None

    def paper_identity(self) -> PaperAccountIdentity:
        account = self._read("account")
        return PaperAccountIdentity(provider_id="alpaca-paper-broker", account_id=account["id"])

    def _read(self, path: str, params: dict | None = None):
        response = self._http_client.get(f"{self._base_url}/v2/{path}", headers=self._headers(), params=params or {}, timeout=self._timeout, allow_redirects=False)
        response.raise_for_status()
        if getattr(response, "status_code", 200) != 200:
            raise ValueError("Unexpected broker read status")
        return response.json()

    def execution_calendar(self, start, end):
        from tradingagents.scheduling.calendar import alpaca_calendar
        return alpaca_calendar(self, start, end)

    def submit_exact_order(self, client_order_id: str, order: ExactPaperOrder) -> PaperOrderObservation:
        """One POST with the approved terms. No resizing, quote lookup or retry."""
        body = {"client_order_id": client_order_id, "symbol": order.symbol, "side": order.side,
            "qty": str(order.quantity), "type": "limit", "limit_price": str(order.limit_price_usd), "time_in_force": order.time_in_force}
        if order.stop_loss_usd is not None or order.take_profit_usd is not None:
            body["order_class"] = "bracket" if order.stop_loss_usd is not None and order.take_profit_usd is not None else "oto"
            if order.stop_loss_usd is not None: body["stop_loss"] = {"stop_price": str(order.stop_loss_usd)}
            if order.take_profit_usd is not None: body["take_profit"] = {"limit_price": str(order.take_profit_usd)}
        response = self._http_client.post(f"{self._base_url}/v2/orders", headers=self._headers(), json=body, timeout=self._timeout, allow_redirects=False)
        response.raise_for_status()
        if getattr(response, "status_code", 200) not in {200, 201}:
            raise ValueError("Unexpected broker submission status; reconcile the client order ID")
        payload = response.json()
        observation = _order_observation(payload)
        if (observation.client_order_id, observation.symbol, observation.side, observation.quantity) != (client_order_id, order.symbol, order.side, order.quantity):
            raise ValueError("Broker acknowledged different order terms")
        if payload.get("type") != "limit" or Decimal(str(payload["limit_price"])) != order.limit_price_usd or payload.get("time_in_force") != order.time_in_force:
            raise ValueError("Broker acknowledged a different price or duration")
        return observation

    def find_order(self, client_order_id: str) -> PaperOrderObservation | None:
        response = self._http_client.get(f"{self._base_url}/v2/orders:by_client_order_id", headers=self._headers(), params={"client_order_id": client_order_id}, timeout=self._timeout, allow_redirects=False)
        if getattr(response, "status_code", None) == 404:
            return None
        response.raise_for_status()
        if getattr(response, "status_code", 200) != 200:
            raise ValueError("Unexpected broker lookup status")
        observation = _order_observation(response.json())
        if observation.client_order_id != client_order_id:
            raise ValueError("Broker lookup returned another client order ID")
        return observation

    def cancel_exact_order(self, client_order_id: str) -> PaperOrderObservation | None:
        current = self.find_order(client_order_id)
        if current is None or current.status in TERMINAL:
            return current
        response = self._http_client.delete(f"{self._base_url}/v2/orders/{current.broker_order_id}", headers=self._headers(), timeout=self._timeout, allow_redirects=False)
        response.raise_for_status()
        # HTTP acknowledgement alone never releases a reservation.
        return self.find_order(client_order_id)

    def order_family(self, broker_order_id: str) -> AccountOrderFamily:
        """Read native child identities, including legs of a completed parent."""
        payload = self._read(f"orders/{quote(broker_order_id, safe='')}", {"nested": "true"})
        parent = _order_observation(payload)
        if parent.broker_order_id != broker_order_id:
            raise ValueError("Broker returned another parent order")
        legs = payload.get("legs")
        if not isinstance(legs, list) or len(legs) > 2 or payload.get("order_class") not in {"bracket", "oto"}:
            raise ValueError("Broker protective-order coverage is unavailable")
        children = []
        for leg in legs:
            kind = leg.get("type")
            if kind not in {"limit", "stop", "stop_limit"} or leg.get("legs"):
                raise ValueError("Unsupported nested protective order")
            children.append(ProtectiveChild(role="take_profit" if kind == "limit" else "stop_loss",
                observation=_order_observation(leg), limit_price_usd=leg.get("limit_price"), stop_price_usd=leg.get("stop_price")))
        return AccountOrderFamily(parent=parent, children=children)

    def paper_snapshot(self) -> PaperAccountSnapshot:
        # Account and position marks arrive on separate live endpoints. A skewed
        # read is not a ledger discrepancy until fresh reads also fail. Retry only
        # that condition, never a POST, economic-state change, or malformed data.
        import time
        from tradingagents.research.account_rounding import equity_residual
        deadline = time.monotonic() + 10
        diagnostics = []
        baseline = None
        for _ in range(5):
            snapshot, economic = self._paper_snapshot_once(baseline)
            baseline = economic
            from tradingagents.research.account_rounding import equity_reconciles
            if equity_reconciles(snapshot):
                if diagnostics:
                    snapshot.limitations.append("Recovered transient broker mark skew using fresh read-only observations: " + json.dumps(diagnostics, sort_keys=True))
                return snapshot
            diagnostics.append({"observed_at": snapshot.observed_at.isoformat(),
                "reported_equity_usd": str(snapshot.equity_usd),
                "detailed_equity_usd": str(snapshot.equity_usd-equity_residual(snapshot)),
                "residual_usd": str(equity_residual(snapshot))})
            if time.monotonic() >= deadline:
                break
            time.sleep(.15)
        raise SnapshotConsistencyError(diagnostics)

    def _paper_snapshot_once(self, baseline=None):
        started = now_utc()
        before = self._account_state()
        if baseline is not None and _economic_state(before) != baseline:
            raise ValueError("Paper account changed during observation; refresh before execution")
        turnover = self._daily_turnover(now_utc())
        account, positions, orders = self._account_state()
        if _economic_state(before) != _economic_state((account, positions, orders)):
            raise ValueError("Paper account changed during observation; refresh before execution")
        if account["currency"] != "USD" or any(p.get("asset_class") != "us_equity" or p.get("side") != "long" for p in positions):
            raise ValueError("Exact paper execution supports long USD equities only")
        equity = Decimal(account["equity"])
        parsed_positions = [AccountPosition(symbol=p["symbol"], quantity=p["qty"], market_value_usd=p["market_value"], cost_basis_usd=p["cost_basis"]) for p in positions]
        open_orders = []
        for item in orders:
            remaining = Decimal(item["qty"]) - Decimal(item["filled_qty"])
            if remaining < 0: raise ValueError("Broker open-order quantity is inconsistent")
            open_orders.append(OpenPaperOrder(client_order_id=item["client_order_id"], broker_order_id=item["id"], symbol=item["symbol"], side=item["side"], remaining_quantity=remaining,
                maximum_price_usd=item.get("limit_price") if item.get("type") in {"limit", "stop_limit"} else None))
        drawdown = self._drawdown_observer(account["id"], equity) if self._drawdown_observer else None
        snapshot = PaperAccountSnapshot(provider_id="alpaca-paper-broker", account_id=account["id"], evidence_kind=self._evidence_kind,
            started_at=started, observed_at=now_utc(), equity_usd=equity, cash_usd=account["cash"], buying_power_usd=account["buying_power"], daily_turnover_usd=turnover,
            drawdown_fraction=drawdown, trading_blocked=bool(account["trading_blocked"] or account["account_blocked"] or account["status"] != "ACTIVE"),
            positions=parsed_positions, open_orders=open_orders, complete=True,
            limitations=["Independent broker reads are checked for economic changes and consistent marks; they are not an atomic exchange snapshot"] + (["Reconciled drawdown history unavailable; new entries are blocked"] if drawdown is None else []))

        from tradingagents.research.account_rounding import equity_reconciles, equity_residual
        if equity_reconciles(snapshot) and equity_residual(snapshot):
            snapshot.limitations.append(f"Broker equity reporting residual: {equity_residual(snapshot)} USD; detailed marks retained")
        return snapshot, _economic_state(before)

    def _account_state(self):
        # Fetch the two independently marked views together to reduce skew.
        # This remains non-atomic: economic-state and exact equity checks below
        # are still required. Resolve credentials before entering the threads.
        from concurrent.futures import ThreadPoolExecutor
        self._headers()
        with ThreadPoolExecutor(max_workers=2) as reads:
            account_read = reads.submit(self._read, "account")
            positions_read = reads.submit(self._read, "positions")
            account, positions = account_read.result(), positions_read.result()
        if any(not isinstance(account.get(key), bool) for key in ("trading_blocked", "account_blocked")):
            raise ValueError("Broker account trading flags are missing or unverified")
        orders = self._read("orders", {"status": "open", "limit": 500, "nested": "false"})
        if not isinstance(positions, list) or not isinstance(orders, list) or len(orders) >= 500:
            raise ValueError("Broker position/order coverage is incomplete")
        return account, positions, orders

    def _daily_turnover(self, observed_at: datetime) -> Decimal:
        # Trading-day turnover uses execution timestamps, never order creation.
        midnight = observed_at.astimezone(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        params = {"after": midnight.isoformat(), "until": observed_at.isoformat(), "direction": "asc", "page_size": 100}
        total, seen = Decimal(0), set()
        for _ in range(20):
            page = self._read("account/activities/FILL", params)
            if not isinstance(page, list) or len(page) > 100:
                raise ValueError("Invalid broker activity page")
            for item in page:
                if item["id"] in seen: raise ValueError("Broker activity pagination repeated an execution")
                seen.add(item["id"])
                when = datetime.fromisoformat(item["transaction_time"].replace("Z", "+00:00"))
                qty, price = Decimal(item["qty"]), Decimal(item["price"])
                if item["activity_type"] != "FILL" or not (midnight <= when <= observed_at) or not qty.is_finite() or not price.is_finite() or qty <= 0 or price <= 0:
                    raise ValueError("Broker execution activity is invalid or outside the requested day")
                total += qty*price
            if len(page) < 100: return total
            params["page_token"] = page[-1]["id"]
        raise ValueError("Daily execution coverage exceeds the bounded snapshot; entries require reconciliation")

    def account_activities(self, start: datetime, until: datetime) -> AccountActivityBatch:
        identity = self.paper_identity()
        params = {"after": start.isoformat(), "until": until.isoformat(), "direction": "asc", "page_size": 100}
        activities, seen, limitations, complete = [], set(), [], False
        for _ in range(20):
            page = self._read("account/activities", params)
            if not isinstance(page, list) or len(page) > 100:
                raise ValueError("Invalid broker accounting activity page")
            repeated = False
            for raw in page:
                item = _account_activity(raw, until)
                if item.source_id in seen:
                    repeated = True
                    item = AccountActivity(source_id="duplicate:"+content_hash(raw), kind="unknown", effective_at=until,
                        raw={"reason":"repeated_source_id", "activity":raw})
                seen.add(item.source_id)
                activities.append(item)
                if item.time_precision == "day":
                    limitations.append("Some cash activity timestamps have day precision; intraday posting and flow valuations are unverified")
            if repeated:
                limitations.append("Broker pagination repeated a source activity; coverage is incomplete")
                break
            if len(page) < 100:
                complete = True
                break
            params["page_token"] = page[-1]["id"]
        if not complete: limitations.append("Bounded activity retrieval did not establish full coverage")
        return AccountActivityBatch(provider_id=identity.provider_id, account_id=identity.account_id, evidence_kind=self._evidence_kind,
            coverage_start=start, coverage_end=until, observed_at=now_utc(), complete=complete, source="alpaca-account-activities-v2",
            activities=activities, limitations=sorted(set(limitations)))

    def estimate_price(self, symbol: str) -> float:
        price = float(self._price_estimator(_normalize_symbol(symbol)))
        _positive_finite(price, "estimated price")
        return price

    def submit_order(
        self,
        intent_id: str,
        symbol: str,
        side: OrderSide,
        notional: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> BrokerOrder:
        """Submit an order — market, OTO, or full bracket.

        When ``stop_loss`` and ``take_profit`` are both provided the
        order is sent as ``order_class=bracket`` with two child legs.
        Either one alone produces ``order_class=oto`` with the
        configured protective child. Without either, behaviour is
        unchanged (plain market order).

        Prices are validated against the current quote returned by
        ``price_estimator`` so the broker never sees a stop above the
        take-profit (BUY) or vice-versa (SELL); the API would reject
        those anyway but we catch them before the round-trip.

        Bracket orders cannot use ``notional`` on Alpaca — bracket /
        OTO require a discrete share count. We convert here using
        the estimated price; the share count is rounded down to whole
        shares without rounding the requested size up. A market fill can
        still differ from this quote; exact approval and execution limits
        must be enforced by the submission boundary.
        """

        normalized_symbol = _normalize_symbol(symbol)
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        _positive_finite(notional, "notional")
        budget = Decimal(str(notional)).quantize(Decimal(".01"), rounding=ROUND_DOWN)
        if budget <= 0:
            raise ValueError("notional must cover at least one USD cent")
        for label, value in (("stop_loss", stop_loss), ("take_profit", take_profit)):
            if value is not None:
                _positive_finite(value, label)
        bracket_requested = stop_loss is not None or take_profit is not None

        # Build the base request body. Defaults match the plain-market
        # path so non-bracket callers see no behavioural change.
        body: dict[str, object] = {
            "symbol": normalized_symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "client_order_id": intent_id,
        }

        if bracket_requested:
            current_price = self.estimate_price(normalized_symbol)
            _validate_bracket_pricing(
                side=side,
                current_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            # Alpaca bracket / OTO requires an integer share count (qty);
            # notional is not accepted. Round down so we never oversize
            # the operator's budget.
            quantity = int(budget / Decimal(str(current_price)))
            if quantity < 1:
                raise ValueError("bracket budget cannot cover one whole share at the current quote")
            # Preserve GTC for protective children. Alpaca supports both
            # day and GTC for brackets; this adapter's choice is explicit.
            body["time_in_force"] = "gtc"
            body["qty"] = str(quantity)
            if stop_loss is not None and take_profit is not None:
                body["order_class"] = "bracket"
                body["take_profit"] = {"limit_price": f"{take_profit:.2f}"}
                body["stop_loss"] = {"stop_price": f"{stop_loss:.2f}"}
            else:
                body["order_class"] = "oto"
                if take_profit is not None:
                    body["take_profit"] = {"limit_price": f"{take_profit:.2f}"}
                if stop_loss is not None:
                    body["stop_loss"] = {"stop_price": f"{stop_loss:.2f}"}
        else:
            body["notional"] = str(budget)

        # Resolve credentials up-front so missing-secret / config errors
        # propagate normally rather than getting masked as a "rejected"
        # broker order. Only the broker round-trip is caught below.
        headers = self._headers()
        try:
            response = self._http_client.post(
                f"{self._base_url}/v2/orders",
                headers=headers,
                json=body,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            # Broker rejected the order (HTTP 4xx, connection error,
            # etc). Mirror the request shape so the operator can see
            # what we sent; the service stores this on
            # BrokerOrderRecord.payload for the ladder UI.
            error_payload: dict[str, Any] = {
                "request": body,
                "error": str(exc),
            }
            return BrokerOrder(
                intent_id=intent_id,
                broker=self.broker_name,
                environment=self.environment,
                status="rejected",
                broker_order_id="",
                payload=error_payload,
            )

        payload = response.json()
        return BrokerOrder(
            intent_id=intent_id,
            broker=self.broker_name,
            environment=self.environment,
            status=str(payload["status"]),
            broker_order_id=str(payload["id"]),
            payload={
                "request": body,
                "response": payload,
            },
        )

    def _headers(self) -> dict[str, str]:
        # Bind credentials across account verification and the single POST.
        # API request resolution creates a new adapter when configuration changes.
        if self._credential_headers is None:
            credentials = _parse_credentials(self._secret_store.get_secret(self._secret_ref))
            self._credential_headers = {
                "APCA-API-KEY-ID": credentials["key_id"],
                "APCA-API-SECRET-KEY": credentials["secret_key"],
            }
        return dict(self._credential_headers)


def _positive_finite(value: float, label: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")


def _parse_credentials(raw_secret: str) -> dict[str, str]:
    payload = json.loads(raw_secret)
    key_id = payload.get("key_id") or payload.get("key")
    secret_key = payload.get("secret_key") or payload.get("secret")
    if not key_id or not secret_key:
        raise ValueError("Alpaca broker secret must include key_id and secret_key")
    return {"key_id": str(key_id), "secret_key": str(secret_key)}


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


def _validate_bracket_pricing(
    *,
    side: OrderSide,
    current_price: float,
    stop_loss: float | None,
    take_profit: float | None,
) -> None:
    """Reject orderings that Alpaca's bracket validator would refuse.

    For BUY (long entry) the stop has to sit below the current price
    and the take-profit above it. For SELL (short entry / exit) the
    relationship inverts. When only one leg is set we only check that
    side of the relationship — the other leg is treated as "absent"
    rather than infinite.
    """

    if side == "buy":
        if take_profit is not None and take_profit <= current_price:
            raise ValueError(
                f"take_profit ({take_profit}) must be greater than current price "
                f"({current_price}) for a BUY bracket"
            )
        if stop_loss is not None and stop_loss >= current_price:
            raise ValueError(
                f"stop_loss ({stop_loss}) must be less than current price "
                f"({current_price}) for a BUY bracket"
            )
    else:  # sell
        if take_profit is not None and take_profit >= current_price:
            raise ValueError(
                f"take_profit ({take_profit}) must be less than current price "
                f"({current_price}) for a SELL bracket"
            )
        if stop_loss is not None and stop_loss <= current_price:
            raise ValueError(
                f"stop_loss ({stop_loss}) must be greater than current price "
                f"({current_price}) for a SELL bracket"
            )


def _order_observation(payload: dict) -> PaperOrderObservation:
    quantity = Decimal(payload["qty"])
    if not quantity.is_finite() or quantity != quantity.to_integral_value():
        raise ValueError("Broker returned a non-whole exact order quantity")
    status = str(payload["status"])
    known = {"accepted", "new", "partially_filled", "filled", "canceled", "expired", "rejected", "pending_cancel", "pending_new"}
    return PaperOrderObservation(client_order_id=payload["client_order_id"], broker_order_id=payload["id"], symbol=payload["symbol"], side=payload["side"],
        quantity=int(quantity), filled_quantity=payload["filled_qty"], average_fill_price_usd=payload["filled_avg_price"], status=status if status in known else "unknown",
        observed_at=now_utc(), broker_updated_at=payload.get("updated_at"), raw=payload)


def _economic_state(state):
    account, positions, orders = state
    return (
        tuple(account[key] for key in ("id", "cash", "currency", "trading_blocked", "account_blocked", "status")),
        sorted((p["symbol"], p["qty"], p["cost_basis"]) for p in positions),
        sorted((o["id"], o["client_order_id"], o["symbol"], o["side"], o["qty"], o["filled_qty"], o["status"], o["type"], o.get("limit_price")) for o in orders),
    )


def _account_activity(raw: dict, observed_at: datetime) -> AccountActivity:
    source_id = str(raw.get("id") or "unidentified:"+content_hash(raw))
    try:
        if not raw.get("id"): raise ValueError("missing source activity ID")
        if raw.get("activity_type") == "FILL":
            return AccountActivity(source_id=source_id, kind="fill", effective_at=raw["transaction_time"], symbol=raw["symbol"], side=raw["side"],
                quantity=raw["qty"], price_usd=raw["price"], broker_order_id=raw["order_id"], raw=raw)
        kind = {"CSD":"deposit", "CSW":"withdrawal", "DIV":"dividend", "INT":"interest", "FEE":"fee"}.get(raw.get("activity_type"), "unknown")
        # The documented NTA date is an occurrence/settlement date, not proof
        # of an intraday posting instant. Do not derive time from an opaque ID.
        value = str(raw["date"])
        precise = len(value) > 10 and ("+" in value[10:] or value.endswith("Z"))
        when = datetime.fromisoformat(value.replace("Z", "+00:00")) if precise else datetime.fromisoformat(value[:10]).replace(tzinfo=timezone.utc)
        fields = {"cash_amount_usd":raw["net_amount"]} if kind != "unknown" else {}
        if kind == "dividend": fields["symbol"] = raw.get("symbol")
        if kind == "fee": fields["broker_order_id"] = raw.get("order_id")
        return AccountActivity(source_id=source_id, kind=kind, effective_at=when, time_precision="instant" if precise else "day", raw=raw, **fields)
    except (KeyError, ValueError, TypeError):
        return AccountActivity(source_id=source_id, kind="unknown", effective_at=observed_at, raw={"reason":"unsupported_or_incomplete_activity", "activity":raw})
