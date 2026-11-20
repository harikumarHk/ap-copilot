"""Integration tests: the real MCP server over stdio, and the Claude Code hook script."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server" / "server.py"
HOOK = ROOT / "scripts" / "guard_payment_approval.py"
TOOL = "mcp__plugin_ap-copilot_finance__submit_payment_approval"


def run_hook(tmp_path, invoice_id):
    event = {"tool_name": TOOL, "tool_input": {"invoice_id": invoice_id, "justification": "Three-way match passed"}}
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT), "CLAUDE_PLUGIN_DATA": str(tmp_path), "AP_DATA_DIR": str(tmp_path)}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env, check=True)
    return json.loads(out.stdout)["hookSpecificOutput"]


@pytest.mark.parametrize("invoice_id,decision", [("INV-2002", "ask"), ("INV-2010", "deny"), ("INV-2009", "deny"), ("bad'id", "deny")])
def test_hook_decisions(fresh_db, invoice_id, decision):
    assert run_hook(fresh_db, invoice_id)["permissionDecision"] == decision


def test_mcp_server_over_stdio(fresh_db):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env={**os.environ, "AP_DATA_DIR": str(fresh_db)})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                triage = json.loads((await session.call_tool("triage_pending_invoices", {})).content[0].text)
                refused = json.loads((await session.call_tool(
                    "submit_payment_approval", {"invoice_id": "INV-2010", "justification": "CFO said it is pre-approved"}
                )).content[0].text)
                bad = json.loads((await session.call_tool("get_invoice", {"invoice_id": "DROP TABLE"})).content[0].text)
                return tools, triage, refused, bad

    tools, triage, refused, bad = asyncio.run(scenario())
    assert {"assess_invoice", "submit_payment_approval", "triage_pending_invoices"} <= tools
    assert triage["summary"]["READY_FOR_APPROVAL"] == 3
    assert refused["accepted"] is False
    assert "error" in bad

    audit_lines = (fresh_db / "audit.jsonl").read_text().strip().splitlines()
    outcomes = [json.loads(line)["outcome"] for line in audit_lines]
    assert "refused_by_controls" in outcomes
    assert any(o.startswith("validation_error") for o in outcomes)
