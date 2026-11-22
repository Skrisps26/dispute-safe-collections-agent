import json
from types import SimpleNamespace
from collections_agent.models import SessionState
from collections_agent.tools import DomainTools
from collections_agent.telemetry import Publisher
from collections_agent.limits import Guards, LimitError
from collections_agent.settings import Settings
import pytest


def test_queue_failure_cannot_interrupt_dispute_escalation():
    state=SessionState(last_customer_turn="I already paid")
    def broken(event): raise RuntimeError("Publisher queue unavailable")
    state.emit=broken
    tools=DomainTools(state)
    result=tools.execute("log_dispute",{"reason":"already_paid"})
    case=state.case_id
    tools.execute("log_dispute",{"reason":"already_paid"})
    assert result.ok and case and state.collection_hold
    assert state.case_id==case and len(state.disputes)==1
    assert any(e["type"]=="tool_result" and e["payload"]["result"]["data"].get("case_id")==case for e in state.events)


@pytest.mark.asyncio
async def test_repeated_replay_preserves_case_without_consuming_journal():
    packets=[]
    async def publish(raw,**kwargs): packets.append(json.loads(raw))
    state=SessionState(participant_identity="bound",last_customer_turn="Stop contacting me")
    publisher=Publisher(SimpleNamespace(local_participant=SimpleNamespace(publish_data=publish)),state)
    try:
        DomainTools(state).execute("log_dispute",{"reason":"stop_contact"})
        await publisher.sync("bound",0)
        await publisher.queue.join()
        size=len(state.events)
        for _ in range(10):
            await publisher.sync("bound",size)
            await publisher.queue.join()
        assert len(state.events)==size
        assert any(p["type"]=="case_state" and p["payload"]["case_id"]==state.case_id and p["payload"]["contact_suppressed"] for p in packets)
        with pytest.raises(ValueError): await publisher.sync("other",0)
    finally:
        await publisher.close()


@pytest.mark.asyncio
async def test_evidence_capacity_stops_before_quota_or_generation():
    settings=Settings(_env_file=None,model_api_key="test",public_text_budget_usd=1,total_provider_budget_usd=1)
    state=SessionState(events=[{} for _ in range(461)])
    with pytest.raises(LimitError,match="Evidence capacity"):
        await Guards(settings).turn(state,"Invoice details","public-text")
