import re
from datetime import datetime, timezone
from typing import Literal
from .fixtures import bound_account, load_fixture, money
from .models import Fact, SessionState, Source, ToolResult, new_id

Reason = Literal["already_paid", "wrong_amount", "invoice_dispute", "stop_contact"]


class DomainTools:
    """Synchronous effects cannot be interrupted halfway through a dispute/escalation."""
    def __init__(self, state: SessionState):
        self.state = state
        self.framework_events = False

    def execute(self, name: str, inputs: dict, actor: str = "model", call_id: str | None = None) -> ToolResult:
        call_id = call_id or new_id()
        domain_event = actor == "policy" or not self.framework_events
        if domain_event:
            self.state.event("tool_call", {"call_id": call_id, "name": name, "inputs": inputs, "actor": actor})
        result = getattr(self, "_" + name)(call_id, **inputs)
        self.state.results[call_id] = result
        for fact in result.facts:
            self.state.facts[fact.fact_id] = fact
        if domain_event:
            self.state.event("tool_result", {"call_id": call_id, "result": result.model_dump(mode="json")})
        if name == "log_dispute" and result.ok:
            self.execute("escalate_to_human", {}, actor="policy")
        if name in {"log_dispute", "escalate_to_human"} and result.ok:
            self.state.event("case_state", {"case_id": self.state.case_id,
                "collection_hold": self.state.collection_hold, "contact_suppressed": self.state.contact_suppressed,
                "simulated": True})
        return result

    def fact(self, call: str, label: str, text: str, pointer: str, collection: bool = False) -> Fact:
        return Fact(fact_id=f"{call}:{label}", text=text,
                    sources=[Source(tool_call_id=call, json_pointer=pointer)], collection=collection)

    def _allowed(self, invoice_id):
        return invoice_id is None or invoice_id == self.state.invoice_id

    def _lookup_invoice(self, call, invoice_id=None):
        if not self._allowed(invoice_id):
            return ToolResult(ok=False, code="NOT_FOUND_OR_NOT_ALLOWED")
        a = bound_account(self.state)
        data = a.model_dump(mode="json", exclude={"payments", "email"})
        data["as_of"] = load_fixture().as_of.isoformat()
        facts = [self.fact(call, "balance", f"The recorded balance is {money(a.balance_cents)} USD.", "/data/balance_cents"),
                 self.fact(call, "due", f"The recorded due date is {a.due.isoformat()}; this demo is frozen as of {data['as_of']}.", "/data/due"),
                 self.fact(call, "details", f"{a.invoice_id} is a fictional service invoice for {a.name}; the original amount was {money(a.original_cents)} USD.", "/data/original_cents"),
                 self.fact(call, "fee", "There is no late fee.", "/data/fee_cents")]
        if a.installments:
            parts = " and ".join(f"{money(p.amount_cents)} on {p.date.isoformat()}" for p in a.installments)
            facts.append(self.fact(call, "split", f"The approved demo option is {parts}. This is a simulation, not a real payment agreement.", "/data/installments", True))
        return ToolResult(ok=True, data=data, facts=facts)

    def _get_payment_history(self, call, invoice_id=None):
        if not self._allowed(invoice_id):
            return ToolResult(ok=False, code="NOT_FOUND_OR_NOT_ALLOWED")
        a = bound_account(self.state)
        data = {"invoice_id": a.invoice_id, "payments": [p.model_dump(mode="json") for p in a.payments]}
        facts = [self.fact(call, f"payment-{i}", f"The ledger records a payment of {money(p.amount_cents)} on {p.date.isoformat()}. Customer payment claims are not verified ledger entries.", f"/data/payments/{i}") for i, p in enumerate(a.payments)]
        return ToolResult(ok=True, data=data, facts=facts)

    def _log_dispute(self, call, reason: Reason):
        if reason not in {"already_paid", "wrong_amount", "invoice_dispute", "stop_contact"}:
            return ToolResult(ok=False, code="INVALID_REASON")
        self.state.collection_hold = True
        if reason == "stop_contact":
            self.state.contact_suppressed = True
        if reason not in self.state.disputes:
            self.state.disputes[reason] = {"dispute_id": "SIM-D-" + new_id()[:12], "reason": reason,
                "customer_statement": self.state.last_customer_turn,
                "turn_id": self.state.turn_id, "timestamp": datetime.now(timezone.utc).isoformat(), "simulated": True}
        data = {**self.state.disputes[reason], "collection_hold": True, "contact_suppressed": self.state.contact_suppressed}
        facts = [self.fact(call, "dispute", "Your concern is recorded as a customer statement, not a verified ledger change.", "/data/customer_statement")]
        if self.state.contact_suppressed:
            facts.append(self.fact(call, "suppression", "Contact is suppressed in this demo; no follow-up email will be created.", "/data/contact_suppressed"))
        return ToolResult(ok=True, data=data, facts=facts)

    def _escalate_to_human(self, call):
        self.state.collection_hold = True
        if self.state.case_id is None:
            self.state.case_id = "SIM-C-" + new_id()[:12]
        text = "This demo case is marked for human review. Automated collection requests are paused. No real person has been contacted."
        data = {"case_id": self.state.case_id, "collection_hold": True, "simulated": True, "status_text": text}
        return ToolResult(ok=True, data=data, facts=[self.fact(call, "case", text, "/data/status_text")])

    def _send_followup_email(self, call):
        if self.state.contact_suppressed:
            return ToolResult(ok=False, code="CONTACT_SUPPRESSED")
        # Conservative consent gate; model instructions alone never authorize email.
        requests = [t for t in self.state.customer_turns if re.search(r"\b(?:email|e-mail)\s+(?:me|a|the)|\bsend\s+(?:me\s+)?(?:an?\s+)?(?:email|summary|reminder)", t["text"], re.I)]
        if not requests:
            return ToolResult(ok=False, code="CONSENT_REQUIRED")
        consent = requests[-1]["turn_id"]
        for email in self.state.emails:
            if email["consent_turn"] == consent:
                return ToolResult(ok=True, data=email, facts=[self.fact(call, "email", "A simulated email summary was created. No real email was sent.", "/data/simulated")])
        selected = [f for f in self.state.facts.values() if not f.collection and not f.fact_id.endswith(":email")]
        if self.state.discussed_split and not self.state.collection_hold:
            selected += [f for f in self.state.facts.values() if f.fact_id.endswith(":split")]
        if not selected:
            return ToolResult(ok=False, code="LOOKUP_REQUIRED")
        statements = "\n".join("Customer statement (unverified): " + t["text"] for t in self.state.customer_turns)
        body = "SIMULATION — no payment processing, real email or real handoff.\n" + "\n".join(dict.fromkeys(f.text for f in selected)) + "\n" + statements
        data = {"to": bound_account(self.state).email, "subject": "Simulated invoice conversation summary",
                "body": body, "simulated": True, "consent_turn": consent}
        # Bound telemetry payload, never silently truncate customer context.
        if len(body.encode()) > 5000:
            return ToolResult(ok=False, code="SUMMARY_LIMIT")
        self.state.emails.append(data)
        return ToolResult(ok=True, data=data, facts=[self.fact(call, "email", "A simulated email summary was created. No real email was sent.", "/data/simulated")])
