from collections_agent.models import SessionState
from collections_agent.tools import DomainTools


def state(text="I already paid"):
    s = SessionState(last_customer_turn=text, turn_id="t1")
    s.customer_turns.append({"turn_id":"t1", "text":text})
    return s


def test_bound_ledger_and_isolation():
    tools = DomainTools(state())
    result = tools.execute("lookup_invoice", {"invoice_id":"INV-2026-1042"})
    assert result.data["balance_cents"] == 120000
    assert "$1,200.00" in result.facts[0].text
    foreign = tools.execute("lookup_invoice", {"invoice_id":"INV-2026-1043"})
    unknown = tools.execute("lookup_invoice", {"invoice_id":"nonexistent"})
    assert foreign == unknown
    assert not foreign.data and foreign.code == "NOT_FOUND_OR_NOT_ALLOWED"
    history = tools.execute("get_payment_history", {})
    assert history.data["payments"] == [{"date":"2026-10-30", "amount_cents":20000}]


def test_dispute_escalation_idempotent_and_suppressed():
    s = state()
    tools = DomainTools(s)
    first = tools.execute("log_dispute", {"reason":"already_paid"})
    case = s.case_id
    assert first.data["customer_statement"] == "I already paid"
    tools.execute("log_dispute", {"reason":"already_paid"})
    assert s.case_id == case and len(s.disputes) == 1 and s.collection_hold
    assert any(e["type"] == "tool_call" and e["payload"]["actor"] == "policy" for e in s.events)
    tools.execute("log_dispute", {"reason":"stop_contact"})
    s.customer_turns.append({"turn_id":"t2", "text":"Send a reminder anyway"})
    assert tools.execute("send_followup_email", {}).code == "CONTACT_SUPPRESSED"
    assert not s.emails


def test_simulated_email_includes_discussion_and_claims():
    s = state("Can I pay in two parts?")
    tools = DomainTools(s)
    tools.execute("lookup_invoice", {})
    s.discussed_split = True
    assert tools.execute("send_followup_email", {}).code == "CONSENT_REQUIRED"
    s.customer_turns.append({"turn_id":"t2", "text":"Please email me what we discussed"})
    result = tools.execute("send_followup_email", {})
    assert result.ok and result.data["simulated"]
    assert result.data["to"] == "alex.morgan@example.test"
    assert "$600.00 on 2026-11-28" in result.data["body"]
    assert "$600.00 on 2026-12-12" in result.data["body"]
    assert "Customer statement (unverified): Can I pay in two parts?" in result.data["body"]
    tools.execute("send_followup_email", {})
    assert len(s.emails) == 1


def test_invalid_fixture_stops_startup():
    import pytest
    from collections_agent.fixtures import load_fixture, Account
    a = load_fixture().accounts[0].model_dump()
    a["balance_cents"] += 1
    with pytest.raises(ValueError):
        Account.model_validate(a)
