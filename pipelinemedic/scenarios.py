"""Controlled fault injection. These pilot scenarios are not a held-out benchmark."""
import copy
from datetime import datetime
from .data import DATE_COLUMNS, ISO

def inject(base, kind, variant=0):
    b = copy.deepcopy(base)
    if kind in {"rename", "combined"}:
        alias = ["paid_total", "amount_paid", "payment_amount", "collected_amount"][variant % 4]
        for batch in b["batches"]:
            if batch["table"] == "payments":
                for row in batch["rows"]:
                    row[alias] = row.pop("payment_value")
        b["contracts"]["payments"]["aliases"][alias] = "payment_value"
    if kind in {"date", "combined", "ambiguous"}:
        fmt = ["%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S"][variant % 4]
        if kind == "ambiguous":
            # Only ambiguous days are changed. The unchanged value cannot reveal
            # whether day or month came first, and source documentation is absent.
            fmt = "%d/%m/%Y %H:%M:%S"
            col = "order_delivered_customer_date"
            for batch in b["batches"]:
                if batch["table"] == "orders":
                    for row in batch["rows"]:
                        if row[col] and datetime.strptime(row[col], ISO).day <= 12:
                            row[col] = datetime.strptime(row[col], ISO).strftime(fmt)
            b["contracts"]["orders"]["date_formats"][col] = None
        else:
            for batch in b["batches"]:
                if batch["table"] == "orders":
                    for col in DATE_COLUMNS["orders"]:
                        for row in batch["rows"]:
                            if row[col]:
                                row[col] = datetime.strptime(row[col], ISO).strftime(fmt)
                        b["contracts"]["orders"]["date_formats"][col] = fmt
    if kind in {"replay", "combined"}:
        payment = next(x for x in b["batches"] if x["table"] == "payments")
        b["batches"].extend(copy.deepcopy(payment) for _ in range(1 + variant % 3))
    if kind == "batch_conflict":
        p = copy.deepcopy(next(x for x in b["batches"] if x["table"] == "payments"))
        p["rows"][0]["payment_value"] = str(float(p["rows"][0]["payment_value"]) + 1)
        b["batches"].append(p)
    return b

def pilot_suite():
    return [(f"{kind}-{i+1:02d}", kind, i) for kind in ["rename", "date", "replay", "combined", "ambiguous"] for i in range(6)]
