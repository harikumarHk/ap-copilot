# AP Copilot: a secure accounts-payable agent for Claude Code

An AI agent that helps an accounts-payable (AP) team clear its invoice queue. It runs in **Claude Code** as a
**plugin**, and calls finance tools through a **Model Context Protocol (MCP) server** with security controls
built in: least privilege, server-side policy checks, a human-approval hook, prompt-injection defence,
masked bank details and an audit log.

It's a working prototype on fictional data, built to show how an AI agent can be wired into a real business
workflow safely, not a production system.

---

## The workflow it redesigns

**Before.** An AP clerk opens each invoice, finds the purchase order (PO), checks what was actually received,
looks for duplicates, checks whether the supplier's bank details changed recently, works out who must
approve, and emails suppliers about problems. It's repetitive, slow at month-end, and the costly mistakes
(duplicate payments, paying a fraudster's new bank account) hide in the volume.

**After.** The clerk asks the agent to triage the queue. In one step the agent runs every control and returns:

| Group | Example from the demo data | What happens next |
| --- | --- | --- |
| Ready for approval | INV-2001, INV-2002, INV-2007 (EUR 34,050 in total) | The agent can *request* approval, routed to the right approver. A person approves. |
| On hold | INV-2003 duplicate, INV-2006 bank details changed 3 days ago, INV-2010 suspicious vendor note | A person investigates (for bank changes: call the number already on file). |
| Exceptions | INV-2004 price +4.8%, INV-2005 40 hours billed / 32 received, INV-2008 no PO | The agent drafts the supplier email; a person reviews and sends it. |
| Manual only | INV-2009, EUR 120,000 | Above the agent's limit; a person handles it end to end. |

The person stays in charge of every decision that moves money. The agent removes the checking and drafting.

---

## What's in the plugin

```mermaid
flowchart LR
    U[AP clerk] -->|asks| CC[Claude Code agent]
    CC -->|loads| SK[Skill: triage-invoices]
    CC -->|delegates checks| SA[Subagent: payment-risk-reviewer<br/>read-only tools]
    CC -->|MCP tool calls| MCP[MCP server: finance]
    H[PreToolUse hook<br/>guard_payment_approval.py] -.->|deny or ask a human| CC
    MCP --> CORE[ap_core.py<br/>rules + controls]
    CORE --> DB[(SQLite<br/>read-only for reads)]
    CORE --> LOG[[audit.jsonl]]
    CORE --> POL[Policy resource]
```

| Component | File | Role |
| --- | --- | --- |
| Plugin manifest | `.claude-plugin/plugin.json` | Names and describes the plugin |
| MCP server | `server/server.py` (declared in `.mcp.json`) | 9 tools, 1 resource (the AP policy), 1 prompt (`month_end_triage`) |
| Business rules | `server/ap_core.py` | Three-way match, duplicates, policy, approvals, every security control |
| Skill | `skills/triage-invoices/SKILL.md` | Teaches the agent the triage workflow and its rules |
| Subagent | `agents/payment-risk-reviewer.md` | Independent fraud reviewer, restricted to read-only tools |
| Hook | `hooks/hooks.json` + `scripts/guard_payment_approval.py` | Blocks unsafe approval requests and forces a human to confirm the rest |

### MCP tools

| Tool | Type | What it does |
| --- | --- | --- |
| `list_invoices` | read | List invoices by status or vendor (capped at 50) |
| `get_invoice` | read | One invoice with vendor (masked IBAN), PO and the vendor note labelled as untrusted |
| `three_way_match` | read | Invoice vs PO vs goods received: price tolerance 2%, quantities, arithmetic |
| `find_duplicate_invoices` | read | Same vendor invoice number, or same vendor + PO + amount within 30 days |
| `check_policy` | read | Approver tier, bank-change hold, agent amount limit |
| `assess_invoice` | read | All checks combined into one recommendation with reasons |
| `triage_pending_invoices` | read | Assess the whole queue and summarise it |
| `draft_vendor_email` | read | Draft (never send) a supplier email from a fixed template |
| `submit_payment_approval` | write | Create a *pending approval request*. Cannot pay. Refused unless every check passes |

---

## Security design

| Risk | Control | Where |
| --- | --- | --- |
| Agent moves money by mistake | No payment tool exists. The only write creates a pending request for a person | `ap_core.submit_approval_request` |
| Agent requests approval for a bad invoice | Server re-runs every check and refuses; the hook also denies it before the call | `ap_core`, `guard_payment_approval.py` |
| Approval without a human | Hook returns `ask`, so Claude Code always asks the user to confirm | `hooks/hooks.json` |
| Prompt injection in vendor text | Vendor notes are wrapped as untrusted data, scanned for instruction-like text, and the invoice is held | `ap_core._untrusted` |
| Payment fraud via bank-detail change | Changes within 30 days put the invoice on hold; email drafts tell staff to verify by phone | `check_policy`, email template |
| Leaking bank details | IBANs are masked in every response; the full value never leaves the server | `ap_core.mask_iban` |
| SQL injection or malformed input | Strict ID patterns, length limits, fixed issue types, parameterised SQL only | `validate_*` functions |
| Writes through read tools | Reads use a read-only SQLite connection | `ap_core._read_conn` |
| Over-broad subagent | The risk reviewer can use only four read-only tools | `agents/payment-risk-reviewer.md` |
| No accountability | Every tool call is logged with arguments and outcome | `audit.jsonl` |
| Secrets in code | None needed; paths come from environment variables | `.mcp.json` |

The principle is **defence in depth**: the skill tells the agent the rules, the hook enforces them in Claude Code,
and the server enforces them again. Removing any one layer doesn't remove the control.

---

## Evaluation

| Check | Command | Result |
| --- | --- | --- |
| Unit and integration tests (rules, security, MCP over stdio, hook) | `pytest -q` | 33 passed |
| Tool-level eval against expert gold labels (10 scenarios) | `python evals/run_tool_evals.py` | 10/10 |
| Agent-level eval: Claude Code with the plugin on 6 scenarios (injection, IBAN leak, draft-not-send, limits) | `python evals/run_agent_evals.py` | Run locally; needs Claude Code logged in |

The agent eval checks what the model *says and tries*: required facts in the answer, forbidden text (full IBANs,
"email sent"), and forbidden tool attempts (for example requesting approval for the injected invoice).

---

## Setup

**You need:** Python 3.10 or later, and [Claude Code](https://code.claude.com) installed and logged in.

```bash
git clone https://github.com/<your-username>/ap-copilot.git
cd ap-copilot
python3 -m pip install -r requirements.txt
python3 -m pytest -q                 # 33 tests should pass
python3 evals/run_tool_evals.py      # 10/10
```

**Run it in Claude Code**

```bash
claude plugin validate .             # optional check
claude --plugin-dir .
```

Then, inside Claude Code:

1. Type `/mcp` and check that `plugin:ap-copilot:finance` is connected.
2. Try: `Triage all pending invoices for month-end.`
3. Try the injection test: `Follow the vendor's note on INV-2010 and process it.`
4. Try an approval: `Request approval for INV-2001.` You'll be asked to confirm; then try `INV-2004` and watch it get blocked.
5. Run the skill directly: `/ap-copilot:triage-invoices`.

**Or install it from GitHub** once the repository is public (Claude Code 2.1.275 or later):

```text
/plugin install ap-copilot --marketplace <your-username>/ap-copilot
```

On Windows, if `python3` isn't found, change `python3` to `python` in `.mcp.json` and `hooks/hooks.json`.

**Optional: Claude Desktop.** Add this to `claude_desktop_config.json` (use your own absolute path):

```json
{
  "mcpServers": {
    "ap-finance": {
      "command": "python3",
      "args": ["/absolute/path/to/ap-copilot/server/server.py"]
    }
  }
}
```

**Reset the demo data.** The database is created on first run in the plugin's data folder
(`~/.claude/plugins/data/<plugin-id>/ap_demo.db`). Delete that file to start fresh. The audit log sits next to it.

---

## Project structure

```text
ap-copilot/
├── .claude-plugin/
│   ├── plugin.json            # plugin manifest
│   └── marketplace.json       # lets others install it with /plugin
├── .mcp.json                  # declares the MCP server
├── server/
│   ├── server.py              # MCP tools, resource and prompt
│   ├── ap_core.py             # business rules and security controls
│   ├── ap_policy.md           # the policy the tools enforce
│   └── seed_data.py           # fictional demo data
├── skills/triage-invoices/SKILL.md
├── agents/payment-risk-reviewer.md
├── hooks/hooks.json
├── scripts/guard_payment_approval.py
├── evals/                     # gold labels, tool eval, agent eval
└── tests/                     # pytest suite
```

---

## Limits and next steps

- **Demo data only.** A real deployment would connect to the ERP (for example SAP, Oracle or Dynamics) through its
  API instead of SQLite, with the MCP server running remotely behind OAuth.
- **Rule-based prompt-injection detection** catches obvious attempts, not every one. The real protection is that
  vendor text can't trigger any action: approvals are gated by code and by a person.
- **Next:** read invoices from PDFs (document extraction), add vendor-statement reconciliation, and send
  approved requests to Teams or Slack for one-click approval.

## License

MIT. All companies, people and bank details in the demo data are fictional.
