import asyncio
import json
from .models import SessionState

ALLOWED = {"tool_call","tool_result","reply_sources","case_state","voice_state","limit","latency","error"}


class Publisher:
    def __init__(self, room, state: SessionState):
        self.room, self.state = room, state
        self.queue = asyncio.Queue(maxsize=501)
        self.task = asyncio.create_task(self.run())
        state.emit = self.enqueue

    def enqueue(self, event):
        raw = json.dumps(event, separators=(",",":"), ensure_ascii=False).encode()
        if event["type"] not in ALLOWED or len(raw) >= 8192:
            raise ValueError("Telemetry event is invalid or exceeds 8 KiB")
        self.queue.put_nowait(raw)

    async def run(self):
        while True:
            raw = await self.queue.get()
            try:
                await self.room.local_participant.publish_data(raw, reliable=True,
                    destination_identities=[self.state.participant_identity], topic="collections.events")
            except Exception:
                # Journal is authoritative; reconnect RPC replays individually, without fake success.
                pass
            finally:
                self.queue.task_done()

    async def sync(self, caller: str, after: int):
        if caller != self.state.participant_identity or after < 0 or after > len(self.state.events):
            raise ValueError("NOT_ALLOWED")
        # Enqueue an immutable snapshot in sequence, through the same publisher.
        for event in list(self.state.events)[after:]:
            self.enqueue(event)
        self.state.event("case_state", {"case_id":self.state.case_id,"collection_hold":self.state.collection_hold,
            "contact_suppressed":self.state.contact_suppressed,"simulated":True})
        self.state.event("voice_state", {"enabled":bool(self.state.voice_lease),"lease_id":self.state.voice_lease})
        return {"session_id":self.state.session_id,"last_seq":len(self.state.events)}

    async def close(self):
        self.state.emit = None
        self.task.cancel()
        await asyncio.gather(self.task,return_exceptions=True)


def attach_tool_events(session, agent):
    """Model events come from SDK executions; deterministic policy actions remain domain events."""
    agent.domain.framework_events = True
    state = agent.state

    @session.on("tool_execution_updated")
    def started(event):
        if event.update.type == "tool_call_started":
            call = event.update.function_call
            state.event("tool_call", {"call_id":call.call_id,"name":call.name,"inputs":json.loads(call.arguments),"actor":"model"})

    @session.on("function_tools_executed")
    def completed(event):
        for call, output in event.zipped():
            try:
                result = json.loads(output.output)
            except (TypeError,ValueError):
                result = {"ok":False,"code":"TOOL_EXECUTION_ERROR","data":{},"facts":[]}
            state.event("tool_result", {"call_id":call.call_id,"result":result})
