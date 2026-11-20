#!/usr/bin/env python3
"""Tool-level evaluation: compare each control's output with expert gold labels.

No LLM involved, runs in a second. Prints a confusion-style report.

    python evals/run_tool_evals.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("AP_DATA_DIR", tempfile.mkdtemp(prefix="ap_eval_"))
sys.path.insert(0, str(ROOT / "server"))

import ap_core  # noqa: E402

GOLD = json.loads((ROOT / "evals" / "gold_labels.json").read_text())


def main() -> None:
    ap_core.reset_database()
    rows, correct = [], 0
    for item in GOLD:
        got = ap_core.assess_invoice(item["invoice_id"])
        ok = (
            got["recommendation"] == item["recommendation"]
            and got["required_approver"] == item["approver"]
            and set(item["must_flag"]) <= set(got["exceptions"] + got["holds"])
        )
        correct += ok
        rows.append((item["invoice_id"], item["recommendation"], got["recommendation"], "ok" if ok else "MISMATCH", item["scenario"]))

    width = max(len(r[4]) for r in rows)
    print(f"{'Invoice':<9} {'Expected':<19} {'Got':<19} {'Result':<9} Scenario")
    for inv, exp, got, res, scen in rows:
        print(f"{inv:<9} {exp:<19} {got:<19} {res:<9} {scen:<{width}}")
    print(f"\nAccuracy: {correct}/{len(rows)} ({correct / len(rows):.0%})")
    sys.exit(0 if correct == len(rows) else 1)


if __name__ == "__main__":
    main()
