from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable


@dataclass(frozen=True)
class MetricRow:
    key: str
    count: int
    gross: Decimal
    discounts: Decimal
    refunds: Decimal
    net: Decimal

    def to_record(self) -> dict[str, Any]:
        return {"key": self.key, "count": self.count, "gross": format_money(self.gross), "discounts": format_money(self.discounts), "refunds": format_money(self.refunds), "net": format_money(self.net)}


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_money(value: Any) -> str:
    return f"{money(value):.2f}"


def order_total(order: dict[str, Any]) -> Decimal:
    return money(order.get("total", "0"))


def order_discount(order: dict[str, Any]) -> Decimal:
    return money(order.get("discount_total", "0"))


def refund_amount(refund: dict[str, Any]) -> Decimal:
    return money(refund.get("amount", "0"))


def orders_on_date(orders: Iterable[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    return [order for order in orders if str(order.get("created_at", "")).startswith(date)]


def refunds_on_date(refunds: Iterable[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    return [refund for refund in refunds if str(refund.get("created_at", "")).startswith(date)]


def daily_summary(orders: list[dict[str, Any]], refunds: list[dict[str, Any]], date: str) -> dict[str, Any]:
    day_orders = orders_on_date(orders, date)
    day_refunds = refunds_on_date(refunds, date)
    gross = sum((order_total(order) for order in day_orders), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in day_refunds), Decimal("0.00"))
    return {"date": date, "order_count": len(day_orders), "gross_sales": format_money(gross), "refund_total": format_money(refund_total), "net_sales": format_money(gross - refund_total)}


def format_daily_summary(summary: dict[str, Any]) -> str:
    return f"date={summary['date']} orders={summary['order_count']} gross={summary['gross_sales']} refunds={summary['refund_total']} net={summary['net_sales']}"


def group_orders_by(orders: Iterable[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        grouped.setdefault(str(order.get(field, "unknown")), []).append(order)
    return grouped


def group_refunds_by(refunds: Iterable[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        grouped.setdefault(str(refund.get(field, "unknown")), []).append(refund)
    return grouped


def refund_totals_by_order(refunds: Iterable[dict[str, Any]]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for refund in refunds:
        order_id = str(refund.get("order_id", "unknown"))
        totals[order_id] = totals.get(order_id, Decimal("0.00")) + refund_amount(refund)
    return totals


def build_metric_rows(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], group_field: str) -> list[MetricRow]:
    refund_totals = refund_totals_by_order(refunds)
    rows: list[MetricRow] = []
    for key, grouped_orders in sorted(group_orders_by(orders, group_field).items()):
        gross = sum((order_total(order) for order in grouped_orders), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in grouped_orders), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in grouped_orders), Decimal("0.00"))
        rows.append(MetricRow(key, len(grouped_orders), money(gross), money(discounts), money(refund_total), money(gross - refund_total)))
    return rows


def coupon_usage_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = {}
    for order in orders:
        for code in order.get("applied_coupons", []):
            row = usage.setdefault(str(code), {"code": str(code), "orders": 0, "discount_total": Decimal("0.00")})
            row["orders"] += 1
            row["discount_total"] += order_discount(order)
    return [{"code": row["code"], "orders": row["orders"], "discount_total": format_money(row["discount_total"])} for row in sorted(usage.values(), key=lambda item: item["code"])]


def inventory_risk_report(inventory: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sku, row in sorted(inventory.items()):
        available = int(row.get("available", 0) or 0)
        reserved = int(row.get("reserved", 0) or 0)
        damaged = int(row.get("damaged", 0) or 0)
        reorder_point = int(row.get("reorder_point", 0) or 0)
        sellable = max(0, available - reserved - damaged)
        status = "stockout" if sellable <= 0 else "reorder" if sellable <= reorder_point else "healthy"
        rows.append({"sku": sku, "available": available, "reserved": reserved, "damaged": damaged, "sellable": sellable, "reorder_point": reorder_point, "status": status})
    return rows


def report_to_csv(rows: Iterable[dict[str, Any]]) -> str:
    rows = list(rows)
    if not rows:
        return ""
    headers = list(rows[0].keys())
    return "\n".join([",".join(headers), *[",".join(str(row.get(header, "")) for header in headers) for row in rows]])


def customer_id_gross_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "customer_id")
    return [{"customer_id": key, "count": len(rows), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def customer_id_discount_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "customer_id")
    return [{"customer_id": key, "count": len(rows), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def customer_id_quantity_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "customer_id")
    return [{"customer_id": key, "quantity": sum((int(order.get("quantity", 0) or 0) for order in rows))} for key, rows in sorted(grouped.items())]


def customer_id_net_report(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row.to_record() for row in build_metric_rows(orders, refunds, "customer_id")]


def sku_gross_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "sku")
    return [{"sku": key, "count": len(rows), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def sku_discount_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "sku")
    return [{"sku": key, "count": len(rows), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def sku_quantity_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "sku")
    return [{"sku": key, "quantity": sum((int(order.get("quantity", 0) or 0) for order in rows))} for key, rows in sorted(grouped.items())]


def sku_net_report(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row.to_record() for row in build_metric_rows(orders, refunds, "sku")]


def status_gross_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "status")
    return [{"status": key, "count": len(rows), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def status_discount_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "status")
    return [{"status": key, "count": len(rows), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def status_quantity_report(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "status")
    return [{"status": key, "quantity": sum((int(order.get("quantity", 0) or 0) for order in rows))} for key, rows in sorted(grouped.items())]


def status_net_report(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row.to_record() for row in build_metric_rows(orders, refunds, "status")]


def paid_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order.get('status') in {'paid', 'partially_refunded', 'refunded', 'shipped', 'delivered'}]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def paid_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order.get('status') in {'paid', 'partially_refunded', 'refunded', 'shipped', 'delivered'}]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def open_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order.get('status') not in {'cancelled', 'refunded', 'rejected'}]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def open_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order.get('status') not in {'cancelled', 'refunded', 'rejected'}]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def held_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order.get('status') == 'held_for_review']
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def held_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order.get('status') == 'held_for_review']
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def reserved_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order.get('status') == 'inventory_reserved']
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def reserved_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order.get('status') == 'inventory_reserved']
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def discounted_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order_discount(order) > Decimal('0.00')]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def discounted_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order_discount(order) > Decimal('0.00')]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def high_value_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order_total(order) >= Decimal('100.00')]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def high_value_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order_total(order) >= Decimal('100.00')]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def low_value_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order_total(order) < Decimal('50.00')]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def low_value_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order_total(order) < Decimal('50.00')]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def multi_unit_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if int(order.get('quantity', 0) or 0) > 1]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def multi_unit_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if int(order.get('quantity', 0) or 0) > 1]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def single_unit_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if int(order.get('quantity', 0) or 0) == 1]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def single_unit_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if int(order.get('quantity', 0) or 0) == 1]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def coupon_used_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if bool(order.get('applied_coupons'))]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def coupon_used_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if bool(order.get('applied_coupons'))]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def risk_flagged_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if bool(order.get('risk_reasons'))]
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def risk_flagged_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if bool(order.get('risk_reasons'))]
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def cancelled_order_report(orders: Iterable[dict[str, Any]]) -> dict[str, str]:
    rows = [order for order in orders if order.get('status') == 'cancelled']
    return {"count": str(len(rows)), "gross": format_money(sum((order_total(order) for order in rows), Decimal("0.00"))), "discounts": format_money(sum((order_discount(order) for order in rows), Decimal("0.00"))), "quantity": str(sum((int(order.get("quantity", 0) or 0) for order in rows)))}


def cancelled_order_lines(orders: Iterable[dict[str, Any]]) -> list[str]:
    rows = [order for order in orders if order.get('status') == 'cancelled']
    return [f"order_id={order.get('id')} status={order.get('status')} sku={order.get('sku')} total={format_money(order_total(order))}" for order in rows]


def refund_reason_report(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_refunds_by(refunds, "reason")
    return [{"reason": key, "count": len(rows), "total": format_money(sum((refund_amount(refund) for refund in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def refund_status_report(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_refunds_by(refunds, "status")
    return [{"status": key, "count": len(rows), "total": format_money(sum((refund_amount(refund) for refund in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def refund_order_id_report(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_refunds_by(refunds, "order_id")
    return [{"order_id": key, "count": len(rows), "total": format_money(sum((refund_amount(refund) for refund in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def refund_actor_report(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_refunds_by(refunds, "actor")
    return [{"actor": key, "count": len(rows), "total": format_money(sum((refund_amount(refund) for refund in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]


def refund_restock_report(refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_refunds_by(refunds, "restock")
    return [{"restock": key, "count": len(rows), "total": format_money(sum((refund_amount(refund) for refund in rows), Decimal("0.00")))} for key, rows in sorted(grouped.items())]
def report_orders_by_customer_id(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "customer_id")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "customer_id", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_customer_id(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_customer_id(orders, refunds))


def top_orders_by_customer_id(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_customer_id(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_sku(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "sku")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "sku", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_sku(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_sku(orders, refunds))


def top_orders_by_sku(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_sku(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_status(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "status")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "status", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_status(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_status(orders, refunds))


def top_orders_by_status(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_status(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_quantity(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "quantity")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "quantity", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_quantity(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_quantity(orders, refunds))


def top_orders_by_quantity(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_quantity(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_subtotal(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "subtotal")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "subtotal", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_subtotal(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_subtotal(orders, refunds))


def top_orders_by_subtotal(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_subtotal(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_discount_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "discount_total")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "discount_total", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_discount_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_discount_total(orders, refunds))


def top_orders_by_discount_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_discount_total(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_tax_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "tax_total")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "tax_total", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_tax_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_tax_total(orders, refunds))


def top_orders_by_tax_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_tax_total(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "total")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "total", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_total(orders, refunds))


def top_orders_by_total(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_total(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_created_at(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "created_at")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "created_at", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_created_at(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_created_at(orders, refunds))


def top_orders_by_created_at(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_created_at(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_applied_coupons(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "applied_coupons")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "applied_coupons", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_applied_coupons(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_applied_coupons(orders, refunds))


def top_orders_by_applied_coupons(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_applied_coupons(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]


def report_orders_by_risk_reasons(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_orders_by(orders, "risk_reasons")
    refund_totals = refund_totals_by_order(refunds)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        gross = sum((order_total(order) for order in values), Decimal("0.00"))
        discounts = sum((order_discount(order) for order in values), Decimal("0.00"))
        refund_total = sum((refund_totals.get(str(order.get("id")), Decimal("0.00")) for order in values), Decimal("0.00"))
        rows.append({"dimension": "risk_reasons", "key": key, "count": len(values), "gross": format_money(gross), "discounts": format_money(discounts), "refunds": format_money(refund_total), "net": format_money(gross - refund_total)})
    return rows


def csv_orders_by_risk_reasons(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    return report_to_csv(report_orders_by_risk_reasons(orders, refunds))


def top_orders_by_risk_reasons(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = report_orders_by_risk_reasons(orders, refunds)
    return sorted(rows, key=lambda row: Decimal(str(row["gross"])), reverse=True)[:limit]
def finance_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "finance",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def finance_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = finance_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def operations_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "operations",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def operations_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = operations_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def support_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "support",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def support_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = support_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def risk_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "risk",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def risk_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = risk_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def coupon_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "coupon",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def coupon_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = coupon_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def tax_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "tax",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def tax_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = tax_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def payment_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "payment",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def payment_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = payment_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def refund_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "refund",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def refund_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = refund_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def inventory_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "inventory",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def inventory_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = inventory_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def fulfillment_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "fulfillment",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def fulfillment_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = fulfillment_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def customer_success_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "customer_success",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def customer_success_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = customer_success_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def audit_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "audit",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def audit_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = audit_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def exception_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "exception",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def exception_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = exception_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def daily_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "daily",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def daily_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = daily_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def weekly_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "weekly",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def weekly_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = weekly_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def margin_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "margin",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def margin_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = margin_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def compliance_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "compliance",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def compliance_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = compliance_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def reconciliation_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "reconciliation",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def reconciliation_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = reconciliation_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def pipeline_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "pipeline",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def pipeline_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = pipeline_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"


def executive_dashboard_section(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> dict[str, str]:
    orders_list = list(orders)
    refunds_list = list(refunds)
    gross = sum((order_total(order) for order in orders_list), Decimal("0.00"))
    discounts = sum((order_discount(order) for order in orders_list), Decimal("0.00"))
    refund_total = sum((refund_amount(refund) for refund in refunds_list), Decimal("0.00"))
    return {
        "section": "executive",
        "order_count": str(len(orders_list)),
        "refund_count": str(len(refunds_list)),
        "gross": format_money(gross),
        "discounts": format_money(discounts),
        "refunds": format_money(refund_total),
        "net": format_money(gross - refund_total),
    }


def executive_dashboard_line(orders: Iterable[dict[str, Any]], refunds: Iterable[dict[str, Any]]) -> str:
    section = executive_dashboard_section(orders, refunds)
    return f"section={section['section']} orders={section['order_count']} refunds={section['refund_count']} gross={section['gross']} net={section['net']}"
