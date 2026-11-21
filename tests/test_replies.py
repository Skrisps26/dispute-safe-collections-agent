import pytest
from collections_agent.models import SessionState
from collections_agent.tools import DomainTools
from collections_agent.replies import ReplyPlan, render


def test_exact_balance_and_source_pointer():
    s = SessionState()
    result = DomainTools(s).execute("lookup_invoice", {})
    fact = result.facts[0]
    text, sources = render(ReplyPlan(acknowledgement="none", fact_ids=[fact.fact_id], question="none"), s)
    assert text == "The recorded balance is $1,200.00 USD."
    source = sources[0]["sources"][0]
    assert source["json_pointer"] == "/data/balance_cents"
    assert s.results[source["tool_call_id"]].data["balance_cents"] == 120000
    with pytest.raises(KeyError):
        render(ReplyPlan(acknowledgement="none", fact_ids=["invented"], question="none"), s)
    s.collection_hold = True
    with pytest.raises(ValueError):
        render(ReplyPlan(acknowledgement="none", fact_ids=[], question="payment_options"), s)
    with pytest.raises(ValueError):
        render(ReplyPlan(acknowledgement="none", fact_ids=[result.facts[-1].fact_id], question="none"), s)
