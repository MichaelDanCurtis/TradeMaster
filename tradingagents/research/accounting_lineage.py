"""Validated broker-observed protection lineage, separate from FIFO ownership."""
from decimal import Decimal

from tradingagents.research.accounting_contracts import AccountOrderFamily
from tradingagents.research.repository import ConflictError


def protection_lineage(attempts, orders, previous, request):
    by_parent = {attempt.broker_order_id: attempt for attempt in attempts if attempt.broker_order_id}
    attribution = {parent: f"deployment:{orders[attempt.order_id].deployment_id}" if orders[attempt.order_id].deployment_id else "manual"
                   for parent, attempt in by_parent.items()}
    protected = {parent: attempt for parent, attempt in by_parent.items()
                 if any(orders[attempt.order_id].order.get(field) is not None for field in ("stop_loss_usd", "take_profit_usd"))}
    links, errors, current = {}, [], []
    families = [(AccountOrderFamily.model_validate(value), False) for record in previous
                for value in record.request.get("order_families", [])]
    families.extend((family, True) for family in request.order_families)
    seen = set()
    for family, fresh in families:
        parent = family.parent
        attempt = protected.get(parent.broker_order_id)
        if attempt is None:
            raise ConflictError("Protective family has no matching submitted protected order in this account")
        order = orders[attempt.order_id]
        exact = order.order
        if (parent.client_order_id, parent.symbol, parent.side, parent.quantity) != (attempt.client_order_id, exact["symbol"], exact["side"], exact["quantity"]):
            raise ConflictError("Protective family differs from the exact approved parent")
        expected = {role for role, field in (("stop_loss", "stop_loss_usd"), ("take_profit", "take_profit_usd")) if exact.get(field) is not None}
        actual = {child.role for child in family.children}
        if not actual.issubset(expected):
            raise ConflictError("Broker family includes an unapproved protective role")
        if fresh:
            seen.add(parent.broker_order_id)
            if parent.filled_quantity and expected != actual:
                errors.append({"code": "protective_children_missing", "broker_order_id": parent.broker_order_id})
        for child in family.children:
            leg = child.observation
            link = {"parent_broker_order_id": parent.broker_order_id, "parent_order_id": order.order_id,
                    "broker_order_id": leg.broker_order_id, "client_order_id": leg.client_order_id,
                    "symbol": leg.symbol, "side": leg.side, "protection_role": child.role,
                    "executor": attribution[parent.broker_order_id]}
            if leg.broker_order_id in by_parent or (leg.broker_order_id in links and links[leg.broker_order_id] != link):
                raise ConflictError("Protective child is claimed by incompatible parent orders")
            links[leg.broker_order_id] = link
            attribution[leg.broker_order_id] = link["executor"]
            if fresh:
                approved_price = Decimal(exact[f"{child.role}_usd"])
                actual_price = child.stop_price_usd if child.role == "stop_loss" else child.limit_price_usd
                changed = actual_price != approved_price or (child.role == "stop_loss" and child.limit_price_usd is not None)
                if changed:
                    errors.append({"code": "protective_terms_changed", "broker_order_id": leg.broker_order_id,
                                   "detail": "Observed protective pricing differs from the approved parent terms"})
                current.append({**link, "status": leg.status, "quantity": str(leg.quantity),
                    "filled_quantity": str(leg.filled_quantity), "remaining_quantity": str(Decimal(leg.quantity)-leg.filled_quantity),
                    "limit_price_usd": str(child.limit_price_usd) if child.limit_price_usd is not None else None,
                    "stop_price_usd": str(child.stop_price_usd) if child.stop_price_usd is not None else None,
                    "observed_at": leg.observed_at.isoformat(), "approved_terms_match": not changed})
    for parent in protected.keys()-seen:
        errors.append({"code": "protective_lineage_unobserved", "broker_order_id": parent,
                       "detail": "Current protective order-family coverage is required, including completed parents"})
    return attribution, links, current, errors


def apply_fill_lineage(activities, links):
    errors = []
    for activity in activities:
        link = links.get(activity.broker_order_id)
        if link and activity.kind == "fill" and (activity.symbol, activity.side) != (link["symbol"], link["side"]):
            errors.append({"code": "protective_fill_identity_mismatch", "source_id": activity.source_id})
    return errors
