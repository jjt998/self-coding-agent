from __future__ import annotations

import argparse
from pathlib import Path

from order_ops.inventory import format_inventory_line, get_inventory_snapshot
from order_ops.pricing import quote_order
from order_ops.storage import load_database

DATA_DIR = Path(__file__).parent / "data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local order operations demo CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog", help="List active products.")
    inventory_parser = subparsers.add_parser("inventory", help="Show inventory for one SKU.")
    inventory_parser.add_argument("--sku", required=True)
    quote_parser = subparsers.add_parser("quote", help="Quote an order before placement.")
    quote_parser.add_argument("--customer", required=True)
    quote_parser.add_argument("--sku", required=True)
    quote_parser.add_argument("--qty", type=int, required=True)
    quote_parser.add_argument("--coupon", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = load_database(DATA_DIR)
    if args.command == "catalog":
        for product in db.products:
            if product.get("active", True):
                print(f"{product['sku']} | {product['name']} | price={product['price']:.2f} | category={product['category']}")
        return 0
    if args.command == "inventory":
        print(format_inventory_line(get_inventory_snapshot(db.inventory, args.sku)))
        return 0
    if args.command == "quote":
        quote = quote_order(db.products, db.customers, db.coupons, sku=args.sku, customer_id=args.customer, quantity=args.qty, coupon_codes=args.coupon)
        print(quote.to_cli_line())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
