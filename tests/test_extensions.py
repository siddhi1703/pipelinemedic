import copy
import json
import unittest
from unittest.mock import patch

from pipelinemedic.core import attempt, execute, fixed_plan, verify
from pipelinemedic.evaluate import NOOP, run_candidate_experiment
from pipelinemedic.heldout import heldout_suite, inject_heldout

from test_pipeline import fixture

REPAIRABLE = ["rename_items", "date_items", "replay_orders",
              "rename_payments_alt", "triple_items"]


class HeldOutTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture()
        self.gold = execute(self.base, NOOP)

    def test_every_repairable_heldout_family_recovers_and_is_verified(self):
        for kind in REPAIRABLE:
            with self.subTest(kind=kind):
                b = inject_heldout(self.base, kind, 1)
                run = attempt(b, fixed_plan(b))
                self.assertEqual(run["verdict"]["decision"], "accept",
                                 f"{kind}: {run['verdict'].get('failures')}")

    def test_heldout_repairs_do_not_mutate_raw_input(self):
        for kind in REPAIRABLE:
            with self.subTest(kind=kind):
                b = inject_heldout(self.base, kind, 0)
                original = copy.deepcopy(b)
                attempt(b, fixed_plan(b))
                self.assertEqual(b, original)

    def test_heldout_ambiguous_estimated_date_requires_review(self):
        b = inject_heldout(self.base, "ambiguous_estimated", 0)
        self.assertEqual(attempt(b, fixed_plan(b))["verdict"]["decision"], "human_review")

    def test_heldout_replay_preserves_every_valid_record(self):
        b = inject_heldout(self.base, "replay_orders", 2)
        run = attempt(b, fixed_plan(b))
        self.assertEqual(run["verdict"]["decision"], "accept")
        self.assertEqual(len(run["outcome"]["tables"]["orders"]),
                         len(self.gold["tables"]["orders"]))

    def test_unrepaired_heldout_rename_is_never_silently_accepted(self):
        # Dropping the required column must error or be rejected, never accepted.
        b = inject_heldout(self.base, "rename_items", 0)
        self.assertNotEqual(attempt(b, NOOP)["verdict"]["decision"], "accept")

    def test_suite_is_disjoint_from_pilot_and_well_formed(self):
        self.assertEqual(len(heldout_suite()), 24)
        families = {k for _, k, _ in heldout_suite()}
        self.assertFalse(families & {"rename", "date", "replay", "combined", "ambiguous"})


class CandidateExperimentTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture()

    def test_verifier_selects_a_correct_candidate_from_a_diverse_set(self):
        # Three proposals: two useless, one correct. Best-of-N must beat the
        # single first candidate, and selection must not peek at gold.
        from pipelinemedic.scenarios import inject
        faulted = inject(self.base, "rename", 0)
        good = fixed_plan(faulted)
        bad = {"operations": [], "human_review": False, "reason": "no-op"}
        seq = [(bad, {"estimated_cost_usd": 0.01}),
               (bad, {"estimated_cost_usd": 0.01}),
               (good, {"estimated_cost_usd": 0.01})]
        with patch("pipelinemedic.agent.propose_candidates", return_value=seq):
            out = run_candidate_experiment(self.base, "artifacts/_test_cand",
                                           families=("rename",), n=3)
        r = out["results"][0]
        self.assertFalse(r["one_candidate"]["correct"])   # first candidate was a no-op
        self.assertTrue(r["best_of_n"]["correct"])        # verifier found the good one
        self.assertGreaterEqual(r["distinct_plans"], 2)

    def test_failed_candidate_call_is_recorded_not_fabricated(self):
        seq = [(None, {"error": "Claude request timed out", "candidate": 1})]
        with patch("pipelinemedic.agent.propose_candidates", return_value=seq):
            out = run_candidate_experiment(self.base, "artifacts/_test_cand",
                                           families=("rename",), n=1)
        r = out["results"][0]
        self.assertEqual(r["candidates"][0]["error"], "Claude request timed out")
        self.assertFalse(r["best_of_n"]["correct"])


if __name__ == "__main__":
    unittest.main()
