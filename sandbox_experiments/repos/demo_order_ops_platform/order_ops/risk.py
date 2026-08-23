from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RiskDecision:
    hold: bool
    score: int
    reasons: list[str]


def customer_by_id(customers: list[dict[str, Any]], customer_id: str) -> dict[str, Any] | None:
    return next((customer for customer in customers if customer.get("id") == customer_id), None)


def evaluate_basic_risk(customers: list[dict[str, Any]], customer_id: str) -> list[str]:
    return evaluate_customer_risk(customers, customer_id).reasons


def evaluate_customer_risk(customers: list[dict[str, Any]], customer_id: str) -> RiskDecision:
    customer = customer_by_id(customers, customer_id)
    if customer is None:
        return RiskDecision(True, 100, ["unknown_customer"])
    reasons: list[str] = []
    score = 0
    if customer.get("risk_tier") == "high":
        reasons.append("high_risk_customer")
        score += 80
    if int(customer.get("chargeback_count", 0)) >= 2:
        reasons.append("chargeback_history")
        score += 40
    return RiskDecision(score >= 60, score, reasons)


def evaluate_order_risk(customers: list[dict[str, Any]], risk_rules: dict[str, Any], *, customer_id: str, sku: str, order_total: Any, orders: list[dict[str, Any]] | None = None, refunds: list[dict[str, Any]] | None = None) -> RiskDecision:
    base = evaluate_customer_risk(customers, customer_id)
    reasons = list(base.reasons)
    score = base.score
    if Decimal(str(order_total)) > Decimal(str(risk_rules.get("max_order_total_without_review", "999999"))):
        reasons.append("amount_above_review_threshold")
        score += 35
    if sku in risk_rules.get("blocked_skus", []):
        reasons.append("blocked_sku")
        score += 100
    return RiskDecision(score >= 60, score, reasons)
