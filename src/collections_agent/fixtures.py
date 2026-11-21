import json
from datetime import date
from pathlib import Path
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]


class Payment(BaseModel):
    date: date
    amount_cents: int = Field(ge=0, strict=True)


class Account(BaseModel):
    customer_id: str
    name: str
    email: str
    invoice_id: str
    currency: str
    description: str
    original_cents: int = Field(ge=0, strict=True)
    balance_cents: int = Field(ge=0, strict=True)
    fee_cents: int = Field(ge=0, strict=True)
    due: date
    payments: list[Payment]
    installments: list[Payment]

    @model_validator(mode="after")
    def valid_ledger(self):
        if self.original_cents + self.fee_cents - sum(p.amount_cents for p in self.payments) != self.balance_cents:
            raise ValueError("Invalid ledger")
        if self.installments and sum(p.amount_cents for p in self.installments) != self.balance_cents:
            raise ValueError("Invalid installments")
        return self


class Fixture(BaseModel):
    as_of: date
    accounts: list[Account]

    @model_validator(mode="after")
    def unique(self):
        if self.as_of != date(2026, 11, 21):
            raise ValueError("Fixture date must remain frozen")
        for field in ("customer_id", "invoice_id"):
            values = [getattr(a, field) for a in self.accounts]
            if len(values) != len(set(values)):
                raise ValueError("Duplicate binding")
        return self


def load_fixture() -> Fixture:
    return Fixture.model_validate(json.loads((ROOT / "data/demo.json").read_text()))


def bound_account(state) -> Account:
    fixture = load_fixture()
    return next(a for a in fixture.accounts if a.customer_id == state.customer_id and a.invoice_id == state.invoice_id)


def money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"
