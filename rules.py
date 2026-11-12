"""Defense layer 2 (design): the buy decision is made by code from the handbook, not by the model.

The four purchasing checks in handbook section 4 are fixed rules over fixed tables (approved vendors in
section 5, removed/pending vendors in section 6, max unit costs in section 9, and the 21-day / 600-unit limits).
This module reads those tables straight from data/shop_handbook.md and applies them to the facts, so nothing
written inside a vendor document can talk its way past a check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

HANDBOOK = Path(__file__).resolve().parent / "data" / "shop_handbook.md"


def norm(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s&]", " ", name.casefold()).split())


@dataclass(frozen=True)
class Handbook:
    approved: dict[str, tuple[str, str | None]]  # normalised name -> (name, orders email domain)
    removed: dict[str, tuple[str, str]]          # normalised name -> (name, status)
    max_cost: dict[str, float]                   # SKU -> max unit cost
    max_lead_days: int
    max_min_order: int


def _section(text: str, number: int) -> str:
    m = re.search(rf"^## {number}\. .*?$(.*?)(?=^## \d+\. |\Z)", text, re.M | re.S)
    if not m:
        raise ValueError(f"handbook section {number} not found")
    return m.group(1)


def _rows(section: str) -> list[list[str]]:
    rows = []
    for line in section.splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:]  # drop the header row


@lru_cache(maxsize=1)
def load() -> Handbook:
    text = HANDBOOK.read_text(encoding="utf-8")
    rules = _section(text, 4)
    approved = {}
    for row in _rows(_section(text, 5)):
        domain = re.search(r"@([\w.-]+\w)", row[-1])
        approved[norm(row[1])] = (row[1], domain.group(1).lower() if domain else None)
    removed = {norm(r[0]): (r[0], r[1]) for r in _rows(_section(text, 6))}
    max_cost = {r[0]: float(r[4].lstrip("$").replace(",", "")) for r in _rows(_section(text, 9))}
    lead = int(re.search(r"lead time is (\d+) days or less", rules).group(1))
    min_order = int(re.search(r"minimum order is (\d+) units or less", rules).group(1))
    return Handbook(approved, removed, max_cost, lead, min_order)


def decide(facts: dict[str, Any]) -> tuple[str, str, str]:
    """Apply the four checks in order. Returns (decision, one-sentence reason, check that decided it)."""
    hb = load()
    vendor, sku = facts.get("vendor"), facts.get("sku")
    price, lead, minimum = facts.get("unit_price"), facts.get("lead_time_days"), facts.get("min_order")
    no = "do_not_recommend"

    if not vendor:
        return no, "Approved-vendor check could not pass: the document does not show who the vendor is.", "vendor"
    key = norm(vendor)
    if key in hb.removed:
        name, status = hb.removed[key]
        kind = "pending, not approved" if "pending" in status.lower() else "removed"
        return no, f"Approved-vendor check failed: {name} is on the handbook's removed and pending list ({kind}).", "vendor"
    if key not in hb.approved:
        return no, f"Approved-vendor check failed: {vendor} is not on the handbook's approved vendor list.", "vendor"
    name = hb.approved[key][0]

    if price is None:
        return no, "Price check could not pass: the document does not state a unit price.", "price"
    if not sku or sku not in hb.max_cost:
        return no, f"Price check could not pass: SKU {sku or '(none)'} is not in the handbook catalogue.", "price"
    cap = hb.max_cost[sku]
    if price > cap:
        return no, f"Price check failed: the ${price:.2f} unit price is above the ${cap:.2f} max unit cost for {sku}.", "price"

    if lead is None:
        return no, "Lead-time check could not pass: the document does not state a lead time.", "lead_time"
    if lead > hb.max_lead_days:
        return no, f"Lead-time check failed: {lead} days is over the {hb.max_lead_days}-day limit.", "lead_time"

    if minimum is None:
        return no, "Minimum-order check could not pass: the document does not state a minimum order.", "min_order"
    if minimum > hb.max_min_order:
        return no, f"Minimum-order check failed: {minimum} units is over the {hb.max_min_order}-unit limit.", "min_order"

    return ("recommend",
            f"All four checks passed: {name} is approved, ${price:.2f} is at or below the ${cap:.2f} max unit cost, "
            f"{lead} days is within {hb.max_lead_days}, and {minimum} units is within {hb.max_min_order}.",
            "all")


def vendor_domain(vendor: str | None) -> str | None:
    """The orders email domain the handbook lists for an approved vendor (used to spot impersonation)."""
    if not vendor:
        return None
    entry = load().approved.get(norm(vendor))
    return entry[1] if entry else None
