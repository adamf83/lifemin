"""Cheap, local, no-network rules applied before any model call."""
from __future__ import annotations

import re

from .models import PrefilterRejection, RawEmail


def _sender_matches(sender: str, allowlist: list[str]) -> bool:
    sender_lower = sender.lower().strip()
    # Pull the bare address out of "Name <addr@example.com>" if present.
    match = re.search(r"<([^>]+)>", sender_lower)
    address = match.group(1) if match else sender_lower

    for entry in allowlist:
        entry_lower = entry.lower().strip()
        if not entry_lower:
            continue
        if entry_lower.startswith("@"):
            # Domain match, e.g. "@britishgas.co.uk"
            if address.split("@")[-1] == entry_lower[1:]:
                return True
        elif address == entry_lower or sender_lower == entry_lower:
            return True
    return False


def _keyword_matches(email: RawEmail, keywords: list[str]) -> bool:
    haystack = f"{email.subject}\n{email.text}".lower()
    for keyword in keywords:
        keyword_lower = keyword.strip().lower()
        if not keyword_lower:
            continue
        try:
            if re.search(keyword_lower, haystack):
                return True
        except re.error:
            # Not a valid regex; fall back to plain substring match.
            if keyword_lower in haystack:
                return True
    return False


def apply_prefilter(
    email: RawEmail,
    *,
    sender_allowlist: list[str],
    keywords: list[str],
) -> PrefilterRejection | None:
    """Return a PrefilterRejection to stop the pipeline, or None to proceed.

    An empty allowlist and empty keyword list mean "process everything from
    this mailbox" (fail-open default, documented in the plan: the IMAP
    folder itself is treated as the primary filter).
    """
    if not email.text.strip() and not email.subject.strip():
        return PrefilterRejection(reason="empty_body")

    if sender_allowlist and not _sender_matches(email.sender, sender_allowlist):
        return PrefilterRejection(reason="sender_not_allowlisted")

    if keywords and not _keyword_matches(email, keywords):
        return PrefilterRejection(reason="no_keyword_match")

    return None
