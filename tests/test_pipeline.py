import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from pipelinemedic.core import attempt, execute, fixed_plan, verify, make_reports, PipelineError
from pipelinemedic.data import DATE_COLUMNS, ISO, KEYS
from pipelinemedic.scenarios import inject
from pipelinemedic.agent import observe, propose

NOOP = {"operations": [], "human_review": False, "reason": "test"}

def fixture():
    orders = []
    for key in ["a", "b"]:
        row = {"order_id": key, "customer_id": f"customer-{key}", "order_status": "delivered" if key == "a" else "shipped", **{c: "" for c in DATE_COLUMNS["orders"]}}
        row.update(order_purchase_timestamp="2017-03-01 00:00:00", order_estimated_delivery_date="2017-03-03 00:00:00")
        if key == "a": row["order_delivered_customer_date"] = "2017-03-04 00:00:00"
        orders.append(row)
    items = [{"order_id": key, "order_item_id": seq, "price": "10.00", "freight_value": "1.00", "shipping_limit_date": "2017-03-02 00:00:00"} for key,seq in [("a","1"),("a","2"),("b","1")]]
    payments = [{"order_id": key,"payment_sequential": seq,"payment_value": value,"payment_type":"voucher","payment_installments":"1"} for key,seq,value in [("a","1","10.00"),("a","2","10.00"),("b","1","30.00")]]
    tables = {"orders": orders, "items": items, "payments": payments}
    return {"contracts": {t: {"columns":list(rows[0]),"aliases":{},"date_formats":{c:ISO for c in DATE_COLUMNS[t]},"keys":KEYS[t]} for t,rows in tables.items()}, "batches": [{"table":t,"batch_id":t+"-initial","rows":rows} for t,rows in tables.items()]}

class PipelineTests(unittest.TestCase):
    def setUp(self): self.base = fixture()

    def test_clean_reports_do_not_multiply_multi_item_payments(self):
        run = attempt(self.base, NOOP)
        self.assertEqual(run["verdict"]["decision"], "accept")
        self.assertEqual(run["outcome"]["metrics"]["payment_total"], "50.00")
        self.assertEqual(run["outcome"]["metrics"]["order_count"], 2)

    def test_late_delivery_denominator_excludes_undelivered_orders(self):
        metrics = execute(self.base, NOOP)["metrics"]
        self.assertEqual(metrics["eligible_delivered_orders"], 1)
        self.assertEqual(metrics["late_delivery_rate"], 1.0)

    def test_renamed_column_is_repaired_without_mutating_input(self):
        b = inject(self.base, "rename"); original = copy.deepcopy(b)
        run = attempt(b, fixed_plan(b))
        self.assertEqual(run["verdict"]["decision"], "accept")
        self.assertEqual(b, original)

    def test_declared_day_first_dates_restore_original_values(self):
        b = inject(self.base, "date")
        run = attempt(b, fixed_plan(b))
        self.assertEqual(run["verdict"]["decision"], "accept")
        self.assertEqual(run["outcome"]["tables"], execute(self.base, NOOP)["tables"])

    def test_repeated_batch_can_silently_double_payments(self):
        b = inject(self.base, "replay")
        self.assertEqual(execute(b, NOOP)["metrics"]["payment_total"], "100.00")
        self.assertEqual(attempt(b, NOOP)["verdict"]["decision"], "reject")

    def test_replay_repair_preserves_two_legitimate_payments(self):
        b = inject(self.base, "replay", 2)
        run = attempt(b, fixed_plan(b))
        self.assertEqual(run["verdict"]["decision"], "accept")
        self.assertEqual(len(run["outcome"]["tables"]["payments"]), 3)
        self.assertEqual(run["outcome"]["metrics"]["payment_total"], "50.00")

    def test_replay_multiple_times_has_same_result(self):
        a, b = inject(self.base,"replay",0), inject(self.base,"replay",2)
        self.assertEqual(execute(a,fixed_plan(a))["metrics"],execute(b,fixed_plan(b))["metrics"])

    def test_combined_faults_recover(self):
        b = inject(self.base, "combined")
        self.assertEqual(attempt(b,fixed_plan(b))["verdict"]["decision"], "accept")

    def test_ambiguous_date_requires_review(self):
        b = inject(self.base, "ambiguous")
        self.assertEqual(attempt(b, fixed_plan(b))["verdict"]["decision"], "human_review")

    def test_conflicting_batch_id_requires_review(self):
        b = inject(self.base, "batch_conflict")
        self.assertEqual(attempt(b, fixed_plan(b))["verdict"]["decision"], "human_review")

    def test_same_payload_with_new_batch_id_is_not_silently_discarded(self):
        b=inject(self.base,"replay"); b["batches"][-1]["batch_id"]="new-batch"
        self.assertEqual(attempt(b, fixed_plan(b))["verdict"]["decision"], "reject")

    def test_missing_valid_record_is_rejected(self):
        c=execute(self.base,NOOP); c["tables"]["payments"].pop();c["metrics"]=make_reports(c["tables"])
        self.assertEqual(verify(self.base,c)["decision"],"reject")

    def test_schema_only_checker_misses_record_loss(self):
        c=execute(self.base,NOOP);c["tables"]["payments"].pop();c["metrics"]=make_reports(c["tables"])
        self.assertEqual(verify(self.base,c,"schema_only")["decision"],"accept")

    def test_valid_but_wrong_date_is_rejected(self):
        c=execute(self.base,NOOP);c["tables"]["orders"][0]["order_delivered_customer_date"]="2017-04-03 00:00:00";c["metrics"]=make_reports(c["tables"])
        self.assertEqual(verify(self.base,c)["decision"],"reject")

    def test_orphan_relation_is_rejected(self):
        c=execute(self.base,NOOP);c["tables"]["items"][0]["order_id"]="orphan"
        self.assertEqual(verify(self.base,c)["decision"],"reject")

    def test_unapproved_operation_cannot_execute(self):
        with self.assertRaises(PipelineError):execute(self.base,{"operations":[{"op":"delete_rows"}],"human_review":False})

    def test_column_collision_cannot_overwrite_valid_data(self):
        p={"operations":[{"op":"rename_column","table":"payments","source":"payment_sequential","target":"payment_value"}],"human_review":False}
        self.assertEqual(attempt(self.base,p)["verdict"]["decision"],"reject")

    def test_rejected_candidate_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"accepted.duckdb"
            attempt(inject(self.base,"replay"),NOOP,db_path=path)
            self.assertFalse(path.exists())

    def test_verified_candidate_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"accepted.duckdb"
            attempt(self.base,NOOP,db_path=path)
            self.assertTrue(path.exists())

    def test_agent_evidence_excludes_customer_and_order_records(self):
        evidence=json.dumps(observe(self.base))
        self.assertNotIn("customer-a",evidence)
        self.assertNotIn('"rows"',evidence)
        self.assertNotIn("reference_metrics",evidence)

    @patch("pipelinemedic.agent.shutil.which",return_value="/mock/claude")
    @patch("pipelinemedic.agent.subprocess.run")
    def test_cli_json_and_cost_are_parsed(self,run,which):
        run.return_value=SimpleNamespace(returncode=0,stdout=json.dumps({"structured_output":NOOP,"total_cost_usd":0.01}))
        plan,audit=propose(self.base)
        self.assertEqual(plan,NOOP)
        self.assertEqual(audit["estimated_cost_usd"],0.01)
        self.assertFalse(audit["tools_enabled"])

    @patch("pipelinemedic.agent.shutil.which",return_value="/mock/claude")
    @patch("pipelinemedic.agent.subprocess.run")
    def test_failed_cli_is_not_reported_as_success(self,run,which):
        run.return_value=SimpleNamespace(returncode=1,stdout=json.dumps({"is_error":True,"result":"Not signed in"}))
        with self.assertRaises(PipelineError):propose(self.base)

if __name__ == "__main__": unittest.main()
