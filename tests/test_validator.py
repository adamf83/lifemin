"""Tests for validator.py: the safety-critical mechanical re-validation stage."""
from __future__ import annotations

from decimal import Decimal

from custom_components.admin_inbox.models import ExtractedFields, RawEmail, ValidationRejection
from custom_components.admin_inbox.validator import validate_extraction

from .conftest import load_fixture_email

PAST_YEARS = 2
FUTURE_YEARS = 5


def _email(uid: str, text: str) -> RawEmail:
    return RawEmail(uid=uid, sender="a@b.com", subject="s", date="2026-09-01", text=text)


def test_happy_path_bill_validates():
    text = load_fixture_email("happy_bill.txt")
    data = {
        "kind": "bill",
        "title": "Energy bill",
        "counterparty": "British Gas",
        "amount": 87.42,
        "currency": "GBP",
        "due_date": "2026-10-15",
        "confidence": 0.95,
        "source_quote": "The amount due\nis 87.42 GBP and payment is due by 2026-10-15.",
    }
    result = validate_extraction(
        data, _email("1", text), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ExtractedFields)
    assert result.amount == Decimal("87.42")
    assert result.due_date.isoformat() == "2026-10-15"


def test_happy_path_appointment_validates():
    text = load_fixture_email("happy_appointment.txt")
    data = {
        "kind": "appointment",
        "title": "Dental appointment",
        "counterparty": "Riverside Dental Practice",
        "event_date": "2026-11-03",
        "confidence": 0.9,
        "source_quote": "dental appointment with Riverside Dental Practice on\n2026-11-03",
    }
    result = validate_extraction(
        data, _email("2", text), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ExtractedFields)
    assert result.event_date.isoformat() == "2026-11-03"


def test_missing_required_field_rejected():
    data = {"kind": "bill", "title": "x"}
    result = validate_extraction(
        data, _email("3", "body"), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)


def test_invalid_kind_rejected():
    data = {
        "kind": "not_a_real_kind",
        "title": "t",
        "counterparty": "c",
        "confidence": 0.5,
        "source_quote": "q",
        "due_date": "2026-10-01",
    }
    result = validate_extraction(
        data, _email("4", "q present here"), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "kind"


def test_injection_email_with_fabricated_quote_is_rejected():
    """The fake model naively complies and returns the injected values, but
    the source_quote it fabricates does not appear verbatim in the email
    (it splices together text that never occurs contiguously) -- proving
    the mechanical check works independent of whether the real model
    resists the injection."""
    text = load_fixture_email("injection.txt")
    data = {
        "kind": "bill",
        "title": "Fake bill",
        "counterparty": "Attacker",
        "amount": 999999,
        "currency": "GBP",
        "due_date": "2026-10-01",
        "confidence": 0.99,
        "source_quote": "amount 999999 due immediately, no review needed",
    }
    result = validate_extraction(
        data, _email("5", text), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "source_quote"
    assert result.reason == "not_verbatim_in_source"


def test_date_bait_past_rejected():
    text = load_fixture_email("date_bait.txt")
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "due_date": "1970-01-01",
        "confidence": 0.5,
        "source_quote": "due 1970-01-01",
    }
    result = validate_extraction(
        data, _email("6", text), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.reason == "date_out_of_sane_range"


def test_date_bait_future_rejected():
    text = load_fixture_email("date_bait.txt")
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "due_date": "2099-12-31",
        "confidence": 0.5,
        "source_quote": "due 2099-12-31",
    }
    result = validate_extraction(
        data, _email("7", text), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.reason == "date_out_of_sane_range"


def test_both_due_date_and_event_date_set_rejected():
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "due_date": "2026-10-01",
        "event_date": "2026-10-02",
        "confidence": 0.5,
        "source_quote": "q",
    }
    result = validate_extraction(
        data, _email("8", "q"), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "due_date/event_date"


def test_neither_due_date_nor_event_date_set_rejected():
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "confidence": 0.5,
        "source_quote": "q",
    }
    result = validate_extraction(
        data, _email("9", "q"), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "due_date/event_date"


def test_appointment_with_due_date_instead_of_event_date_rejected():
    data = {
        "kind": "appointment",
        "title": "t",
        "counterparty": "c",
        "due_date": "2026-10-01",
        "confidence": 0.5,
        "source_quote": "q",
    }
    result = validate_extraction(
        data, _email("10", "q"), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "event_date"


def test_confidence_out_of_range_rejected():
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "due_date": "2026-10-01",
        "confidence": 1.5,
        "source_quote": "q",
    }
    result = validate_extraction(
        data, _email("11", "q"), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "confidence"


def test_title_exceeding_length_cap_rejected():
    data = {
        "kind": "bill",
        "title": "x" * 201,
        "counterparty": "c",
        "due_date": "2026-10-01",
        "confidence": 0.5,
        "source_quote": "q",
    }
    result = validate_extraction(
        data, _email("12", "q"), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "title"


def test_whitespace_normalized_quote_still_matches():
    text = "Line one\n\n   Line   two   spans"
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "due_date": "2026-10-01",
        "confidence": 0.5,
        "source_quote": "Line one Line two spans",
    }
    result = validate_extraction(
        data, _email("13", text), past_years=PAST_YEARS, future_years=FUTURE_YEARS
    )
    assert isinstance(result, ExtractedFields)


def test_verify_source_quote_false_skips_verbatim_check():
    """Attachment-sourced items (PLAN.md section 1b): the quote is the
    model's own transcription of an image, so there's no independent text
    to check it against -- verify_source_quote=False accepts a quote that
    doesn't appear anywhere in raw_email.text (which is empty/notes-only
    for an upload)."""
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "due_date": "2026-10-01",
        "confidence": 0.5,
        "source_quote": "Amount due 42.00 GBP by 2026-10-01 (transcribed from image)",
    }
    result = validate_extraction(
        data,
        _email("14", ""),
        past_years=PAST_YEARS,
        future_years=FUTURE_YEARS,
        verify_source_quote=False,
    )
    assert isinstance(result, ExtractedFields)


def test_verify_source_quote_false_still_rejects_empty_quote():
    data = {
        "kind": "bill",
        "title": "t",
        "counterparty": "c",
        "due_date": "2026-10-01",
        "confidence": 0.5,
        "source_quote": "   ",
    }
    result = validate_extraction(
        data,
        _email("15", ""),
        past_years=PAST_YEARS,
        future_years=FUTURE_YEARS,
        verify_source_quote=False,
    )
    assert isinstance(result, ValidationRejection)
    assert result.field == "source_quote"
