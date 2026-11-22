from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return uuid4().hex


class Source(BaseModel):
    tool_call_id: str
    json_pointer: str


class Fact(BaseModel):
    fact_id: str
    text: str
    sources: list[Source]
    collection: bool = False


class ToolResult(BaseModel):
    ok: bool
    code: str = "OK"
    data: dict[str, Any] = Field(default_factory=dict)
    facts: list[Fact] = Field(default_factory=list)


class SessionState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    session_id: str = Field(default_factory=new_id)
    visitor_id: str = "room-free"
    ip_hash: str = "room-free"
    participant_identity: str = ""
    customer_id: Literal["CUST-1001"] = "CUST-1001"
    invoice_id: Literal["INV-2026-1042"] = "INV-2026-1042"
    prompt_version: Literal["v1", "v2"] = "v2"
    turn_id: str = ""
    last_message_id: str = ""
    last_customer_turn: str = ""
    customer_turns: list[dict[str, str]] = Field(default_factory=list)
    collection_hold: bool = False
    contact_suppressed: bool = False
    disputes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    case_id: str | None = None
    facts: dict[str, Fact] = Field(default_factory=dict)
    results: dict[str, ToolResult] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    emails: list[dict[str, Any]] = Field(default_factory=list)
    discussed_split: bool = False
    email_consent_turn: str | None = None
    voice_lease: str | None = None
    voice_replies: int = 0
    requests: int = 0
    reserved_tokens: int = 0
    usage: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    emit: Any = Field(default=None, exclude=True)

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"v": 1, "seq": len(self.events) + 1, "session_id": self.session_id,
                 "turn_id": self.turn_id, "type": kind, "payload": payload}
        if len(self.events) >= 500:
            raise RuntimeError("Session event limit reached; start a new demo.")
        self.events.append(event)
        if self.emit:
            try:
                self.emit(event)
            except Exception:
                # Transport/queue failure cannot interrupt dispute policy. Replay uses the journal.
                pass
