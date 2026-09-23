"""Orchestrates prefilter -> fetch -> extract -> validate -> review queue."""
from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_DEDUP_PRUNE_DAYS,
    CONF_DUE_DATE_FUTURE_YEARS,
    CONF_DUE_DATE_PAST_YEARS,
    CONF_FETCH_FAILURE_THRESHOLD,
    CONF_KEYWORDS,
    CONF_SENDER_ALLOWLIST,
    DEFAULT_DEDUP_PRUNE_DAYS,
    DEFAULT_DUE_DATE_FUTURE_YEARS,
    DEFAULT_DUE_DATE_PAST_YEARS,
    DEFAULT_FETCH_FAILURE_THRESHOLD,
    DOMAIN,
    ISSUE_AI_TASK_ENTITY_MISSING,
    ISSUE_IMAP_FETCH_DEGRADED,
)
from .extractor import async_extract
from .fetcher import FetchError, async_fetch_email
from .models import (
    ExtractionFailure,
    FetchRequest,
    ItemState,
    MessageRef,
    StoredItem,
    ValidationRejection,
)
from .prefilter import apply_prefilter
from .store import AdminInboxStore, content_hash
from .validator import validate_extraction

_LOGGER = logging.getLogger(__name__)

_FETCH_FAILURE_WINDOW = timedelta(hours=24)


class PipelineDiagnostics:
    """In-memory counters surfaced via diagnostics.py and reset on restart."""

    def __init__(self) -> None:
        self.dedup_dropped = 0
        self.prefiltered = 0
        self.extraction_failed = 0
        self.validation_rejected = 0
        self.fetch_failed = 0


class AdminInboxPipeline:
    """Drives a FetchRequest through every pipeline stage.

    Two entry points share the same post-fetch pipeline
    (`_async_process_fetched`): a fresh `imap_content` event
    (`async_handle_fetch_request`, which reserves a new placeholder item)
    and reconciliation's retry of a stuck item
    (`async_reconcile`, which reuses the existing placeholder).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry,
        store: AdminInboxStore,
        on_item_changed: Callable[[], None],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.store = store
        self._on_item_changed = on_item_changed
        self.diagnostics = PipelineDiagnostics()
        self._fetch_failure_times: deque[datetime] = deque()

    def _options(self) -> dict:
        return self.entry.options

    def _push_update(self) -> None:
        self._on_item_changed()

    async def async_handle_fetch_request(self, request: FetchRequest) -> None:
        if self.store.is_uid_known(request.uid):
            self.diagnostics.dedup_dropped += 1
            return

        item = self.store.reserve_pending_fetch(request.uid)
        self._push_update()
        await self._async_fetch_and_process(item, request)

    async def async_reconcile(self) -> None:
        """Retry items stuck in pending_fetch/fetch_failed (mitigates flaky IMAP push)."""
        for item in self.store.stuck_items(timedelta(hours=1)):
            request = FetchRequest(entry_id=item.entry_id, uid=item.uid)
            await self._async_fetch_and_process(item, request)

    def async_prune(self) -> int:
        days = self._options().get(CONF_DEDUP_PRUNE_DAYS, DEFAULT_DEDUP_PRUNE_DAYS)
        pruned = self.store.prune_dedup_only_older_than(days)
        if pruned:
            self._push_update()
        return pruned

    # -- shared post-fetch pipeline --------------------------------------

    async def _async_fetch_and_process(self, item: StoredItem, request: FetchRequest) -> None:
        try:
            raw_email = await async_fetch_email(self.hass, request)
        except FetchError as err:
            _LOGGER.warning("admin_inbox: fetch failed for uid %s: %s", request.uid, err)
            self.store.mark_fetch_failed(item)
            self.diagnostics.fetch_failed += 1
            self._push_update()
            self._async_record_fetch_failure()
            return

        await self._async_process_fetched(item, request, raw_email)

    async def _async_process_fetched(self, item: StoredItem, request: FetchRequest, raw_email) -> None:
        chash = content_hash(raw_email.text)
        existing = self.store.find_by_content_hash(chash)
        if existing is not None and existing.id != item.id:
            self.store.merge_uid_into(existing, request.uid)
            self.store.delete_item(item.id)
            self._push_update()
            return

        rejection = apply_prefilter(
            raw_email,
            sender_allowlist=self._options().get(CONF_SENDER_ALLOWLIST, []),
            keywords=self._options().get(CONF_KEYWORDS, []),
        )
        if rejection is not None:
            self.diagnostics.prefiltered += 1
            # Hard filter: not stored anywhere, not even as a dedup-only
            # record, per PLAN.md section 4.4. A duplicate imap_content
            # event for the same uid will simply be prefiltered again.
            self.store.delete_item(item.id)
            self._push_update()
            return

        ai_task_entity_id = self._options().get(CONF_AI_TASK_ENTITY_ID) or self.entry.data.get(
            CONF_AI_TASK_ENTITY_ID
        )
        if ai_task_entity_id is None or self.hass.states.get(ai_task_entity_id) is None:
            _LOGGER.error(
                "admin_inbox: configured AI Task entity %s is missing; pausing extraction",
                ai_task_entity_id,
            )
            self._async_raise_ai_task_missing(ai_task_entity_id)
            return
        self._async_clear_issue(ISSUE_AI_TASK_ENTITY_MISSING)

        extraction = await async_extract(
            self.hass, raw_email, ai_task_entity_id=ai_task_entity_id
        )
        if isinstance(extraction, ExtractionFailure):
            self.store.mark_terminal_dedup_only(
                item, ItemState.EXTRACTION_FAILED, extraction.reason
            )
            self.diagnostics.extraction_failed += 1
            self._push_update()
            return

        past_years = self._options().get(CONF_DUE_DATE_PAST_YEARS, DEFAULT_DUE_DATE_PAST_YEARS)
        future_years = self._options().get(
            CONF_DUE_DATE_FUTURE_YEARS, DEFAULT_DUE_DATE_FUTURE_YEARS
        )
        validated = validate_extraction(
            extraction, raw_email, past_years=past_years, future_years=future_years
        )
        if isinstance(validated, ValidationRejection):
            reason = f"{validated.field}:{validated.reason}"
            _LOGGER.info("admin_inbox: validation rejected uid %s (%s)", request.uid, reason)
            self.store.mark_terminal_dedup_only(item, ItemState.VALIDATION_REJECTED, reason)
            self.diagnostics.validation_rejected += 1
            self._push_update()
            return

        message_ref = MessageRef(
            entry_id=request.entry_id,
            uid=request.uid,
            message_id=request.message_id,
            subject=raw_email.subject,
            sender=raw_email.sender,
            date=raw_email.date,
        )
        self.store.mark_pending_review(
            item,
            kind=validated.kind,
            title=validated.title,
            counterparty=validated.counterparty,
            amount=validated.amount,
            currency=validated.currency,
            due_date=validated.due_date,
            event_date=validated.event_date,
            confidence=validated.confidence,
            source_quote=validated.source_quote,
            message_ref=message_ref,
            chash=chash,
        )
        self._push_update()

    # -- repair issue helpers ------------------------------------------

    def _async_record_fetch_failure(self) -> None:
        now = dt_util.utcnow()
        self._fetch_failure_times.append(now)
        cutoff = now - _FETCH_FAILURE_WINDOW
        while self._fetch_failure_times and self._fetch_failure_times[0] < cutoff:
            self._fetch_failure_times.popleft()

        threshold = self._options().get(
            CONF_FETCH_FAILURE_THRESHOLD, DEFAULT_FETCH_FAILURE_THRESHOLD
        )
        if len(self._fetch_failure_times) >= threshold:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_IMAP_FETCH_DEGRADED}_{self.entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_IMAP_FETCH_DEGRADED,
                translation_placeholders={"entry_id": self.entry.entry_id},
            )

    def _async_raise_ai_task_missing(self, entity_id: str | None) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_AI_TASK_ENTITY_MISSING}_{self.entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_AI_TASK_ENTITY_MISSING,
            translation_placeholders={"entity_id": entity_id or "none"},
        )

    def _async_clear_issue(self, issue_key: str) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, f"{issue_key}_{self.entry.entry_id}")
