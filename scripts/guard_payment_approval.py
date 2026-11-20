#!/usr/bin/env python3
"""PreToolUse hook: a second, independent gate before any payment-approval request.

Claude Code runs this before the agent's submit_payment_approval tool call.
It reads the call from stdin and answers with a permission decision:

- "deny"  if the invoice is not READY_FOR_APPROVAL (the agent is told why), or
          if anything goes wrong (fail closed).
- "ask"   otherwise, so a person always confirms in Claude Code before the
          request is created, with the amount and approver shown.

The MCP server re-checks the same rules on its side, so the control holds even
if this hook is removed (defence in depth).
"""

import json
import os
import sys
from pathlib import Path


def decide(decision: str, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    try:
        event = json.load(sys.stdin)
        tool_input = event.get("tool_input", {}) or {}
        invoice_id = str(tool_input.get("invoice_id", ""))
        justification = str(tool_input.get("justification", ""))

        plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent))
        if os.environ.get("CLAUDE_PLUGIN_DATA") and not os.environ.get("AP_DATA_DIR"):
            os.environ["AP_DATA_DIR"] = os.environ["CLAUDE_PLUGIN_DATA"]
        sys.path.insert(0, str(plugin_root / "server"))
        import ap_core  # noqa: E402

        assessment = ap_core.assess_invoice(invoice_id)
    except Exception as exc:  # fail closed
        decide("deny", f"Payment-approval guard could not verify the request ({exc}). Blocked for safety.")

    if assessment["recommendation"] != "READY_FOR_APPROVAL":
        reasons = "; ".join(assessment["reasons"]) or ", ".join(assessment["holds"] + assessment["exceptions"])
        decide(
            "deny",
            f"{invoice_id} is {assessment['recommendation']} and cannot be sent for approval. {reasons}",
        )

    decide(
        "ask",
        f"Request approval for {invoice_id}: {assessment['vendor']}, EUR {assessment['amount']:,.2f}, "
        f"routed to {assessment['required_approver']}. Justification: {justification[:200]}",
    )


if __name__ == "__main__":
    main()
