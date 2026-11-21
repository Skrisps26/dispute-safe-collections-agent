from typing import Literal
from pydantic import BaseModel, ConfigDict
from .models import SessionState

SAFE_ERROR = "I could not safely prepare that reply. Successful actions remain recorded in the evidence panel. Please ask again."
COURTESY = {"none": "", "understood": "Understood.", "thanks": "Thank you.",
            "sorry": "I'm sorry this is difficult.", "finance_only": "I can help only with this demo invoice.",
            "unknown": "I don't have evidence for that."}
QUESTIONS = {"none": "", "invoice_help": "What would you like to know about this invoice?",
             "payment_options": "Would you like to see the approved options?",
             "confirm_split": "Would you like to discuss this approved split?",
             "email_permission": "Would you like a simulated email summary?", "clarify": "Could you clarify your concern?"}


class ReplyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledgement: Literal["none", "understood", "thanks", "sorry", "finance_only", "unknown"]
    fact_ids: list[str]
    question: Literal["none", "invoice_help", "payment_options", "confirm_split", "email_permission", "clarify"]


def render(plan: ReplyPlan, state: SessionState) -> tuple[str, list[dict]]:
    if state.collection_hold and plan.question in {"payment_options", "confirm_split"}:
        raise ValueError("Payment question during hold")
    facts = [state.facts[fid] for fid in dict.fromkeys(plan.fact_ids)]
    if any(state.collection_hold and fact.collection for fact in facts):
        raise ValueError("Superseded collection fact")
    text = " ".join(x for x in [COURTESY[plan.acknowledgement], *(f.text for f in facts), QUESTIONS[plan.question]] if x)
    if not text or len(text) > 600:
        raise ValueError("Unsafe reply length")
    if any(f.fact_id.endswith(":split") for f in facts):
        state.discussed_split = True
    sources = [f.model_dump() for f in facts]
    return text, sources
