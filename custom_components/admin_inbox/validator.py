"""Mechanical re-validation of AI Task output against the source email.

This is the safety-critical stage (prompt-injection defense). The
instruction template in extractor.py reduces nuisance extractions; this
module is what actually gates whether extracted data is trusted. See
PLAN.md section 7: the extractor call itself has no tools and no
llm_api, so the model has no HA control-plane access during the call —
this module re-checks every field of its output against the source text
before anything is done with it.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from homeassistant.util import dt as dt_util

from .const import (
    COUNTERPARTY_MAX_LEN,
    DUE_DATE_KINDS,
    EVENT_DATE_KINDS,
    ITEM_KINDS,
    SOURCE_QUOTE_MAX_LEN,
    TITLE_MAX_LEN,
)
from .models import ExtractedFields, RawEmail, ValidationRejection
from .store import normalize_text

_REQUIRED_FIELDS = ("kind", "title", "counterparty", "confidence", "source_quote")


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_amount(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def validate_extraction(
    data: dict,
    raw_email: RawEmail,
    *,
    past_years: int,
    future_years: int,
) -> ExtractedFields | ValidationRejection:
    """Run every mechanical check; any single failure rejects the whole item."""

    for field_name in _REQUIRED_FIELDS:
        if data.get(field_name) in (None, ""):
            return ValidationRejection(field=field_name, reason="missing_required_field")

    kind = data["kind"]
    if kind not in ITEM_KINDS:
        return ValidationRejection(field="kind", reason="invalid_enum_value")

    title = str(data["title"])
    if len(title) > TITLE_MAX_LEN:
        return ValidationRejection(field="title", reason="exceeds_length_cap")

    counterparty = str(data["counterparty"])
    if len(counterparty) > COUNTERPARTY_MAX_LEN:
        return ValidationRejection(field="counterparty", reason="exceeds_length_cap")

    source_quote = str(data["source_quote"])
    if len(source_quote) > SOURCE_QUOTE_MAX_LEN:
        return ValidationRejection(field="source_quote", reason="exceeds_length_cap")

    # Verbatim substring check, whitespace-normalized only. No fuzzy
    # matching: that leniency is exactly what a prompt-injection payload
    # would exploit to fabricate a plausible but unverified quote.
    normalized_body = normalize_text(raw_email.text)
    normalized_quote = normalize_text(source_quote)
    if not normalized_quote or normalized_quote not in normalized_body:
        return ValidationRejection(field="source_quote", reason="not_verbatim_in_source")

    try:
        confidence = float(data["confidence"])
    except (TypeError, ValueError):
        return ValidationRejection(field="confidence", reason="not_numeric")
    if not (0.0 <= confidence <= 1.0):
        return ValidationRejection(field="confidence", reason="out_of_range")

    amount = _parse_amount(data.get("amount"))
    if data.get("amount") not in (None, "") and amount is None:
        return ValidationRejection(field="amount", reason="not_numeric")

    currency = data.get("currency") or None
    if currency is not None and (not isinstance(currency, str) or len(currency) != 3):
        return ValidationRejection(field="currency", reason="invalid_iso4217")

    due_date_raw = data.get("due_date")
    event_date_raw = data.get("event_date")
    if due_date_raw not in (None, "") and _parse_date(due_date_raw) is None:
        return ValidationRejection(field="due_date", reason="unparseable_date")
    if event_date_raw not in (None, "") and _parse_date(event_date_raw) is None:
        return ValidationRejection(field="event_date", reason="unparseable_date")

    due_date = _parse_date(due_date_raw)
    event_date = _parse_date(event_date_raw)

    if bool(due_date) == bool(event_date):
        # Exactly one of the two must be set (both set or both unset are
        # both rejections — no silent coercion, see PLAN.md section 7).
        return ValidationRejection(field="due_date/event_date", reason="exactly_one_required")

    if kind in DUE_DATE_KINDS and due_date is None:
        return ValidationRejection(field="due_date", reason="required_for_kind")
    if kind in EVENT_DATE_KINDS and event_date is None:
        return ValidationRejection(field="event_date", reason="required_for_kind")

    the_date = due_date or event_date
    assert the_date is not None  # exactly one is set, checked above
    today = dt_util.now().date()
    try:
        earliest = today.replace(year=today.year - past_years)
    except ValueError:
        earliest = today.replace(year=today.year - past_years, day=28)
    try:
        latest = today.replace(year=today.year + future_years)
    except ValueError:
        latest = today.replace(year=today.year + future_years, day=28)
    if not (earliest <= the_date <= latest):
        field_name = "due_date" if due_date else "event_date"
        return ValidationRejection(field=field_name, reason="date_out_of_sane_range")

    return ExtractedFields(
        kind=kind,
        title=title,
        counterparty=counterparty,
        confidence=confidence,
        source_quote=source_quote,
        amount=amount,
        currency=currency,
        due_date=due_date,
        event_date=event_date,
    )
