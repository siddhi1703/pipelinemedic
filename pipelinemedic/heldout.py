"""Genuinely held-out faults for evaluating generalization.

These faults are deliberately disjoint from the development pilot in
``scenarios.py``: they rename different columns on different tables, use date
formats and alias names the pilot never uses, replay tables the pilot never
replays, and combine faults in new ways. The repair primitives are unchanged,
so this measures whether the fixed-rule controller and the verifier generalize
to unseen fault compositions rather than to memorized ones.

Gold answers are still computed only from the clean base (see ``evaluate.py``)
and are never passed to the controller, the agent, or the verifier.
"""
import copy
from datetime import datetime

from .data import ISO

# Alias names and date formats intentionally NOT used by scenarios.py (the pilot).
ITEM_ALIASES = {
    "price": ["unit_price", "line_price", "gross_price", "item_value"],
    "freight_value": ["ship_fee", "freight_cost", "delivery_fee", "carriage"],
}
PAYMENT_ALIASES = ["settled_value", "remittance_total", "net_paid", "cleared_amount"]
DATE_FORMATS = ["%d-%m-%Y %H:%M:%S", "%m-%d-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y.%m.%d %H:%M:%S"]


def _reformat(rows, columns, fmt):
    for row in rows:
        for c in columns:
            if row.get(c):
                row[c] = datetime.strptime(row[c], ISO).strftime(fmt)


def inject_heldout(base, kind, variant=0):
    """Return a deep-copied bundle with an unseen fault injected."""
    b = copy.deepcopy(base)

    def batch(name):
        return next(x for x in b["batches"] if x["table"] == name)

    if kind in {"rename_items", "triple_items"}:
        for canon, aliases in ITEM_ALIASES.items():
            alias = aliases[variant % 4]
            for row in batch("items")["rows"]:
                row[alias] = row.pop(canon)
            b["contracts"]["items"]["aliases"][alias] = canon

    if kind in {"date_items", "triple_items"}:
        fmt = DATE_FORMATS[variant % 4]
        _reformat(batch("items")["rows"], ["shipping_limit_date"], fmt)
        b["contracts"]["items"]["date_formats"]["shipping_limit_date"] = fmt

    if kind == "replay_orders":
        for _ in range(1 + variant % 3):
            b["batches"].append(copy.deepcopy(batch("orders")))

    if kind == "triple_items":
        for _ in range(1 + variant % 2):
            b["batches"].append(copy.deepcopy(batch("items")))

    if kind == "rename_payments_alt":
        alias = PAYMENT_ALIASES[variant % 4]
        for row in batch("payments")["rows"]:
            row[alias] = row.pop("payment_value")
        b["contracts"]["payments"]["aliases"][alias] = "payment_value"

    if kind == "ambiguous_estimated":
        # Ambiguous day/month on a different column than the pilot, with no
        # trusted source format documented -> must be escalated, not guessed.
        col = "order_estimated_delivery_date"
        for row in batch("orders")["rows"]:
            if row.get(col) and datetime.strptime(row[col], ISO).day <= 12:
                row[col] = datetime.strptime(row[col], ISO).strftime("%d/%m/%Y %H:%M:%S")
        b["contracts"]["orders"]["date_formats"][col] = None

    return b


def heldout_suite():
    """24 held-out scenarios across six unseen fault families."""
    families = ["rename_items", "date_items", "replay_orders",
                "rename_payments_alt", "triple_items", "ambiguous_estimated"]
    return [(f"{k}-{i + 1:02d}", k, i) for k in families for i in range(4)]
