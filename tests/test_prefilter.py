"""Tests for prefilter.py."""
from __future__ import annotations

from custom_components.admin_inbox.models import RawEmail
from custom_components.admin_inbox.prefilter import apply_prefilter


def _email(sender="billing@britishgas.co.uk", subject="Your bill", text="Amount due 10 GBP") -> RawEmail:
    return RawEmail(uid="1", sender=sender, subject=subject, date="2026-09-01", text=text)


def test_empty_allowlist_and_keywords_pass_everything():
    assert apply_prefilter(_email(), sender_allowlist=[], keywords=[]) is None


def test_empty_body_is_rejected():
    email = _email(subject="", text="")
    result = apply_prefilter(email, sender_allowlist=[], keywords=[])
    assert result is not None
    assert result.reason == "empty_body"


def test_sender_allowlist_exact_address_match():
    email = _email(sender="Billing <billing@britishgas.co.uk>")
    result = apply_prefilter(
        email, sender_allowlist=["billing@britishgas.co.uk"], keywords=[]
    )
    assert result is None


def test_sender_allowlist_domain_match():
    email = _email(sender="Billing <billing@britishgas.co.uk>")
    result = apply_prefilter(email, sender_allowlist=["@britishgas.co.uk"], keywords=[])
    assert result is None


def test_sender_allowlist_rejects_unlisted_sender():
    email = _email(sender="spam@example.com")
    result = apply_prefilter(
        email, sender_allowlist=["billing@britishgas.co.uk"], keywords=[]
    )
    assert result is not None
    assert result.reason == "sender_not_allowlisted"


def test_keyword_match_passes():
    email = _email(subject="Your invoice is ready", text="")
    result = apply_prefilter(email, sender_allowlist=[], keywords=["invoice"])
    assert result is None


def test_keyword_no_match_rejects():
    email = _email(subject="Newsletter", text="Nothing relevant here")
    result = apply_prefilter(email, sender_allowlist=[], keywords=["invoice", "renewal"])
    assert result is not None
    assert result.reason == "no_keyword_match"


def test_invalid_regex_keyword_falls_back_to_substring():
    email = _email(subject="Bill [unterminated", text="")
    result = apply_prefilter(email, sender_allowlist=[], keywords=["[unterminated"])
    assert result is None
