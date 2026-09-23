"""Dataclasses and enums used across the admin_inbox pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class ItemState(StrEnum):
    """Lifecycle state of a StoredItem."""

    PENDING_FETCH = "pending_fetch"
    FETCH_FAILED = "fetch_failed"
    EXTRACTION_FAILED = "extraction_failed"
    VALIDATION_REJECTED = "validation_rejected"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"


TERMINAL_STATES = {
    ItemState.EXTRACTION_FAILED,
    ItemState.VALIDATION_REJECTED,
    ItemState.PENDING,
    ItemState.CONFIRMED,
    ItemState.REJECTED,
    ItemState.EXPIRED,
}

# States that mean "already processed, do not reprocess this uid".
DEDUP_BLOCKED_STATES = {
    ItemState.PENDING_FETCH,
    ItemState.EXTRACTION_FAILED,
    ItemState.VALIDATION_REJECTED,
    ItemState.PENDING,
    ItemState.CONFIRMED,
    ItemState.REJECTED,
    ItemState.EXPIRED,
}


@dataclass
class FetchRequest:
    """A request to fetch a single email, emitted by the listener."""

    entry_id: str
    uid: str
    message_id: str | None = None


@dataclass
class RawEmail:
    """The fetched content of a single email."""

    uid: str
    sender: str
    subject: str
    date: str
    text: str
    parts: list[str] = field(default_factory=list)


@dataclass
class MessageRef:
    """Enough information to locate the source email, without its body."""

    entry_id: str
    uid: str
    message_id: str | None
    subject: str
    sender: str
    date: str

    def as_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "uid": self.uid,
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MessageRef:
        return cls(
            entry_id=data["entry_id"],
            uid=data["uid"],
            message_id=data.get("message_id"),
            subject=data.get("subject", ""),
            sender=data.get("sender", ""),
            date=data.get("date", ""),
        )


@dataclass
class ExtractedFields:
    """Fields extracted by the AI Task model, pre-validation."""

    kind: str
    title: str
    counterparty: str
    confidence: float
    source_quote: str
    amount: Decimal | None = None
    currency: str | None = None
    due_date: date | None = None
    event_date: date | None = None


@dataclass
class ExtractionFailure:
    reason: str


@dataclass
class PrefilterRejection:
    reason: str


@dataclass
class ValidationRejection:
    field: str
    reason: str


@dataclass
class ValidatedItem:
    """An item that has passed all validator checks, ready for the review queue."""

    fields: ExtractedFields
    raw_email: RawEmail


@dataclass
class StoredItem:
    """A persisted admin_inbox item, in any lifecycle state."""

    id: str
    entry_id: str
    uid: str
    content_hash: str
    state: ItemState
    created_at: datetime
    updated_at: datetime
    kind: str | None = None
    title: str | None = None
    counterparty: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    due_date: date | None = None
    event_date: date | None = None
    confidence: float | None = None
    source_quote: str | None = None
    message_ref: MessageRef | None = None
    reviewed_at: datetime | None = None
    reason: str | None = None
    known_uids: list[str] = field(default_factory=list)
    fetch_failure_count: int = 0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "uid": self.uid,
            "content_hash": self.content_hash,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "kind": self.kind,
            "title": self.title,
            "counterparty": self.counterparty,
            "amount": str(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "confidence": self.confidence,
            "source_quote": self.source_quote,
            "message_ref": self.message_ref.as_dict() if self.message_ref else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reason": self.reason,
            "known_uids": self.known_uids,
            "fetch_failure_count": self.fetch_failure_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StoredItem:
        return cls(
            id=data["id"],
            entry_id=data["entry_id"],
            uid=data["uid"],
            content_hash=data["content_hash"],
            state=ItemState(data["state"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            kind=data.get("kind"),
            title=data.get("title"),
            counterparty=data.get("counterparty"),
            amount=Decimal(data["amount"]) if data.get("amount") is not None else None,
            currency=data.get("currency"),
            due_date=date.fromisoformat(data["due_date"]) if data.get("due_date") else None,
            event_date=date.fromisoformat(data["event_date"]) if data.get("event_date") else None,
            confidence=data.get("confidence"),
            source_quote=data.get("source_quote"),
            message_ref=MessageRef.from_dict(data["message_ref"]) if data.get("message_ref") else None,
            reviewed_at=datetime.fromisoformat(data["reviewed_at"]) if data.get("reviewed_at") else None,
            reason=data.get("reason"),
            known_uids=data.get("known_uids", []),
            fetch_failure_count=data.get("fetch_failure_count", 0),
        )
