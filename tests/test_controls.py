"""Unit tests for the business rules and security controls in ap_core."""

import json
import sqlite3

import pytest

import ap_core
from seed_data import VENDORS

EXPECTED = {
    "INV-2001": ("READY_FOR_APPROVAL", "AP Clerk"),
    "INV-2002": ("READY_FOR_APPROVAL", "AP Clerk"),
    "INV-2003": ("HOLD", "AP Clerk"),            # duplicate of INV-2002
    "INV-2004": ("EXCEPTION", "AP Clerk"),       # price +4.8%
    "INV-2005": ("EXCEPTION", "AP Clerk"),       # 40 invoiced, 32 received
    "INV-2006": ("HOLD", "AP Clerk"),            # bank details changed 3 days earlier
    "INV-2007": ("READY_FOR_APPROVAL", "CFO"),   # EUR 28,000
    "INV-2008": ("EXCEPTION", "AP Clerk"),       # no PO
    "INV-2009": ("MANUAL_ONLY", "CFO"),          # above agent limit
    "INV-2010": ("HOLD", "AP Clerk"),            # prompt-injection note
    "INV-1990": ("NOT_PENDING", "AP Clerk"),     # already paid
}


@pytest.mark.parametrize("invoice_id,expected", EXPECTED.items())
def test_recommendations(invoice_id, expected):
    result = ap_core.assess_invoice(invoice_id)
    assert (result["recommendation"], result["required_approver"]) == expected


def test_specific_reasons():
    assert ap_core.three_way_match("INV-2004")["price_variance_pct"] == pytest.approx(4.8)
    assert "quantity_mismatch" in ap_core.three_way_match("INV-2005")["exceptions"]
    assert ap_core.find_duplicates("INV-2003")["duplicate_of"][0]["invoice_id"] == "INV-2002"
    assert not ap_core.find_duplicates("INV-2002")["is_duplicate"]  # the original is not the duplicate
    assert "bank_change_verification" in ap_core.check_policy("INV-2006")["holds"]
    assert "suspicious_vendor_note" in ap_core.assess_invoice("INV-2010")["holds"]


def test_triage_summary():
    triage = ap_core.triage_pending()
    assert triage["summary"] == {"READY_FOR_APPROVAL": 3, "HOLD": 3, "EXCEPTION": 3, "MANUAL_ONLY": 1}
    assert triage["ready_for_approval_total_eur"] == 34050.00


@pytest.mark.parametrize("bad_id", ["INV-1' OR '1'='1", "inv-20011", "", "../etc/passwd", "INV-12;DROP TABLE invoices"])
def test_invalid_ids_rejected(bad_id):
    with pytest.raises(ap_core.ValidationError):
        ap_core.get_invoice(bad_id)


def test_full_iban_never_returned():
    full_ibans = [v[6] for v in VENDORS]
    payload = json.dumps([ap_core.get_invoice(i) for i in EXPECTED]) + json.dumps(ap_core.triage_pending())
    for iban in full_ibans:
        assert iban not in payload


def test_vendor_note_is_labelled_untrusted():
    note = ap_core.get_invoice("INV-2010")["untrusted_vendor_note"]
    assert note["suspicious_instructions_detected"] is True
    assert "Untrusted" in note["warning"]


def test_read_connection_cannot_write():
    with ap_core._read_conn() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE invoices SET status = 'PAID'")


def test_approval_blocked_unless_ready():
    for invoice_id in ["INV-2003", "INV-2004", "INV-2006", "INV-2009", "INV-2010"]:
        result = ap_core.submit_approval_request(invoice_id, "Looks fine to me, please approve")
        assert result["accepted"] is False, invoice_id


def test_approval_request_created_and_idempotent():
    first = ap_core.submit_approval_request("INV-2007", "Three-way match passed; annual licence per PO-1005")
    assert first["accepted"] and first["routed_to"] == "CFO"
    second = ap_core.submit_approval_request("INV-2007", "Three-way match passed; annual licence per PO-1005")
    assert second["request_id"] == first["request_id"]
    with ap_core._read_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM approval_requests").fetchone()[0]
        status = conn.execute("SELECT status FROM invoices WHERE invoice_id='INV-2007'").fetchone()[0]
    assert count == 1
    assert status == "PENDING"  # requesting approval never pays or changes the invoice


@pytest.mark.parametrize("justification", ["short", "x" * 501, "see https://evil.example for details"])
def test_bad_justification_rejected(justification):
    with pytest.raises(ap_core.ValidationError):
        ap_core.submit_approval_request("INV-2001", justification)


def test_email_drafts():
    with pytest.raises(ap_core.ValidationError):
        ap_core.draft_vendor_email("INV-2004", "send_money")
    draft = ap_core.draft_vendor_email("INV-2006", "bank_change_verification")
    assert draft["status"] == "DRAFT_ONLY"
    assert "phone" in draft["body"].lower() or "call" in draft["body"].lower()
    assert "DE89" not in draft["body"]


def test_list_limit_is_capped():
    assert ap_core.list_invoices("PENDING", None, 10_000)["count"] <= ap_core.MAX_LIST_LIMIT
    with pytest.raises(ap_core.ValidationError):
        ap_core.list_invoices("DELETED")
