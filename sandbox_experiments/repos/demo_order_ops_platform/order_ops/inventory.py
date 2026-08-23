from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class InventorySnapshot:
    sku: str
    available: int
    reserved: int
    damaged: int
    reorder_point: int

    @property
    def sellable(self) -> int:
        return max(0, self.available - self.reserved - self.damaged)


def get_inventory_snapshot(inventory: dict[str, dict[str, Any]], sku: str) -> InventorySnapshot:
    row = inventory.get(sku)
    if not row:
        raise InventoryError(f"unknown sku {sku}")
    return InventorySnapshot(sku, int(row.get("available", 0)), int(row.get("reserved", 0)), int(row.get("damaged", 0)), int(row.get("reorder_point", 0)))


def format_inventory_line(snapshot: InventorySnapshot) -> str:
    return f"{snapshot.sku} | available={snapshot.available} | reserved={snapshot.reserved} | damaged={snapshot.damaged} | sellable={snapshot.sellable} | reorder_point={snapshot.reorder_point}"


def has_enough_sellable_inventory(inventory: dict[str, dict[str, Any]], sku: str, quantity: int) -> bool:
    return get_inventory_snapshot(inventory, sku).sellable >= quantity


def reserve_inventory(inventory: dict[str, dict[str, Any]], sku: str, quantity: int) -> None:
    snapshot = get_inventory_snapshot(inventory, sku)
    if quantity <= 0:
        raise InventoryError("quantity_must_be_positive")
    if snapshot.sellable < quantity:
        raise InventoryError("insufficient_inventory")
    inventory[sku]["reserved"] = int(inventory[sku].get("reserved", 0)) + quantity


def release_inventory(inventory: dict[str, dict[str, Any]], sku: str, quantity: int) -> None:
    snapshot = get_inventory_snapshot(inventory, sku)
    if snapshot.reserved < quantity:
        raise InventoryError("release_exceeds_reserved")
    inventory[sku]["reserved"] = int(inventory[sku].get("reserved", 0)) - quantity


def restock_inventory(inventory: dict[str, dict[str, Any]], sku: str, quantity: int) -> None:
    get_inventory_snapshot(inventory, sku)
    inventory[sku]["available"] = int(inventory[sku].get("available", 0)) + quantity
