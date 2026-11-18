"""Gold scoring is isolated here, outside the runtime agent and verifier."""
from __future__ import annotations
import copy
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from .core import attempt, execute, fixed_plan, make_reports, verify
from .data import fingerprint
from .scenarios import inject, pilot_suite

NOOP = {"operations": [], "human_review": False, "reason": "Unrepaired input"}

def score(run, gold, expect_review=False):
    verdict, outcome = run["verdict"]["decision"], run["outcome"]
    if expect_review:
        return {"correct_recovery": False, "appropriate_review": verdict == "human_review", "incorrect_acceptance": verdict == "accept", "payment_error": None, "valid_record_changes": None}
    if "tables" not in outcome:
        return {"correct_recovery": False, "appropriate_review": False, "incorrect_acceptance": False, "payment_error": None, "valid_record_changes": None}
    changes = 0
    for t, rows in gold["tables"].items():
        columns = sorted(rows[0])
        def bag(rs): return Counter(tuple(r.get(c) for c in columns) for r in rs)
        a, b = bag(rows), bag(outcome["tables"][t])
        changes += sum((a-b).values()) + sum((b-a).values())
    correct = changes == 0 and outcome["metrics"] == gold["metrics"]
    return {"correct_recovery": verdict == "accept" and correct, "appropriate_review": False, "incorrect_acceptance": verdict == "accept" and not correct,
            "payment_error": str(abs(Decimal(outcome["metrics"]["payment_total"])-Decimal(gold["metrics"]["payment_total"]))), "valid_record_changes": changes}

def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2))

def run_pilot(base, output):
    output = Path(output)
    gold = execute(base, NOOP)
    # Evaluation references are never passed into fixed_plan(), propose(), or verify().
    save_json(output / "evaluation_only" / "reference_metrics.json", gold["metrics"])
    rows = []
    for case_id, kind, variant in pilot_suite():
        bundle = inject(base, kind, variant)
        for name, plan, checked in [("unrepaired", NOOP, False), ("fixed_rules", fixed_plan(bundle), False), ("fixed_rules_with_verifier", fixed_plan(bundle), True)]:
            run = attempt(bundle, plan, checker=checked)
            rows.append({"scenario": case_id, "family": kind, "method": name, "decision": run["verdict"]["decision"], "seconds": run["seconds"], **score(run, gold, kind == "ambiguous")})
        print(f"Pilot: {case_id}", flush=True)
    summaries = {}
    for name in ["unrepaired", "fixed_rules", "fixed_rules_with_verifier"]:
        selected = [x for x in rows if x["method"] == name]
        summaries[name] = {"scenarios": len(selected), "repairable_cases": sum(x["family"] != "ambiguous" for x in selected), "correct_recoveries": sum(x["correct_recovery"] for x in selected),
            "review_cases": sum(x["family"] == "ambiguous" for x in selected), "appropriate_reviews": sum(x["appropriate_review"] for x in selected), "incorrect_acceptances": sum(x["incorrect_acceptance"] for x in selected),
            "mean_runtime_seconds": sum(x["seconds"] for x in selected)/len(selected)}
    result = {"benchmark_status": "development pilot; NOT a held-out final evaluation", "suite": "30 synthetic scenarios: six variants each of rename, date, replay, combined, and ambiguous", "reference_metrics": gold["metrics"], "summary": summaries, "cases": rows}
    save_json(output / "pilot_results.json", result)
    return result

def checker_challenges(base, output):
    """Controlled bad candidates probe checker quality, not language-model quality."""
    gold = execute(base, NOOP)
    challenges = []
    replay = inject(base, "replay")
    wrong = execute(replay, NOOP)
    challenges.append(("Repeated payment batch retained", replay, wrong))
    missing = copy.deepcopy(gold)
    missing["tables"]["payments"] = missing["tables"]["payments"][1:]
    missing["metrics"] = make_reports(missing["tables"])
    challenges.append(("A legitimate payment record deleted", base, missing))
    changed = copy.deepcopy(gold)
    row = next(r for r in changed["tables"]["orders"] if r["order_delivered_customer_date"] and r["order_delivered_customer_date"][5:7] != r["order_delivered_customer_date"][8:10] and int(r["order_delivered_customer_date"][8:10]) <= 12)
    v = row["order_delivered_customer_date"]
    row["order_delivered_customer_date"] = v[:5]+v[8:10]+"-"+v[5:7]+v[10:]
    changed["metrics"] = make_reports(changed["tables"])
    challenges.append(("Day and month swapped in one valid date", base, changed))
    results = [{"challenge": name, "full": verify(b, candidate, "full"), "schema_only": verify(b, candidate, "schema_only")} for name,b,candidate in challenges]
    save_json(Path(output) / "checker_challenges.json", {"status": "hand-constructed negative controls, not AI-generated repairs", "cases": results})
    return results

def run_live_pilot(base, output, max_cases=4):
    from .agent import propose
    output = Path(output)
    gold = execute(base, NOOP)
    cases = []
    for kind in ["rename", "date", "replay", "ambiguous"][:max_cases]:
        print(f"Claude development case: {kind}", flush=True)
        bundle = inject(base, kind, 0)
        start = perf_counter()
        try:
            plan, audit = propose(bundle, output / "claude_traces" / f"{kind}.json")
            runs = {}
            for label, checked in [("agent_alone", False), ("agent_with_verifier", True)]:
                run = attempt(bundle, plan, checker=checked)
                runs[label] = {"decision": run["verdict"]["decision"], "failures": run["verdict"]["failures"], "execution_seconds": run["seconds"], **score(run, gold, kind == "ambiguous")}
            cases.append({"family": kind, "plan": plan, "claude_seconds": audit["seconds"], "estimated_cost_usd": audit["estimated_cost_usd"], "runs": runs})
        except Exception as e:
            cases.append({"family": kind, "error": str(e), "seconds": perf_counter()-start})
        save_json(output / "claude_pilot_results.json", {"status": "four development smoke cases; same model proposal reused for paired comparison; not a held-out performance claim", "cases": cases})
    return cases
