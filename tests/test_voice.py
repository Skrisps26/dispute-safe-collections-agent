import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from livekit.agents import Agent, APIStatusError, APITimeoutError
from collections_agent.limits import LimitError
from collections_agent.session import create_session
from collections_agent.voice import VoiceController


class AudioSwitch:
    def __init__(self): self.enabled=True
    def set_audio_enabled(self,value): self.enabled=value


class SessionControl:
    def __init__(self):
        self.input,self.output=AudioSwitch(),AudioSwitch()
        self.interruptions=0
    async def interrupt(self): self.interruptions+=1


@pytest.mark.asyncio
async def test_disabled_voice_has_no_redis_or_provider_network():
    attempted=[]
    def reject(request):
        attempted.append(str(request.url));raise AssertionError("Network forbidden")
    session,agent,provider=create_session(transport=httpx.MockTransport(reject))
    redis=SimpleNamespace(get=AsyncMock(side_effect=AssertionError("Redis must not be read at zero budget")))
    voice=VoiceController(agent,SessionControl(),None,redis)
    try:
        with pytest.raises(LimitError,match="budget is zero"):
            await voice.enable("untrusted-lease")
        assert not attempted and not voice.providers
        redis.get.assert_not_called()
        assert agent.state.voice_lease is None
    finally:
        await provider.close()


@pytest.mark.parametrize("node,error",[("tts",APIStatusError("Insufficient credit",status_code=402)),("stt",APIStatusError("Unauthorized",status_code=401)),("tts",APITimeoutError("timeout"))])
@pytest.mark.asyncio
async def test_native_speech_fault_detaches_without_losing_text_or_case(monkeypatch,node,error):
    session,agent,provider=create_session()
    control=SessionControl()
    room=SimpleNamespace(local_participant=SimpleNamespace(perform_rpc=AsyncMock(return_value="{}")))
    redis=SimpleNamespace(delete=AsyncMock())
    voice=VoiceController(agent,control,room,redis)
    agent.state.last_customer_turn="I already paid"
    agent.domain.execute("log_dispute",{"reason":"already_paid"})
    agent.state.customer_turns.append({"turn_id":"t1","text":"I already paid"})
    case=agent.state.case_id
    agent.state.voice_lease="test-lease"
    provider.scope="public-voice"
    close=AsyncMock()
    voice.providers=[SimpleNamespace(aclose=close)]
    invoked=[]
    async def failing(*args):
        invoked.append(node)
        raise error
        yield  # make this an async iterator; no audio frame implementation
    monkeypatch.setattr(Agent.default,node+"_node",staticmethod(failing))
    try:
        async for _ in getattr(agent,node+"_node")(None,None):
            pytest.fail("Injected failure cannot produce a frame/transcript")
        await asyncio.gather(*list(voice.off_tasks))
        assert invoked == [node]
        assert control.input.enabled is control.output.enabled is False
        assert agent.turn_detection == "manual"
        assert not agent.state.voice_lease and provider.scope=="public-text"
        assert agent.state.case_id==case and agent.state.collection_hold
        assert agent.state.customer_turns[0]["text"]=="I already paid"
        assert provider.state.requests==0 and provider.state.usage==[]
        close.assert_awaited_once()
        assert agent.state.events[-1]["type"]=="voice_state"
    finally:
        await provider.close()
