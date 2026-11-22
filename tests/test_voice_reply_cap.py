from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import pytest
from livekit.agents import llm
from collections_agent.session import create_session
from collections_agent.voice import VoiceController


@pytest.mark.asyncio
async def test_blocked_turns_still_consume_speech_reply_allowance():
    class Switch:
        enabled=True
        def set_audio_enabled(self,value): self.enabled=value
    session,agent,provider=create_session()
    control=SimpleNamespace(input=Switch(),output=Switch(),interrupt=AsyncMock())
    room=SimpleNamespace(local_participant=SimpleNamespace(perform_rpc=AsyncMock(return_value="{}")))
    voice=VoiceController(agent,control,room,SimpleNamespace(delete=AsyncMock()))
    agent.state.voice_lease="test-lease"
    try:
        for _ in range(10):
            context=llm.ChatContext()
            context.add_message(role="user",content="Invoice question")
            replies=[text async for text in agent.llm_node(context,[],SimpleNamespace(tool_choice="auto"))]
            assert "budget is zero" in replies[-1]
        context=llm.ChatContext()
        context.add_message(role="user",content="Another question")
        replies=[text async for text in agent.llm_node(context,[],SimpleNamespace(tool_choice="auto"))]
        assert "Voice reply allowance exhausted" in replies[-1]
        assert not control.input.enabled and not control.output.enabled
        await asyncio.gather(*list(voice.off_tasks))
        assert agent.state.voice_replies==10 and agent.state.voice_lease is None
        assert provider.state.requests==0
    finally:
        await provider.close()
