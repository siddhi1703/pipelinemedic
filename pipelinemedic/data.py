"""Load a reproducible sample without modifying the source CSVs."""
from __future__ import annotations
import csv
import hashlib
import json
import random
from pathlib import Path

FILES = {"orders": "olist_orders_dataset.csv", "items": "olist_order_items_dataset.csv", "payments": "olist_order_payments_dataset.csv"}
DATE_COLUMNS = {"orders": ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"], "items": ["shipping_limit_date"], "payments": []}
ISO = "%Y-%m-%d %H:%M:%S"
KEYS = {"orders": ["order_id"], "items": ["order_id", "order_item_id"], "payments": ["order_id", "payment_sequential"]}

def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, columns=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def prepare(source, destination, size=5000, seed=5130):
    source, destination = Path(source), Path(destination)
    tables = {t: read_csv(source / name) for t, name in FILES.items()}
    ids = sorted({r["order_id"] for r in tables["orders"]})
    if size <= 0 or size > len(ids):
        raise ValueError(f"Sample size must be between 1 and {len(ids)}")
    chosen = set(random.Random(seed).sample(ids, size))
    sample = {t: [r for r in rows if r["order_id"] in chosen] for t, rows in tables.items()}
    provenance = {"source": "Brazilian E-Commerce Public Dataset by Olist", "url": "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce", "seed": seed, "sample_orders": size, "source_rows": {t: len(rows) for t, rows in tables.items()}, "sample_rows": {t: len(rows) for t, rows in sample.items()}, "source_sha256": {t: hashlib.sha256((source / name).read_bytes()).hexdigest() for t, name in FILES.items()}}
    for t, rows in sample.items():
        write_csv(destination / FILES[t], rows)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2))
    return provenance

def load_sample(directory):
    tables = {t: read_csv(Path(directory) / name) for t, name in FILES.items()}
    contracts = {t: {"columns": list(rows[0]), "aliases": {}, "date_formats": {c: ISO for c in DATE_COLUMNS[t]}, "keys": KEYS[t]} for t, rows in tables.items()}
    return {"contracts": contracts, "batches": [{"table": t, "batch_id": f"{t}-initial", "rows": rows} for t, rows in tables.items()]}
