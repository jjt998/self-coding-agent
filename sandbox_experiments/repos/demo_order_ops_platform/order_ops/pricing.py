from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

Money = Decimal
ZERO = Decimal("0.00")
HUNDRED = Decimal("100.00")
TAX_RATES = {"standard": Decimal("0.0825"), "grocery": Decimal("0.0100"), "digital": Decimal("0.0000")}


class PricingError(ValueError):
    pass


@dataclass(frozen=True)
class PriceLine:
    sku: str
    name: str
    category: str
    tax_category: str
    unit_price: Money
    quantity: int
    subtotal: Money
    discount_total: Money = ZERO
    tax_total: Money = ZERO
    total: Money = ZERO

    def with_totals(self, discount_total: Money, tax_total: Money) -> "PriceLine":
        taxable = max(ZERO, self.subtotal - discount_total)
        return PriceLine(self.sku, self.name, self.category, self.tax_category, self.unit_price, self.quantity, money(self.subtotal), money(discount_total), money(tax_total), money(taxable + tax_total))

    def to_record(self) -> dict[str, Any]:
        return {"sku": self.sku, "name": self.name, "category": self.category, "tax_category": self.tax_category, "unit_price": format_money(self.unit_price), "quantity": self.quantity, "subtotal": format_money(self.subtotal), "discount_total": format_money(self.discount_total), "tax_total": format_money(self.tax_total), "total": format_money(self.total)}


@dataclass(frozen=True)
class CouponDecision:
    code: str
    accepted: bool
    discount: Money = ZERO
    reason: str = ""
    exclusive: bool = False
    coupon_type: str = ""
    sequence: int = 0

    def label(self) -> str:
        return self.code if self.accepted else f"{self.code}:{self.reason or 'rejected'}"


@dataclass(frozen=True)
class DiscountAllocation:
    code: str
    sku: str
    amount: Money
    basis: Money


@dataclass
class PriceQuote:
    sku: str
    customer_id: str
    quantity: int
    subtotal: Money
    discount_total: Money
    tax_total: Money
    total: Money
    applied_coupons: list[str]
    rejected_coupons: list[str]
    lines: list[PriceLine] = field(default_factory=list)
    coupon_decisions: list[CouponDecision] = field(default_factory=list)
    allocations: list[DiscountAllocation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_cli_line(self) -> str:
        applied = ",".join(self.applied_coupons) if self.applied_coupons else "none"
        rejected = ",".join(self.rejected_coupons) if self.rejected_coupons else "none"
        return f"quote sku={self.sku} customer={self.customer_id} qty={self.quantity} subtotal={self.subtotal:.2f} discount={self.discount_total:.2f} tax={self.tax_total:.2f} total={self.total:.2f} applied={applied} rejected={rejected}"


@dataclass(frozen=True)
class CouponValidationContext:
    coupon: dict[str, Any]
    product: dict[str, Any]
    customer: dict[str, Any]
    subtotal: Money
    remaining_subtotal: Money
    already_applied: list[str]

    @property
    def code(self) -> str:
        return normalize_code(self.coupon.get("code", ""))


class CatalogIndex:
    def __init__(self, rows: Iterable[dict[str, Any]], key: str) -> None:
        self.by_key = {str(row.get(key, "")).upper(): row for row in rows if row.get(key) is not None}

    def require(self, value: str, label: str) -> dict[str, Any]:
        row = self.by_key.get(str(value).upper())
        if row is None:
            raise PricingError(f"unknown {label} {value}")
        return row

    def get(self, value: str) -> dict[str, Any] | None:
        return self.by_key.get(str(value).upper())


class QuoteEngine:
    def __init__(self, products: list[dict[str, Any]], customers: list[dict[str, Any]], coupons: list[dict[str, Any]]) -> None:
        self.product_index = CatalogIndex(products, "sku")
        self.customer_index = CatalogIndex(customers, "id")
        self.coupon_index = CatalogIndex(coupons, "code")

    def quote(self, customer_id: str, sku: str, quantity: int, coupon_codes: list[str]) -> PriceQuote:
        problems = validate_quote_request(customer_id, sku, quantity)
        if problems:
            raise PricingError(",".join(problems))
        product = self.product_index.require(sku, "sku")
        customer = self.customer_index.require(customer_id, "customer")
        line = build_price_line(product, quantity)
        decisions, discount_total = self.apply_coupon_stack(coupon_codes, product, customer, line.subtotal)
        tax_total = calculate_tax(line.subtotal - discount_total, product.get("tax_category", "standard"))
        priced_line = line.with_totals(discount_total, tax_total)
        return PriceQuote(str(product["sku"]), customer_id, quantity, priced_line.subtotal, discount_total, tax_total, priced_line.total, [d.code for d in decisions if d.accepted], [d.label() for d in decisions if not d.accepted], [priced_line], decisions, build_single_line_allocations(decisions, priced_line), quote_warnings(product, customer, priced_line, decisions))

    def apply_coupon_stack(self, coupon_codes: list[str], product: dict[str, Any], customer: dict[str, Any], subtotal: Money) -> tuple[list[CouponDecision], Money]:
        decisions: list[CouponDecision] = []
        discount_total = ZERO
        exclusive_applied = False
        for sequence, raw_code in enumerate(normalize_coupon_codes(coupon_codes), start=1):
            coupon = self.coupon_index.get(raw_code)
            if coupon is None:
                decisions.append(CouponDecision(raw_code, False, reason="not_found", sequence=sequence))
                continue
            context = CouponValidationContext(coupon, product, customer, subtotal, max(ZERO, subtotal - discount_total), [d.code for d in decisions if d.accepted])
            allowed, reason = validate_coupon_for_stack(context, exclusive_applied)
            if not allowed:
                decisions.append(CouponDecision(context.code, False, reason=reason, exclusive=bool(coupon.get("exclusive")), coupon_type=str(coupon.get("discount_type", "")), sequence=sequence))
                continue
            discount = calculate_coupon_discount(coupon, context.remaining_subtotal)
            if discount <= ZERO:
                decisions.append(CouponDecision(context.code, False, reason="no_discount", sequence=sequence))
                continue
            decisions.append(CouponDecision(context.code, True, discount=discount, exclusive=bool(coupon.get("exclusive")), coupon_type=str(coupon.get("discount_type", "")), sequence=sequence))
            discount_total = money(discount_total + discount)
            exclusive_applied = exclusive_applied or bool(coupon.get("exclusive"))
        return decisions, discount_total


def money(value: Any) -> Money:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_money(value: Any) -> str:
    return f"{money(value):.2f}"


def normalize_code(value: Any) -> str:
    return str(value).strip().upper()


def normalize_coupon_codes(coupon_codes: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for code in coupon_codes:
        normalized = normalize_code(code)
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def validate_quote_request(customer_id: str, sku: str, quantity: int) -> list[str]:
    problems: list[str] = []
    if not customer_id.strip():
        problems.append("customer_required")
    if not sku.strip():
        problems.append("sku_required")
    if quantity <= 0:
        problems.append("quantity_must_be_positive")
    return problems


def build_price_line(product: dict[str, Any], quantity: int) -> PriceLine:
    if not product.get("active", True):
        raise PricingError(f"inactive sku {product.get('sku')}")
    unit_price = money(product.get("price", "0"))
    subtotal = money(unit_price * quantity)
    return PriceLine(str(product.get("sku", "")), str(product.get("name", "")), str(product.get("category", "")), str(product.get("tax_category", "standard")), unit_price, quantity, subtotal, total=subtotal)


def validate_coupon_for_stack(context: CouponValidationContext, exclusive_already_applied: bool) -> tuple[bool, str]:
    coupon = context.coupon
    if not coupon.get("active", False):
        return False, "inactive"
    if exclusive_already_applied or (coupon.get("exclusive") and context.already_applied):
        return False, "exclusive_conflict"
    if coupon.get("segment") and coupon.get("segment") != context.customer.get("segment"):
        return False, "segment_mismatch"
    if context.subtotal < money(coupon.get("min_subtotal", "0")):
        return False, "below_min_subtotal"
    categories = coupon.get("categories") or []
    if categories and context.product.get("category") not in categories:
        return False, "category_mismatch"
    if int(coupon.get("used_count", 0)) >= int(coupon.get("max_uses", 999999)):
        return False, "usage_limit"
    return True, ""


def calculate_coupon_discount(coupon: dict[str, Any], remaining_subtotal: Money) -> Money:
    remaining = money(max(ZERO, remaining_subtotal))
    if coupon.get("discount_type") == "percent":
        raw = remaining * Decimal(str(coupon.get("discount_value", "0"))) / HUNDRED
    elif coupon.get("discount_type") == "amount":
        raw = money(coupon.get("discount_value", "0"))
    else:
        raw = ZERO
    if coupon.get("max_discount") is not None:
        raw = min(raw, money(coupon["max_discount"]))
    return money(min(remaining, raw))


def calculate_tax(taxable_amount: Any, tax_category: str) -> Money:
    return money(max(ZERO, money(taxable_amount)) * TAX_RATES.get(str(tax_category), TAX_RATES["standard"]))


def build_single_line_allocations(decisions: list[CouponDecision], line: PriceLine) -> list[DiscountAllocation]:
    return [DiscountAllocation(d.code, line.sku, d.discount, line.subtotal) for d in decisions if d.accepted and d.discount > ZERO]


def apply_coupon_stack(coupons: list[dict[str, Any]], coupon_codes: list[str], product: dict[str, Any], customer: dict[str, Any], subtotal: Money) -> tuple[list[str], list[str], Money]:
    decisions, total = QuoteEngine([product], [customer], coupons).apply_coupon_stack(coupon_codes, product, customer, subtotal)
    return [d.code for d in decisions if d.accepted], [d.label() for d in decisions if not d.accepted], total


def quote_order(products: list[dict[str, Any]], customers: list[dict[str, Any]], coupons: list[dict[str, Any]], *, sku: str, customer_id: str, quantity: int, coupon_codes: list[str]) -> PriceQuote:
    return QuoteEngine(products, customers, coupons).quote(customer_id, sku, quantity, coupon_codes)


def update_coupon_usage(coupons: list[dict[str, Any]], applied_codes: Iterable[str]) -> None:
    applied = {normalize_code(code) for code in applied_codes}
    for coupon in coupons:
        if normalize_code(coupon.get("code", "")) in applied:
            coupon["used_count"] = int(coupon.get("used_count", 0)) + 1


def quote_to_order_totals(quote: PriceQuote) -> dict[str, str]:
    return {"subtotal": format_money(quote.subtotal), "discount_total": format_money(quote.discount_total), "tax_total": format_money(quote.tax_total), "total": format_money(quote.total)}


def quote_warnings(product: dict[str, Any], customer: dict[str, Any], line: PriceLine, decisions: list[CouponDecision]) -> list[str]:
    warnings: list[str] = []
    if line.discount_total > line.subtotal * Decimal("0.50"):
        warnings.append("discount_above_half_subtotal")
    if customer.get("risk_tier") == "high":
        warnings.append("risk_review_recommended")
    return warnings


def quotes_to_csv(quotes: Iterable[PriceQuote]) -> str:
    rows = ["sku,customer_id,quantity,subtotal,discount,tax,total,applied,rejected"]
    for quote in quotes:
        rows.append(",".join([quote.sku, quote.customer_id, str(quote.quantity), format_money(quote.subtotal), format_money(quote.discount_total), format_money(quote.tax_total), format_money(quote.total), "|".join(quote.applied_coupons), "|".join(quote.rejected_coupons)]))
    return "\n".join(rows)


def filter_discounted_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.discount_total > ZERO]


def summarize_discounted_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_discounted_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_discounted_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_discounted_quotes(quotes))


def filter_undiscounted_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.discount_total == ZERO]


def summarize_undiscounted_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_undiscounted_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_undiscounted_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_undiscounted_quotes(quotes))


def filter_taxable_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.tax_total > ZERO]


def summarize_taxable_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_taxable_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_taxable_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_taxable_quotes(quotes))


def filter_tax_exempt_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.tax_total == ZERO]


def summarize_tax_exempt_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_tax_exempt_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_tax_exempt_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_tax_exempt_quotes(quotes))


def filter_high_value_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.total >= Decimal('100.00')]


def summarize_high_value_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_high_value_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_high_value_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_high_value_quotes(quotes))


def filter_low_value_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.total < Decimal('50.00')]


def summarize_low_value_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_low_value_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_low_value_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_low_value_quotes(quotes))


def filter_multi_unit_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.quantity > 1]


def summarize_multi_unit_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_multi_unit_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_multi_unit_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_multi_unit_quotes(quotes))


def filter_single_unit_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.quantity == 1]


def summarize_single_unit_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_single_unit_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_single_unit_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_single_unit_quotes(quotes))


def filter_has_rejections_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if bool(quote.rejected_coupons)]


def summarize_has_rejections_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_has_rejections_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_has_rejections_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_has_rejections_quotes(quotes))


def filter_clean_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if not quote.rejected_coupons]


def summarize_clean_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_clean_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_clean_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_clean_quotes(quotes))


def filter_has_coupon_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if bool(quote.applied_coupons)]


def summarize_has_coupon_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_has_coupon_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_has_coupon_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_has_coupon_quotes(quotes))


def filter_no_coupon_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if not quote.applied_coupons]


def summarize_no_coupon_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_no_coupon_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_no_coupon_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_no_coupon_quotes(quotes))


def filter_deep_discount_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.discount_total >= Decimal('20.00')]


def summarize_deep_discount_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_deep_discount_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_deep_discount_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_deep_discount_quotes(quotes))


def filter_small_discount_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if ZERO < quote.discount_total < Decimal('20.00')]


def summarize_small_discount_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_small_discount_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_small_discount_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_small_discount_quotes(quotes))


def filter_large_tax_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.tax_total >= Decimal('5.00')]


def summarize_large_tax_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_large_tax_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_large_tax_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_large_tax_quotes(quotes))


def filter_small_tax_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if ZERO < quote.tax_total < Decimal('5.00')]


def summarize_small_tax_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_small_tax_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_small_tax_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_small_tax_quotes(quotes))


def filter_free_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.total == ZERO]


def summarize_free_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_free_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_free_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_free_quotes(quotes))


def filter_payable_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.total > ZERO]


def summarize_payable_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_payable_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_payable_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_payable_quotes(quotes))


def filter_office_sku_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.sku.endswith('BLUE')]


def summarize_office_sku_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_office_sku_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_office_sku_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_office_sku_quotes(quotes))


def filter_home_sku_quotes(quotes: Iterable[PriceQuote]) -> list[PriceQuote]:
    return [quote for quote in quotes if quote.sku.endswith('RED')]


def summarize_home_sku_quotes(quotes: Iterable[PriceQuote]) -> dict[str, str]:
    rows = filter_home_sku_quotes(quotes)
    return {
        "count": str(len(rows)),
        "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
        "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
        "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
        "total": format_money(sum((quote.total for quote in rows), ZERO)),
    }


def csv_home_sku_quotes(quotes: Iterable[PriceQuote]) -> str:
    return quotes_to_csv(filter_home_sku_quotes(quotes))


def summarize_quote_metrics_by_customer_id(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "customer_id")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result


def summarize_quote_metrics_by_sku(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "sku")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result


def summarize_quote_metrics_by_quantity(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "quantity")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result


def summarize_quote_metrics_by_discount_total(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "discount_total")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result


def summarize_quote_metrics_by_tax_total(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "tax_total")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result


def summarize_quote_metrics_by_total(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "total")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result


def summarize_quote_metrics_by_subtotal(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "subtotal")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result


def summarize_quote_metrics_by_applied_coupons(quotes: Iterable[PriceQuote]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[PriceQuote]] = {}
    for quote in quotes:
        value = getattr(quote, "applied_coupons")
        key = "|".join(value) if isinstance(value, list) else str(value)
        grouped.setdefault(key or "none", []).append(quote)
    result: dict[str, dict[str, str]] = {}
    for key, rows in sorted(grouped.items()):
        result[key] = {
            "count": str(len(rows)),
            "subtotal": format_money(sum((quote.subtotal for quote in rows), ZERO)),
            "discount": format_money(sum((quote.discount_total for quote in rows), ZERO)),
            "tax": format_money(sum((quote.tax_total for quote in rows), ZERO)),
            "total": format_money(sum((quote.total for quote in rows), ZERO)),
        }
    return result
