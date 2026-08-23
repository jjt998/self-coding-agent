from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass
class OrderOpsDatabase:
    data_dir: Path
    products: list[dict[str, Any]]
    inventory: dict[str, dict[str, Any]]
    customers: list[dict[str, Any]]
    coupons: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    refunds: list[dict[str, Any]]
    risk_rules: dict[str, Any]


def read_json(path: Path, fallback: Any) -> Any:
    return fallback if not path.exists() else json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_database(data_dir: Path) -> OrderOpsDatabase:
    return OrderOpsDatabase(data_dir, read_json(data_dir / "products.json", []), read_json(data_dir / "inventory.json", {}), read_json(data_dir / "customers.json", []), read_json(data_dir / "coupons.json", []), read_json(data_dir / "orders.json", []), read_json(data_dir / "refunds.json", []), read_json(data_dir / "risk_rules.json", {}))


def save_inventory(data_dir: Path, inventory: dict[str, dict[str, Any]]) -> None:
    write_json(data_dir / "inventory.json", inventory)


def save_orders(data_dir: Path, orders: list[dict[str, Any]]) -> None:
    write_json(data_dir / "orders.json", orders)


def save_coupons(data_dir: Path, coupons: list[dict[str, Any]]) -> None:
    write_json(data_dir / "coupons.json", coupons)


def save_refunds(data_dir: Path, refunds: list[dict[str, Any]]) -> None:
    write_json(data_dir / "refunds.json", refunds)
