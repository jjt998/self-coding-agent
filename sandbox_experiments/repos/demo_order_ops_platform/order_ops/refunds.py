from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

REFUNDABLE_STATUSES = {"paid", "partially_refunded"}
RESTOCK_REASONS = {"wrong_item", "buyer_remorse", "duplicate_order"}
NO_RESTOCK_REASONS = {"damaged", "missing_parts", "fraud", "lost_in_transit"}


class RefundError(ValueError):
    pass


@dataclass(frozen=True)
class RefundDecision:
    allowed: bool
    amount: Decimal
    restock: bool
    reason_code: str
    message: str
    remaining_before: Decimal = Decimal("0.00")
    remaining_after: Decimal = Decimal("0.00")
    full_refund: bool = False
    warnings: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_money(value: Any) -> str:
    return f"{money(value):.2f}"


def next_refund_id(refunds: list[dict[str, Any]]) -> str:
    values = [int(str(refund.get("id"))[1:]) for refund in refunds if str(refund.get("id", "")).startswith("R") and str(refund.get("id"))[1:].isdigit()]
    return f"R{(max(values) if values else 0) + 1:04d}"


def refunds_for_order(refunds: Iterable[dict[str, Any]], order_id: str) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get("order_id") == order_id]


def refunded_total_for_order(refunds: Iterable[dict[str, Any]], order_id: str) -> Decimal:
    return money(sum((money(refund.get("amount", "0")) for refund in refunds_for_order(refunds, order_id)), Decimal("0.00")))


def refundable_total(order: dict[str, Any], refunds: list[dict[str, Any]]) -> Decimal:
    return max(Decimal("0.00"), money(order.get("total", "0")) - refunded_total_for_order(refunds, str(order.get("id"))))


def normalize_reason(reason: str) -> str:
    return reason.strip().lower().replace(" ", "_")


def evaluate_refund(order: dict[str, Any], refunds: list[dict[str, Any]], amount: Any, reason: str) -> RefundDecision:
    requested = money(amount)
    normalized_reason = normalize_reason(reason)
    remaining = refundable_total(order, refunds)
    if order.get("status") not in REFUNDABLE_STATUSES:
        return RefundDecision(False, Decimal("0.00"), False, "status_not_refundable", "Order is not refundable.")
    if requested <= Decimal("0.00"):
        return RefundDecision(False, Decimal("0.00"), False, "invalid_amount", "Refund amount must be positive.")
    if requested > remaining:
        return RefundDecision(False, remaining, False, "amount_exceeds_remaining", "Refund exceeds remaining total.")
    if not normalized_reason:
        return RefundDecision(False, Decimal("0.00"), False, "reason_required", "Refund reason is required.")
    remaining_after = money(remaining - requested)
    return RefundDecision(True, requested, normalized_reason in RESTOCK_REASONS, "approved", "Refund approved.", remaining, remaining_after, remaining_after <= Decimal("0.01"), [])


def process_partial_refund(order: dict[str, Any], refunds: list[dict[str, Any]], amount: Any, reason: str, actor: str = "system") -> tuple[dict[str, Any], RefundDecision]:
    decision = evaluate_refund(order, refunds, amount, reason)
    if not decision.allowed:
        raise RefundError(decision.reason_code)
    refund = {"id": next_refund_id(refunds), "order_id": order.get("id"), "amount": format_money(decision.amount), "reason": normalize_reason(reason), "restock": decision.restock, "created_at": utc_now(), "actor": actor, "status": "approved"}
    refunds.append(refund)
    old_status = str(order.get("status"))
    order["status"] = "refunded" if decision.full_refund else "partially_refunded"
    order["updated_at"] = utc_now()
    order.setdefault("events", []).append({"event": "final_refund" if decision.full_refund else "partial_refund", "actor": actor, "from": old_status, "to": order["status"], "at": utc_now(), "note": f"refund={refund['id']} amount={refund['amount']}"})
    return refund, decision


def refund_cli_line(refund: dict[str, Any], decision: RefundDecision) -> str:
    return f"refund_id={refund.get('id')} order_id={refund.get('order_id')} amount={money(refund.get('amount')):.2f} status={refund.get('status')} restock={str(decision.restock).lower()} remaining={decision.remaining_after:.2f}"


def refund_ratio(order: dict[str, Any], refunds: Iterable[dict[str, Any]]) -> Decimal:
    total = money(order.get("total", "0"))
    if total <= Decimal("0.00"):
        return Decimal("0.00")
    return money(refunded_total_for_order(refunds, str(order.get("id"))) / total * Decimal("100"))


def restock_quantity_for_refund(order: dict[str, Any], refund: dict[str, Any]) -> int:
    if not refund.get("restock"):
        return 0
    total = money(order.get("total", "0"))
    quantity = int(order.get("quantity", 0) or 0)
    if total <= Decimal("0.00"):
        return 0
    return max(1, min(quantity, int((Decimal(quantity) * (money(refund.get("amount", "0")) / total)).to_integral_value(rounding=ROUND_HALF_UP))))


def filter_restock_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('restock')]


def count_restock_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_restock_refunds(refunds))


def total_restock_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_restock_refunds(refunds)), Decimal("0.00")))


def order_ids_for_restock_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_restock_refunds(refunds)})


def filter_non_restock_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if not refund.get('restock')]


def count_non_restock_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_non_restock_refunds(refunds))


def total_non_restock_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_non_restock_refunds(refunds)), Decimal("0.00")))


def order_ids_for_non_restock_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_non_restock_refunds(refunds)})


def filter_approved_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('status') == 'approved']


def count_approved_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_approved_refunds(refunds))


def total_approved_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_approved_refunds(refunds)), Decimal("0.00")))


def order_ids_for_approved_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_approved_refunds(refunds)})


def filter_large_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if money(refund.get('amount', '0')) >= Decimal('100.00')]


def count_large_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_large_refunds(refunds))


def total_large_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_large_refunds(refunds)), Decimal("0.00")))


def order_ids_for_large_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_large_refunds(refunds)})


def filter_small_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if money(refund.get('amount', '0')) < Decimal('25.00')]


def count_small_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_small_refunds(refunds))


def total_small_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_small_refunds(refunds)), Decimal("0.00")))


def order_ids_for_small_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_small_refunds(refunds)})


def filter_damaged_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('reason') == 'damaged']


def count_damaged_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_damaged_refunds(refunds))


def total_damaged_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_damaged_refunds(refunds)), Decimal("0.00")))


def order_ids_for_damaged_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_damaged_refunds(refunds)})


def filter_buyer_remorse_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('reason') == 'buyer_remorse']


def count_buyer_remorse_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_buyer_remorse_refunds(refunds))


def total_buyer_remorse_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_buyer_remorse_refunds(refunds)), Decimal("0.00")))


def order_ids_for_buyer_remorse_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_buyer_remorse_refunds(refunds)})


def filter_wrong_item_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('reason') == 'wrong_item']


def count_wrong_item_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_wrong_item_refunds(refunds))


def total_wrong_item_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_wrong_item_refunds(refunds)), Decimal("0.00")))


def order_ids_for_wrong_item_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_wrong_item_refunds(refunds)})


def filter_fraud_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('reason') == 'fraud']


def count_fraud_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_fraud_refunds(refunds))


def total_fraud_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_fraud_refunds(refunds)), Decimal("0.00")))


def order_ids_for_fraud_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_fraud_refunds(refunds)})


def filter_duplicate_order_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('reason') == 'duplicate_order']


def count_duplicate_order_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_duplicate_order_refunds(refunds))


def total_duplicate_order_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_duplicate_order_refunds(refunds)), Decimal("0.00")))


def order_ids_for_duplicate_order_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_duplicate_order_refunds(refunds)})


def filter_over_50_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if money(refund.get('amount', '0')) >= Decimal('50.00')]


def count_over_50_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_over_50_refunds(refunds))


def total_over_50_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_over_50_refunds(refunds)), Decimal("0.00")))


def order_ids_for_over_50_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_over_50_refunds(refunds)})


def filter_under_50_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if money(refund.get('amount', '0')) < Decimal('50.00')]


def count_under_50_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_under_50_refunds(refunds))


def total_under_50_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_under_50_refunds(refunds)), Decimal("0.00")))


def order_ids_for_under_50_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_under_50_refunds(refunds)})


def filter_has_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if bool(refund.get('actor'))]


def count_has_actor_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_has_actor_refunds(refunds))


def total_has_actor_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_has_actor_refunds(refunds)), Decimal("0.00")))


def order_ids_for_has_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_has_actor_refunds(refunds)})


def filter_missing_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if not refund.get('actor')]


def count_missing_actor_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_missing_actor_refunds(refunds))


def total_missing_actor_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_missing_actor_refunds(refunds)), Decimal("0.00")))


def order_ids_for_missing_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_missing_actor_refunds(refunds)})


def filter_system_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('actor') == 'system']


def count_system_actor_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_system_actor_refunds(refunds))


def total_system_actor_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_system_actor_refunds(refunds)), Decimal("0.00")))


def order_ids_for_system_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_system_actor_refunds(refunds)})


def filter_finance_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if refund.get('actor') == 'finance']


def count_finance_actor_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_finance_actor_refunds(refunds))


def total_finance_actor_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_finance_actor_refunds(refunds)), Decimal("0.00")))


def order_ids_for_finance_actor_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_finance_actor_refunds(refunds)})


def filter_round_amount_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if money(refund.get('amount', '0')) == money(int(money(refund.get('amount', '0'))))]


def count_round_amount_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_round_amount_refunds(refunds))


def total_round_amount_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_round_amount_refunds(refunds)), Decimal("0.00")))


def order_ids_for_round_amount_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_round_amount_refunds(refunds)})


def filter_fractional_amount_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if money(refund.get('amount', '0')) != money(int(money(refund.get('amount', '0'))))]


def count_fractional_amount_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_fractional_amount_refunds(refunds))


def total_fractional_amount_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_fractional_amount_refunds(refunds)), Decimal("0.00")))


def order_ids_for_fractional_amount_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_fractional_amount_refunds(refunds)})


def filter_morning_refund_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if str(refund.get('created_at', 'T00:')).split('T')[-1][:2] < '12']


def count_morning_refund_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_morning_refund_refunds(refunds))


def total_morning_refund_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_morning_refund_refunds(refunds)), Decimal("0.00")))


def order_ids_for_morning_refund_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_morning_refund_refunds(refunds)})


def filter_evening_refund_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if str(refund.get('created_at', 'T00:')).split('T')[-1][:2] >= '18']


def count_evening_refund_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_evening_refund_refunds(refunds))


def total_evening_refund_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_evening_refund_refunds(refunds)), Decimal("0.00")))


def order_ids_for_evening_refund_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_evening_refund_refunds(refunds)})


def filter_positive_amount_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if money(refund.get('amount', '0')) > Decimal('0.00')]


def count_positive_amount_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_positive_amount_refunds(refunds))


def total_positive_amount_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_positive_amount_refunds(refunds)), Decimal("0.00")))


def order_ids_for_positive_amount_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_positive_amount_refunds(refunds)})


def filter_missing_created_at_refunds(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [refund for refund in refunds if not refund.get('created_at')]


def count_missing_created_at_refunds(refunds: Iterable[dict[str, Any]]) -> int:
    return len(filter_missing_created_at_refunds(refunds))


def total_missing_created_at_refunds(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in filter_missing_created_at_refunds(refunds)), Decimal("0.00")))


def order_ids_for_missing_created_at_refunds(refunds: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({str(refund.get("order_id")) for refund in filter_missing_created_at_refunds(refunds)})
def group_refunds_by_id(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("id", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_id(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_id(refunds).items())}


def total_refunds_by_id(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_id(refunds).items())}


def order_ids_by_refund_id(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_id(refunds).items())}


def group_refunds_by_order_id(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("order_id", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_order_id(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_order_id(refunds).items())}


def total_refunds_by_order_id(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_order_id(refunds).items())}


def order_ids_by_refund_order_id(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_order_id(refunds).items())}


def group_refunds_by_amount(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("amount", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_amount(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_amount(refunds).items())}


def total_refunds_by_amount(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_amount(refunds).items())}


def order_ids_by_refund_amount(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_amount(refunds).items())}


def group_refunds_by_reason(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("reason", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_reason(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_reason(refunds).items())}


def total_refunds_by_reason(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_reason(refunds).items())}


def order_ids_by_refund_reason(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_reason(refunds).items())}


def group_refunds_by_restock(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("restock", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_restock(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_restock(refunds).items())}


def total_refunds_by_restock(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_restock(refunds).items())}


def order_ids_by_refund_restock(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_restock(refunds).items())}


def group_refunds_by_created_at(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("created_at", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_created_at(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_created_at(refunds).items())}


def total_refunds_by_created_at(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_created_at(refunds).items())}


def order_ids_by_refund_created_at(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_created_at(refunds).items())}


def group_refunds_by_actor(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("actor", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_actor(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_actor(refunds).items())}


def total_refunds_by_actor(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_actor(refunds).items())}


def order_ids_by_refund_actor(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_actor(refunds).items())}


def group_refunds_by_status(refunds: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get("status", "unknown")), []).append(refund)
    return grouped


def count_refunds_by_status(refunds: Iterable[dict[str, Any]]) -> dict[str, int]:
    return {key: len(rows) for key, rows in sorted(group_refunds_by_status(refunds).items())}


def total_refunds_by_status(refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {key: format_money(sum((money(refund.get("amount", "0")) for refund in rows), Decimal("0.00"))) for key, rows in sorted(group_refunds_by_status(refunds).items())}


def order_ids_by_refund_status(refunds: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    return {key: sorted({str(refund.get("order_id")) for refund in rows}) for key, rows in sorted(group_refunds_by_status(refunds).items())}
def finance_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def finance_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finance_refund_snapshot(refund) for refund in refunds]


def finance_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def support_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def support_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [support_refund_snapshot(refund) for refund in refunds]


def support_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def operations_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def operations_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [operations_refund_snapshot(refund) for refund in refunds]


def operations_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def restock_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def restock_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [restock_refund_snapshot(refund) for refund in refunds]


def restock_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def damage_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def damage_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [damage_refund_snapshot(refund) for refund in refunds]


def damage_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def fraud_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def fraud_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [fraud_refund_snapshot(refund) for refund in refunds]


def fraud_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def customer_success_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def customer_success_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [customer_success_refund_snapshot(refund) for refund in refunds]


def customer_success_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def audit_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def audit_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [audit_refund_snapshot(refund) for refund in refunds]


def audit_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def ledger_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def ledger_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ledger_refund_snapshot(refund) for refund in refunds]


def ledger_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def daily_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def daily_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [daily_refund_snapshot(refund) for refund in refunds]


def daily_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def weekly_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def weekly_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [weekly_refund_snapshot(refund) for refund in refunds]


def weekly_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def exception_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def exception_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [exception_refund_snapshot(refund) for refund in refunds]


def exception_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def manual_review_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def manual_review_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [manual_review_refund_snapshot(refund) for refund in refunds]


def manual_review_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def policy_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def policy_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [policy_refund_snapshot(refund) for refund in refunds]


def policy_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def reconciliation_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def reconciliation_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [reconciliation_refund_snapshot(refund) for refund in refunds]


def reconciliation_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def inventory_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def inventory_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [inventory_refund_snapshot(refund) for refund in refunds]


def inventory_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def margin_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def margin_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [margin_refund_snapshot(refund) for refund in refunds]


def margin_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def tax_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def tax_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tax_refund_snapshot(refund) for refund in refunds]


def tax_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def payment_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def payment_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [payment_refund_snapshot(refund) for refund in refunds]


def payment_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def compliance_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def compliance_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compliance_refund_snapshot(refund) for refund in refunds]


def compliance_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def sla_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def sla_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sla_refund_snapshot(refund) for refund in refunds]


def sla_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def reason_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def reason_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [reason_refund_snapshot(refund) for refund in refunds]


def reason_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def actor_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def actor_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [actor_refund_snapshot(refund) for refund in refunds]


def actor_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))


def order_link_refund_snapshot(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id"),
        "order_id": refund.get("order_id"),
        "amount": format_money(refund.get("amount", "0")),
        "reason": refund.get("reason"),
        "restock": bool(refund.get("restock")),
        "status": refund.get("status"),
        "actor": refund.get("actor"),
        "created_at": refund.get("created_at"),
    }


def order_link_refund_batch(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [order_link_refund_snapshot(refund) for refund in refunds]


def order_link_refund_total(refunds: Iterable[dict[str, Any]]) -> str:
    return format_money(sum((money(refund.get("amount", "0")) for refund in refunds), Decimal("0.00")))
