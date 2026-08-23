from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .pricing import PriceQuote, format_money, money, quote_to_order_totals

TERMINAL_STATUSES = {"cancelled", "refunded", "rejected"}
REFUNDABLE_STATUSES = {"paid", "partially_refunded"}
ALLOWED_TRANSITIONS = {("draft", "quoted", "quote_created"), ("quoted", "inventory_reserved", "inventory_reserved"), ("quoted", "held_for_review", "risk_hold"), ("held_for_review", "inventory_reserved", "risk_released"), ("inventory_reserved", "paid", "payment_captured"), ("inventory_reserved", "cancelled", "reservation_released"), ("paid", "partially_refunded", "partial_refund"), ("partially_refunded", "refunded", "final_refund"), ("paid", "refunded", "full_refund")}


class OrderError(ValueError):
    pass


@dataclass(frozen=True)
class OrderValidationResult:
    valid: bool
    problems: list[str] = field(default_factory=list)

    def require_valid(self) -> None:
        if not self.valid:
            raise OrderError(",".join(self.problems))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def next_order_id(orders: list[dict[str, Any]]) -> str:
    values = [int(str(order.get("id"))[1:]) for order in orders if str(order.get("id", "")).startswith("O") and str(order.get("id"))[1:].isdigit()]
    return f"O{(max(values) if values else 1000) + 1}"


def find_order(orders: list[dict[str, Any]], order_id: str) -> dict[str, Any] | None:
    return next((order for order in orders if order.get("id") == order_id), None)


def require_order(orders: list[dict[str, Any]], order_id: str) -> dict[str, Any]:
    order = find_order(orders, order_id)
    if order is None:
        raise OrderError(f"unknown order {order_id}")
    return order


def order_event(event: str, actor: str, from_status: str, to_status: str, note: str = "") -> dict[str, Any]:
    record = {"event": event, "actor": actor, "from": from_status, "to": to_status, "at": utc_now()}
    if note:
        record["note"] = note
    return record


def transition_order(order: dict[str, Any], new_status: str, event: str, actor: str, note: str = "") -> None:
    old_status = str(order.get("status", "draft"))
    if old_status in TERMINAL_STATUSES:
        raise OrderError(f"cannot transition terminal order {order.get('id')}")
    if (old_status, new_status, event) not in ALLOWED_TRANSITIONS:
        raise OrderError(f"transition {old_status}->{new_status} via {event} is not allowed")
    order["status"] = new_status
    order["updated_at"] = utc_now()
    order.setdefault("events", []).append(order_event(event, actor, old_status, new_status, note))


def build_order_record(order_id: str, customer_id: str, sku: str, quantity: int, quote: PriceQuote) -> dict[str, Any]:
    totals = quote_to_order_totals(quote)
    return {"id": order_id, "customer_id": customer_id, "sku": sku, "quantity": quantity, "status": "quoted", "subtotal": totals["subtotal"], "discount_total": totals["discount_total"], "tax_total": totals["tax_total"], "total": totals["total"], "applied_coupons": list(quote.applied_coupons), "rejected_coupons": list(quote.rejected_coupons), "created_at": utc_now(), "updated_at": utc_now(), "paid_at": None, "reserved_at": None, "risk_reasons": [], "events": [order_event("quote_created", "system", "draft", "quoted")]}


def build_order_from_quote(order_id: str, quote: PriceQuote) -> dict[str, Any]:
    return build_order_record(order_id, quote.customer_id, quote.sku, quote.quantity, quote)


def mark_order_reserved(order: dict[str, Any], actor: str = "system") -> None:
    transition_order(order, "inventory_reserved", "inventory_reserved", actor)
    order["reserved_at"] = utc_now()


def mark_order_held(order: dict[str, Any], reasons: list[str], actor: str = "risk") -> None:
    transition_order(order, "held_for_review", "risk_hold", actor, ",".join(reasons))
    order["risk_reasons"] = list(reasons)


def cancel_reserved_order(order: dict[str, Any], actor: str = "system", note: str = "") -> None:
    transition_order(order, "cancelled", "reservation_released", actor, note)
    order["cancelled_at"] = utc_now()


def validate_order_record(order: dict[str, Any]) -> OrderValidationResult:
    problems: list[str] = []
    if not str(order.get("id", "")).startswith("O"):
        problems.append("order_id_required")
    if not order.get("customer_id"):
        problems.append("customer_id_required")
    if not order.get("sku"):
        problems.append("sku_required")
    if int(order.get("quantity", 0) or 0) <= 0:
        problems.append("quantity_must_be_positive")
    return OrderValidationResult(not problems, problems)


def is_terminal(order: dict[str, Any]) -> bool:
    return str(order.get("status")) in TERMINAL_STATUSES


def is_paid(order: dict[str, Any]) -> bool:
    return str(order.get("status")) in {"paid", "shipped", "delivered", "partially_refunded", "refunded"}


def is_inventory_reserved(order: dict[str, Any]) -> bool:
    return str(order.get("status")) == "inventory_reserved"


def is_refundable(order: dict[str, Any]) -> bool:
    return str(order.get("status")) in REFUNDABLE_STATUSES


def order_total(order: dict[str, Any]) -> Decimal:
    return money(order.get("total", "0"))


def order_discount(order: dict[str, Any]) -> Decimal:
    return money(order.get("discount_total", "0"))


def order_tax(order: dict[str, Any]) -> Decimal:
    return money(order.get("tax_total", "0"))


def placed_order_cli_line(order: dict[str, Any]) -> str:
    reasons = ",".join(order.get("risk_reasons", [])) if order.get("risk_reasons") else "none"
    return f"order_id={order.get('id')} status={order.get('status')} customer={order.get('customer_id')} sku={order.get('sku')} qty={order.get('quantity')} total={order_total(order):.2f} risk_reasons={reasons}"


def cancel_order_cli_line(order: dict[str, Any], released: int) -> str:
    return f"order_id={order.get('id')} status={order.get('status')} released={released}"


def filter_paid_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if is_paid(order)]


def count_paid_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_paid_orders(orders))


def total_paid_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_paid_orders(orders)), Decimal("0.00")))


def quantity_paid_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_paid_orders(orders)))


def filter_terminal_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if is_terminal(order)]


def count_terminal_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_terminal_orders(orders))


def total_terminal_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_terminal_orders(orders)), Decimal("0.00")))


def quantity_terminal_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_terminal_orders(orders)))


def filter_refundable_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if is_refundable(order)]


def count_refundable_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_refundable_orders(orders))


def total_refundable_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_refundable_orders(orders)), Decimal("0.00")))


def quantity_refundable_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_refundable_orders(orders)))


def filter_reserved_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if is_inventory_reserved(order)]


def count_reserved_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_reserved_orders(orders))


def total_reserved_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_reserved_orders(orders)), Decimal("0.00")))


def quantity_reserved_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_reserved_orders(orders)))


def filter_held_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order.get('status') == 'held_for_review']


def count_held_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_held_orders(orders))


def total_held_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_held_orders(orders)), Decimal("0.00")))


def quantity_held_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_held_orders(orders)))


def filter_cancelled_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order.get('status') == 'cancelled']


def count_cancelled_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_cancelled_orders(orders))


def total_cancelled_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_cancelled_orders(orders)), Decimal("0.00")))


def quantity_cancelled_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_cancelled_orders(orders)))


def filter_discounted_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order_discount(order) > Decimal('0.00')]


def count_discounted_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_discounted_orders(orders))


def total_discounted_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_discounted_orders(orders)), Decimal("0.00")))


def quantity_discounted_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_discounted_orders(orders)))


def filter_taxable_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order_tax(order) > Decimal('0.00')]


def count_taxable_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_taxable_orders(orders))


def total_taxable_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_taxable_orders(orders)), Decimal("0.00")))


def quantity_taxable_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_taxable_orders(orders)))


def filter_high_value_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order_total(order) >= Decimal('100.00')]


def count_high_value_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_high_value_orders(orders))


def total_high_value_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_high_value_orders(orders)), Decimal("0.00")))


def quantity_high_value_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_high_value_orders(orders)))


def filter_low_value_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order_total(order) < Decimal('50.00')]


def count_low_value_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_low_value_orders(orders))


def total_low_value_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_low_value_orders(orders)), Decimal("0.00")))


def quantity_low_value_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_low_value_orders(orders)))


def filter_multi_unit_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if int(order.get('quantity', 0) or 0) > 1]


def count_multi_unit_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_multi_unit_orders(orders))


def total_multi_unit_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_multi_unit_orders(orders)), Decimal("0.00")))


def quantity_multi_unit_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_multi_unit_orders(orders)))


def filter_single_unit_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if int(order.get('quantity', 0) or 0) == 1]


def count_single_unit_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_single_unit_orders(orders))


def total_single_unit_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_single_unit_orders(orders)), Decimal("0.00")))


def quantity_single_unit_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_single_unit_orders(orders)))


def filter_coupon_used_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if bool(order.get('applied_coupons'))]


def count_coupon_used_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_coupon_used_orders(orders))


def total_coupon_used_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_coupon_used_orders(orders)), Decimal("0.00")))


def quantity_coupon_used_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_coupon_used_orders(orders)))


def filter_risk_flagged_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if bool(order.get('risk_reasons'))]


def count_risk_flagged_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_risk_flagged_orders(orders))


def total_risk_flagged_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_risk_flagged_orders(orders)), Decimal("0.00")))


def quantity_risk_flagged_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_risk_flagged_orders(orders)))


def filter_missing_events_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if not order.get('events')]


def count_missing_events_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_missing_events_orders(orders))


def total_missing_events_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_missing_events_orders(orders)), Decimal("0.00")))


def quantity_missing_events_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_missing_events_orders(orders)))


def filter_has_events_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if bool(order.get('events'))]


def count_has_events_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_has_events_orders(orders))


def total_has_events_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_has_events_orders(orders)), Decimal("0.00")))


def quantity_has_events_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_has_events_orders(orders)))


def filter_physical_sku_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if not str(order.get('sku', '')).startswith('SKU-DIGI')]


def count_physical_sku_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_physical_sku_orders(orders))


def total_physical_sku_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_physical_sku_orders(orders)), Decimal("0.00")))


def quantity_physical_sku_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_physical_sku_orders(orders)))


def filter_digital_sku_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if str(order.get('sku', '')).startswith('SKU-DIGI')]


def count_digital_sku_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_digital_sku_orders(orders))


def total_digital_sku_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_digital_sku_orders(orders)), Decimal("0.00")))


def quantity_digital_sku_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_digital_sku_orders(orders)))


def filter_morning_created_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if str(order.get('created_at', 'T00:')).split('T')[-1][:2] < '12']


def count_morning_created_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_morning_created_orders(orders))


def total_morning_created_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_morning_created_orders(orders)), Decimal("0.00")))


def quantity_morning_created_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_morning_created_orders(orders)))


def filter_evening_created_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if str(order.get('created_at', 'T00:')).split('T')[-1][:2] >= '18']


def count_evening_created_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_evening_created_orders(orders))


def total_evening_created_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_evening_created_orders(orders)), Decimal("0.00")))


def quantity_evening_created_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_evening_created_orders(orders)))


def filter_zero_discount_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order_discount(order) == Decimal('0.00')]


def count_zero_discount_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_zero_discount_orders(orders))


def total_zero_discount_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_zero_discount_orders(orders)), Decimal("0.00")))


def quantity_zero_discount_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_zero_discount_orders(orders)))


def filter_deep_discount_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order for order in orders if order_discount(order) >= Decimal('20.00')]


def count_deep_discount_orders(orders: Iterable[dict[str, Any]]) -> int:
    return len(filter_deep_discount_orders(orders))


def total_deep_discount_orders(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in filter_deep_discount_orders(orders)), Decimal("0.00")))


def quantity_deep_discount_orders(orders: Iterable[dict[str, Any]]) -> int:
    return sum((int(order.get("quantity", 0) or 0) for order in filter_deep_discount_orders(orders)))
def group_orders_by_customer_id(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("customer_id", "unknown")), []).append(order)
    return grouped


def count_orders_by_customer_id(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_customer_id(orders).items())}


def total_orders_by_customer_id(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_customer_id(orders).items())}


def quantity_orders_by_customer_id(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_customer_id(orders).items())}


def group_orders_by_sku(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("sku", "unknown")), []).append(order)
    return grouped


def count_orders_by_sku(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_sku(orders).items())}


def total_orders_by_sku(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_sku(orders).items())}


def quantity_orders_by_sku(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_sku(orders).items())}


def group_orders_by_status(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("status", "unknown")), []).append(order)
    return grouped


def count_orders_by_status(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_status(orders).items())}


def total_orders_by_status(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_status(orders).items())}


def quantity_orders_by_status(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_status(orders).items())}


def group_orders_by_quantity(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("quantity", "unknown")), []).append(order)
    return grouped


def count_orders_by_quantity(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_quantity(orders).items())}


def total_orders_by_quantity(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_quantity(orders).items())}


def quantity_orders_by_quantity(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_quantity(orders).items())}


def group_orders_by_subtotal(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("subtotal", "unknown")), []).append(order)
    return grouped


def count_orders_by_subtotal(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_subtotal(orders).items())}


def total_orders_by_subtotal(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_subtotal(orders).items())}


def quantity_orders_by_subtotal(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_subtotal(orders).items())}


def group_orders_by_discount_total(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("discount_total", "unknown")), []).append(order)
    return grouped


def count_orders_by_discount_total(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_discount_total(orders).items())}


def total_orders_by_discount_total(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_discount_total(orders).items())}


def quantity_orders_by_discount_total(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_discount_total(orders).items())}


def group_orders_by_tax_total(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("tax_total", "unknown")), []).append(order)
    return grouped


def count_orders_by_tax_total(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_tax_total(orders).items())}


def total_orders_by_tax_total(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_tax_total(orders).items())}


def quantity_orders_by_tax_total(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_tax_total(orders).items())}


def group_orders_by_total(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("total", "unknown")), []).append(order)
    return grouped


def count_orders_by_total(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_total(orders).items())}


def total_orders_by_total(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_total(orders).items())}


def quantity_orders_by_total(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_total(orders).items())}


def group_orders_by_created_at(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("created_at", "unknown")), []).append(order)
    return grouped


def count_orders_by_created_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_created_at(orders).items())}


def total_orders_by_created_at(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_created_at(orders).items())}


def quantity_orders_by_created_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_created_at(orders).items())}


def group_orders_by_updated_at(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("updated_at", "unknown")), []).append(order)
    return grouped


def count_orders_by_updated_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_updated_at(orders).items())}


def total_orders_by_updated_at(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_updated_at(orders).items())}


def quantity_orders_by_updated_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_updated_at(orders).items())}


def group_orders_by_paid_at(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("paid_at", "unknown")), []).append(order)
    return grouped


def count_orders_by_paid_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_paid_at(orders).items())}


def total_orders_by_paid_at(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_paid_at(orders).items())}


def quantity_orders_by_paid_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_paid_at(orders).items())}


def group_orders_by_reserved_at(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("reserved_at", "unknown")), []).append(order)
    return grouped


def count_orders_by_reserved_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_reserved_at(orders).items())}


def total_orders_by_reserved_at(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_reserved_at(orders).items())}


def quantity_orders_by_reserved_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_reserved_at(orders).items())}


def group_orders_by_payment_id(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("payment_id", "unknown")), []).append(order)
    return grouped


def count_orders_by_payment_id(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_payment_id(orders).items())}


def total_orders_by_payment_id(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_payment_id(orders).items())}


def quantity_orders_by_payment_id(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_payment_id(orders).items())}


def group_orders_by_cancelled_at(orders: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get("cancelled_at", "unknown")), []).append(order)
    return grouped


def count_orders_by_cancelled_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_orders_by_cancelled_at(orders).items())}


def total_orders_by_cancelled_at(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((order_total(order) for order in rows), Decimal("0.00"))) for key, rows in sorted(group_orders_by_cancelled_at(orders).items())}


def quantity_orders_by_cancelled_at(orders: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: sum((int(order.get("quantity", 0) or 0) for order in rows)) for key, rows in sorted(group_orders_by_cancelled_at(orders).items())}
def finance_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def finance_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finance_order_snapshot(order) for order in orders]


def finance_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def operations_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def operations_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [operations_order_snapshot(order) for order in orders]


def operations_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def support_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def support_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [support_order_snapshot(order) for order in orders]


def support_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def risk_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def risk_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [risk_order_snapshot(order) for order in orders]


def risk_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def fulfillment_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def fulfillment_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [fulfillment_order_snapshot(order) for order in orders]


def fulfillment_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def coupon_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def coupon_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [coupon_order_snapshot(order) for order in orders]


def coupon_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def tax_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def tax_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tax_order_snapshot(order) for order in orders]


def tax_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def payment_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def payment_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [payment_order_snapshot(order) for order in orders]


def payment_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def reservation_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def reservation_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [reservation_order_snapshot(order) for order in orders]


def reservation_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def cancellation_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def cancellation_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [cancellation_order_snapshot(order) for order in orders]


def cancellation_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def refund_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def refund_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund_order_snapshot(order) for order in orders]


def refund_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def audit_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def audit_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [audit_order_snapshot(order) for order in orders]


def audit_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def pipeline_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def pipeline_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [pipeline_order_snapshot(order) for order in orders]


def pipeline_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def exception_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def exception_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [exception_order_snapshot(order) for order in orders]


def exception_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def daily_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def daily_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [daily_order_snapshot(order) for order in orders]


def daily_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def weekly_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def weekly_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [weekly_order_snapshot(order) for order in orders]


def weekly_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def customer_success_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def customer_success_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [customer_success_order_snapshot(order) for order in orders]


def customer_success_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def inventory_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def inventory_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [inventory_order_snapshot(order) for order in orders]


def inventory_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def margin_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def margin_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [margin_order_snapshot(order) for order in orders]


def margin_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))


def compliance_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "customer_id": order.get("customer_id"),
        "sku": order.get("sku"),
        "quantity": int(order.get("quantity", 0) or 0),
        "status": order.get("status"),
        "subtotal": format_money(money(order.get("subtotal", "0"))),
        "discount_total": format_money(order_discount(order)),
        "tax_total": format_money(order_tax(order)),
        "total": format_money(order_total(order)),
        "event_count": len(order.get("events", [])),
    }


def compliance_order_batch(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compliance_order_snapshot(order) for order in orders]


def compliance_order_total(orders: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((order_total(order) for order in orders), Decimal("0.00")))
