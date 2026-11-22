"""Thin provider attachment/lifecycle glue. LiveKit/Gnani own all audio processing."""
import asyncio
import json
import time
from livekit import rtc
from .limits import LimitError


class VoiceController:
    def __init__(self, agent, session, room, redis):
        self.agent, self.session, self.room, self.redis = agent, session, room, redis
        self.state = agent.state
        self.providers = []
        self.timer = None
        self.lock = asyncio.Lock()
        self.off_tasks = set()
        self.text_scope = agent.provider.scope
        agent.voice = self

    def register(self):
        @self.room.local_participant.register_rpc_method("collections.set_voice")
        async def set_voice(data: rtc.RpcInvocationData):
            if data.caller_identity != self.state.participant_identity:
                raise ValueError("NOT_ALLOWED")
            body = json.loads(data.payload)
            if set(body) - {"enabled","lease_id"} or type(body.get("enabled")) is not bool:
                raise ValueError("INVALID_REQUEST")
            if body["enabled"]:
                await self.enable(body.get("lease_id"))
            else:
                await self.off("Voice turned off; continuing in text.")
            return json.dumps({"enabled":bool(self.state.voice_lease)})

    async def enable(self, lease_id):
        async with self.lock:
            if self.state.voice_lease:
                raise LimitError("Voice is already enabled.")
            # Zero budget fails before any Redis read or speech provider construction.
            from .limits import require_budget
            settings = self.agent.provider.settings
            require_budget(settings, "public-voice")
            if not settings.voice_enabled or not settings.gnani_api_key or settings.gnani_max_cost_per_call_usd <= 0:
                raise LimitError("Voice disabled: verified pricing, credit safeguards and credentials required.")
            if not isinstance(lease_id,str) or len(lease_id)>64:
                raise ValueError("INVALID_LEASE")
            key = f"collections:voice-lease:{lease_id}"
            lease = await self.redis.get(key)
            if isinstance(lease,str):
                lease = json.loads(lease)
            if not lease or lease.get("session_id") != self.state.session_id or lease.get("visitor_id") != self.state.visitor_id or lease.get("participant_identity") != self.state.participant_identity or lease.get("expires",0) <= time.time():
                raise ValueError("INVALID_LEASE")
            if not await self.redis.getdel(key):
                raise ValueError("LEASE_ALREADY_USED")
            await self.agent.provider.guards.voice_slot(self.state)
            # No retries/refunds: quota and conservative full-call cost are already reserved.
            try:
                from livekit.plugins import gnani, silero
                from livekit.agents import inference
                stt = gnani.STT(api_key=settings.gnani_api_key,language="en-IN",use_streaming=True)
                self.providers.append(stt)
                tts = gnani.TTS(api_key=settings.gnani_api_key,model="timbre-v2.5",voice="Kaveri",language="en-IN",synthesize_method="websocket")
                self.providers.append(tts)
                vad = silero.VAD.load()
                self.providers.append(vad)
                self.agent.update_options(stt=stt,tts=tts,vad=vad)
                self.agent.turn_detection = inference.TurnDetector()
                self.state.voice_lease = lease_id
                self.state.voice_replies = 0
                self.session.input.set_audio_enabled(True)
                self.session.output.set_audio_enabled(True)
                self.timer = asyncio.create_task(self.expire())
                self.state.event("voice_state", {"enabled":True,"lease_id":lease_id,"message":"Voice enabled for at most 150 seconds and ten replies; captions are not word-aligned."})
            except Exception:
                # Outside audio iterators: safe to detach/close providers here.
                await self._off("Voice unavailable; continue using text.")
                raise

    async def expire(self):
        await asyncio.sleep(150)
        await self.off("Voice time limit reached; continuing in text.")

    def schedule_off(self, reason):
        self.session.input.set_audio_enabled(False)
        self.session.output.set_audio_enabled(False)
        task = asyncio.create_task(self.off(reason))
        self.off_tasks.add(task)
        task.add_done_callback(self.off_tasks.discard)

    async def off(self, reason):
        async with self.lock:
            await self._off(reason)

    async def _off(self, reason):
        # This method is always invoked outside the failing STT/TTS iterator.
        lease = self.state.voice_lease
        await self.session.interrupt()
        self.session.input.set_audio_enabled(False)
        self.session.output.set_audio_enabled(False)
        self.agent.turn_detection = "manual"
        self.agent.update_options(stt=None,tts=None,vad=None)
        self.state.voice_lease = None
        self.agent.provider.scope = self.text_scope
        if self.timer and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.timer = None
        providers, self.providers = self.providers, []
        for provider in providers:
            try:
                await provider.aclose()
            except Exception:
                pass
        if lease:
            await self.redis.delete(f"collections:voice-pending:{self.state.session_id}")
        self.state.event("voice_state", {"enabled":False,"lease_id":None,"message":reason})
        # Request microphone unpublication through the SDK; UI also reacts to voice_state.
        try:
            await self.room.local_participant.perform_rpc(destination_identity=self.state.participant_identity,
                method="collections.voice_off",payload="{}",response_timeout=3)
        except Exception:
            pass
