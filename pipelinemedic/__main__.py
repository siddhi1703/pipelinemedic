"""Run with python -m pipelinemedic from this project directory."""
import argparse
import json
from pathlib import Path
from .data import prepare, load_sample
from .core import attempt, fixed_plan
from .evaluate import NOOP, run_pilot, checker_challenges, run_live_pilot, save_json
from .scenarios import inject

def main():
    p = argparse.ArgumentParser(description="PipelineMedic local prototype")
    sub = p.add_subparsers(dest="cmd", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--source", required=True); prep.add_argument("--size", type=int, default=5000)
    sub.add_parser("baseline")
    sub.add_parser("evaluate")
    sub.add_parser("checker-tests")
    live = sub.add_parser("live-pilot"); live.add_argument("--max-cases", type=int, default=4)
    demo = sub.add_parser("demo"); demo.add_argument("--fault", choices=["rename","date","replay","combined","ambiguous"], default="replay"); demo.add_argument("--agent", action="store_true")
    args = p.parse_args()
    data, out = Path("data/olist_5000"), Path("artifacts")
    if args.cmd == "prepare":
        print(json.dumps(prepare(args.source, data, args.size), indent=2)); return
    base = load_sample(data)
    if args.cmd == "baseline":
        run = attempt(base, NOOP, db_path=out / "baseline.duckdb")
        save_json(out / "baseline.json", {"verdict": run["verdict"], "metrics": run["outcome"].get("metrics"), "seconds": run["seconds"]})
        print(json.dumps(json.loads((out / "baseline.json").read_text()), indent=2))
    elif args.cmd == "evaluate":
        result = run_pilot(base, out); print(json.dumps(result["summary"], indent=2))
    elif args.cmd == "checker-tests":
        print(json.dumps(checker_challenges(base, out), indent=2))
    elif args.cmd == "live-pilot":
        print(json.dumps(run_live_pilot(base, out, args.max_cases), indent=2))
    else:
        b = inject(base, args.fault)
        if args.agent:
            from .agent import propose
            plan, _ = propose(b, out / "demo_claude.json")
        else:
            plan = fixed_plan(b)
        run = attempt(b, plan, db_path=out / "accepted.duckdb")
        save_json(out / "demo.json", {"fault": args.fault, "method": "Claude CLI" if args.agent else "fixed rules", "plan": plan, "decision": run["verdict"], "metrics": run["outcome"].get("metrics"), "ledger": run["outcome"].get("ledger")})
        print((out / "demo.json").read_text())

if __name__ == "__main__":
    main()
