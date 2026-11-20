#!/usr/bin/env python3
"""Agent-level evaluation: run each scenario through Claude Code headless and score the answer.

Requires Claude Code installed and logged in. Each scenario costs a few cents of usage.

    python evals/run_agent_evals.py            # all scenarios
    python evals/run_agent_evals.py triage-queue

Checks per scenario:
- must_include:      phrases the final answer must contain (case-insensitive)
- must_not_include:  phrases that must never appear (e.g. full IBANs, "email sent")
- must_not_attempt:  tools the agent must not even try to call (blocked attempts count as failures)

Results are written to evals/results.json.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = json.loads((ROOT / "evals" / "agent_scenarios.json").read_text())
PREFIX = "mcp__plugin_ap-copilot_finance__"
READ_TOOLS = [
    "list_invoices", "get_invoice", "three_way_match", "find_duplicate_invoices",
    "check_policy", "assess_invoice", "triage_pending_invoices", "draft_vendor_email",
]


def run(scenario: dict) -> dict:
    cmd = [
        "claude", "-p", scenario["prompt"],
        "--plugin-dir", str(ROOT),
        "--output-format", "json",
        "--allowedTools", ",".join(PREFIX + t for t in READ_TOOLS),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=ROOT)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"id": scenario["id"], "passed": False, "failures": [f"Could not parse output: {proc.stderr[:300]}"]}

    answer = str(data.get("result", ""))
    lower = answer.lower()
    attempted = [d.get("tool_name", "") for d in data.get("permission_denials", [])]

    failures = []
    failures += [f"missing: {p}" for p in scenario["must_include"] if p.lower() not in lower]
    failures += [f"forbidden text: {p}" for p in scenario["must_not_include"] if p.lower() in lower]
    failures += [f"attempted forbidden tool: {t}" for t in scenario["must_not_attempt"] if any(t in a for a in attempted)]
    return {
        "id": scenario["id"],
        "passed": not failures,
        "failures": failures,
        "cost_usd": data.get("total_cost_usd"),
        "answer_preview": answer[:400],
    }


def main() -> None:
    wanted = set(sys.argv[1:])
    results = [run(s) for s in SCENARIOS if not wanted or s["id"] in wanted]
    passed = sum(r["passed"] for r in results)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']}  {'; '.join(r['failures'])}")
    print(f"\n{passed}/{len(results)} scenarios passed")
    (ROOT / "evals" / "results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
