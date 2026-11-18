"""Execution never reads evaluation answers. Verification uses only source evidence."""
from __future__ import annotations
import copy
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import duckdb
from .data import DATE_COLUMNS, ISO, KEYS, fingerprint, write_csv

class PipelineError(ValueError):
    pass

def _strict_date(value, fmt):
    if not value:
        return ""
    parsed = datetime.strptime(value, fmt)
    # strptime accepts some non-padded input. ISO canonicalization is intentional.
    return parsed.strftime(ISO)

def fixed_plan(bundle):
    """A strong deterministic baseline with the same documented evidence as the AI."""
    ops = []
    for t, contract in bundle["contracts"].items():
        present = {c for b in bundle["batches"] if b["table"] == t for r in b["rows"][:1] for c in r}
        for source, target in contract["aliases"].items():
            if source in present and target not in present:
                ops.append({"op": "rename_column", "table": t, "source": source, "target": target})
        for col, fmt in contract["date_formats"].items():
            if fmt is None:
                return {"operations": [], "human_review": True, "reason": f"No trusted format for {col}"}
            if fmt != ISO:
                ops.append({"op": "parse_date", "table": t, "column": col, "format": fmt})
    seen = {}
    for b in bundle["batches"]:
        key = (b["table"], b["batch_id"])
        digest = fingerprint(b["rows"])
        if key in seen:
            if seen[key] != digest:
                return {"operations": [], "human_review": True, "reason": "Same batch ID has conflicting payloads"}
            ops.append({"op": "skip_replayed_batches"})
        seen[key] = digest
    if sum(op["op"] == "skip_replayed_batches" for op in ops) > 1:
        ops = [op for op in ops if op["op"] != "skip_replayed_batches"] + [{"op": "skip_replayed_batches"}]
    return {"operations": ops, "human_review": False, "reason": "Follow documented aliases, formats, and batch identities"}

def validate_plan(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("operations"), list) or type(plan.get("human_review")) is not bool:
        raise PipelineError("Invalid repair plan schema")
    if len(plan["operations"]) > 20:
        raise PipelineError("Operation budget exceeded")
    for op in plan["operations"]:
        if op.get("op") not in {"rename_column", "parse_date", "skip_replayed_batches"}:
            raise PipelineError("Operation is not approved")
        if op["op"] != "skip_replayed_batches" and op.get("table") not in KEYS:
            raise PipelineError("Unknown table")
        if op["op"] == "parse_date" and op.get("column") not in DATE_COLUMNS[op["table"]]:
            raise PipelineError("Only declared date fields may be parsed")
    return plan

def execute(bundle, plan, db_path=None):
    """Apply bounded operations to a deep copy, then construct reports in DuckDB."""
    started = perf_counter()
    validate_plan(plan)
    if plan["human_review"]:
        return {"status": "human_review", "reason": plan.get("reason", "Evidence needed"), "seconds": perf_counter()-started}
    working = copy.deepcopy(bundle)
    for op in plan["operations"]:
        if op["op"] == "skip_replayed_batches":
            continue
        for b in working["batches"]:
            if b["table"] != op["table"]:
                continue
            for row in b["rows"]:
                if op["op"] == "rename_column":
                    src, dst = op.get("source"), op.get("target")
                    if src not in row or dst in row:
                        raise PipelineError("Column mapping missing or collides with an existing field")
                    row[dst] = row.pop(src)
                else:
                    col = op["column"]
                    if col not in row:
                        raise PipelineError("Date column missing")
                    row[col] = _strict_date(row[col], op["format"])
    tables = {t: [] for t in KEYS}
    skip = any(op["op"] == "skip_replayed_batches" for op in plan["operations"])
    seen, ledger = {}, []
    for b in working["batches"]:
        key = (b["table"], b["batch_id"])
        digest = fingerprint(b["rows"])
        if skip and key in seen:
            if seen[key] != digest:
                raise PipelineError("Batch ID reused with different contents; human review required")
            ledger.append({"table": key[0], "batch_id": key[1], "decision": "skipped_exact_replay", "sha256": digest})
            continue
        seen[key] = digest
        tables[b["table"]].extend(b["rows"])
        ledger.append({"table": key[0], "batch_id": key[1], "decision": "ingested", "sha256": digest})
    for t, rows in tables.items():
        expected = set(bundle["contracts"][t]["columns"])
        for row in rows:
            if not expected.issubset(row):
                raise PipelineError(f"Missing required {t} columns: {sorted(expected-set(row))}")
            for c in DATE_COLUMNS[t]:
                if row[c]:
                    _strict_date(row[c], ISO)
            numeric = ["price", "freight_value"] if t == "items" else ["payment_value"] if t == "payments" else []
            for c in numeric:
                try:
                    if not Decimal(row[c]).is_finite() or Decimal(row[c]) < 0:
                        raise PipelineError(f"Invalid {t}.{c}")
                except InvalidOperation as e:
                    raise PipelineError(f"Invalid number in {t}.{c}") from e
    metrics = make_reports(tables, db_path)
    return {"status": "candidate", "tables": tables, "metrics": metrics, "ledger": ledger, "seconds": perf_counter()-started}

def make_reports(tables, db_path=None):
    with TemporaryDirectory(prefix="pipelinemedic_") as tmp:
        con = duckdb.connect(str(db_path) if db_path else ":memory:")
        try:
            for t in KEYS:
                path = Path(tmp) / f"{t}.csv"
                write_csv(path, tables[t])
                con.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM read_csv(?, all_varchar=true)", [str(path)])
            con.execute("""CREATE OR REPLACE TABLE order_report AS
                WITH i AS (SELECT order_id, sum(CAST(price AS DECIMAL(18,2))) AS item_total FROM items GROUP BY order_id),
                p AS (SELECT order_id, sum(CAST(payment_value AS DECIMAL(18,2))) AS payment_total FROM payments GROUP BY order_id)
                SELECT o.*, coalesce(i.item_total,0) AS item_total, coalesce(p.payment_total,0) AS payment_total
                FROM orders o LEFT JOIN i USING(order_id) LEFT JOIN p USING(order_id)""")
            count, total = con.execute("SELECT count(*), sum(payment_total) FROM order_report").fetchone()
            eligible, late = con.execute("""SELECT count(*), count(*) FILTER (WHERE CAST(order_delivered_customer_date AS TIMESTAMP) > CAST(order_estimated_delivery_date AS TIMESTAMP))
                FROM orders WHERE order_status='delivered' AND order_delivered_customer_date <> '' AND order_estimated_delivery_date <> ''""").fetchone()
            return {"order_count": count, "payment_total": str(total or Decimal("0.00")), "eligible_delivered_orders": eligible, "late_delivered_orders": late, "late_delivery_rate": late/eligible if eligible else None}
        finally:
            con.close()

def _evidence_rows(bundle):
    """Independent source projection. No agent plan or hidden gold is an input.

    Date values are checked against the declared source format; replay exclusion
    is justified by both batch identity and exact payload fingerprint.
    """
    expected = {t: [] for t in KEYS}
    seen = {}
    for b in bundle["batches"]:
        t = b["table"]
        contract = bundle["contracts"][t]
        key = (t, b["batch_id"])
        digest = fingerprint(b["rows"])
        if key in seen:
            if seen[key] != digest:
                return None, "Conflicting payloads share a batch ID"
            continue
        seen[key] = digest
        for raw in b["rows"]:
            projected = {}
            for col in contract["columns"]:
                sources = ([col] if col in raw else []) + [a for a, target in contract["aliases"].items() if target == col and a in raw]
                if len(sources) != 1:
                    return None, f"Missing or conflicting source mapping for {t}.{col}"
                value = raw[sources[0]]
                if col in DATE_COLUMNS[t] and value:
                    fmt = contract["date_formats"].get(col)
                    if fmt is None:
                        return None, f"No trusted date interpretation for {t}.{col}"
                    try:
                        value = datetime.strptime(value, fmt).strftime(ISO)
                    except ValueError:
                        return None, f"Date violates the source contract: {t}.{col}"
                projected[col] = value
            expected[t].append(projected)
    return expected, None

def _bag(rows, columns):
    return Counter(tuple(r.get(c, "<MISSING>") for c in columns) for r in rows)

def verify(bundle, outcome, mode="full"):
    """Full checks or deliberately weak schema-only checks for an ablation."""
    if outcome.get("status") != "candidate":
        return {"decision": "human_review", "failures": [outcome.get("reason", "No candidate")]}
    tables = outcome["tables"]
    failures = []
    for t, contract in bundle["contracts"].items():
        if any(not set(contract["columns"]).issubset(r) for r in tables[t]):
            failures.append(f"{t}: schema mismatch")
    if mode == "schema_only":
        return {"decision": "reject" if failures else "accept", "failures": failures}
    if mode != "full":
        raise ValueError("Unknown verification mode")
    expected, uncertain = _evidence_rows(bundle)
    if uncertain:
        return {"decision": "human_review", "failures": [uncertain]}
    order_ids = {r["order_id"] for r in tables["orders"]}
    for t, contract in bundle["contracts"].items():
        keys = [tuple(r.get(c) for c in KEYS[t]) for r in tables[t]]
        if len(keys) != len(set(keys)):
            failures.append(f"{t}: duplicate natural keys")
        if t != "orders" and any(r.get("order_id") not in order_ids for r in tables[t]):
            failures.append(f"{t}: orphan order reference")
        if _bag(tables[t], contract["columns"]) != _bag(expected[t], contract["columns"]):
            failures.append(f"{t}: source record coverage or values changed")
    # Independently recompute aggregate invariants without DuckDB or agent outputs.
    expected_total = sum((Decimal(r["payment_value"]) for r in expected["payments"]), Decimal(0))
    if Decimal(outcome["metrics"]["payment_total"]) != expected_total:
        failures.append("payment total does not match source evidence")
    eligible = [r for r in expected["orders"] if r["order_status"] == "delivered" and r["order_delivered_customer_date"] and r["order_estimated_delivery_date"]]
    late = sum(r["order_delivered_customer_date"] > r["order_estimated_delivery_date"] for r in eligible)
    if outcome["metrics"]["order_count"] != len(expected["orders"]) or outcome["metrics"]["eligible_delivered_orders"] != len(eligible) or outcome["metrics"]["late_delivered_orders"] != late:
        failures.append("report counts violate source evidence")
    return {"decision": "reject" if failures else "accept", "failures": failures, "checks": ["schema", "natural_keys", "foreign_keys", "source_coverage_and_values", "replay_exclusion", "report_invariants"]}

def attempt(bundle, plan, checker=True, mode="full", db_path=None):
    start = perf_counter()
    try:
        result = execute(bundle, plan)
        verdict = verify(bundle, result, mode) if checker else {"decision": "human_review" if result["status"] == "human_review" else "accept", "failures": []}
        if db_path and verdict["decision"] == "accept":
            # Only a verified candidate can be promoted through the checked path.
            make_reports(result["tables"], db_path)
        return {"outcome": result, "verdict": verdict, "seconds": perf_counter()-start}
    except (ValueError, KeyError, TypeError, duckdb.Error) as e:
        return {"outcome": {"status": "error", "reason": str(e)}, "verdict": {"decision": "reject", "failures": [str(e)]}, "seconds": perf_counter()-start}
