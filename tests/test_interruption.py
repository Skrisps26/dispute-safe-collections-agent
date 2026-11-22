"""Framework cancellation test, not an acoustic barge-in/latency measurement."""
import asyncio
import json
import pytest
from livekit.agents import llm
from collections_agent.models import SessionState
from collections_agent.session import create_session


class ScriptedLLM(llm.LLM):
    def __init__(self):
        super().__init__()
        self.after_case = asyncio.Event()

    def chat(self, *, chat_ctx, tools=None, conn_options, **kwargs):
        return ScriptedStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class ScriptedStream(llm.LLMStream):
    async def _run(self):
        if not any(isinstance(i,llm.FunctionCallOutput) for i in self.chat_ctx.items):
            self._event_ch.send_nowait(llm.ChatChunk(id="scripted",delta=llm.ChoiceDelta(role="assistant",tool_calls=[llm.FunctionToolCall(call_id="dispute-call",name="log_dispute",arguments='{"reason":"already_paid"}')])) )
        else:
            self._llm.after_case.set()
            await asyncio.Event().wait()  # consumer cancels output after successful effects


@pytest.mark.asyncio
async def test_framework_interrupt_keeps_one_case_and_hold():
    class NoChargeTestGuards:
        async def turn(self,*args):
            pass
    session, agent, provider = create_session(guards=NoChargeTestGuards())
    scripted = ScriptedLLM()
    provider.llm = scripted
    agent.update_options(llm=scripted)
    try:
        await session.start(agent=agent)
        run = session.run(user_input="I already paid")
        await asyncio.wait_for(scripted.after_case.wait(),5)
        await session.interrupt()
        await run
        case = agent.state.case_id
        assert case and agent.state.collection_hold
        assert len(agent.state.disputes) == 1
        assert agent.state.disputes["already_paid"]["customer_statement"] == "I already paid"
        cases = {e["payload"]["case_id"] for e in agent.state.events if e["type"]=="case_state"}
        assert cases == {case}
    finally:
        await session.aclose()
        await provider.close()
        await scripted.aclose()
