import httpx
import pytest
from collections_agent.session import create_session


@pytest.mark.asyncio
async def test_room_free_disabled_session_has_no_provider_network(caplog):
    attempted = []
    def reject(request):
        attempted.append(str(request.url))
        raise AssertionError("Network forbidden")
    session, agent, provider = create_session(transport=httpx.MockTransport(reject))
    try:
        await session.start(agent=agent)
        await session.run(user_input="What is my balance?")
        replies = [i.text_content for i in session.history.items if getattr(i,"role",None) == "assistant"]
        assert replies and "budget is zero" in replies[-1]
        assert not attempted
        assert not agent.state.case_id
        assert "failed to emit event" not in caplog.text
    finally:
        await session.aclose()
        await provider.close()
