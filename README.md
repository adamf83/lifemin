# admin_inbox

A Home Assistant custom integration that turns bills, renewals, appointment
confirmations and expiry notices arriving by email into structured, dated
household obligations — gated behind human review before anything becomes
a calendar event.

See [`PLAN.md`](PLAN.md) for the full design: architecture, data model,
prompt-injection defenses, test strategy and milestone breakdown.

## What it does

1. Watches one IMAP mailbox (via the built-in `imap` integration) for new
   mail.
2. Cheaply pre-filters by sender allowlist / keywords before anything is
   sent to a model.
3. Sends the email body to an [AI Task](https://www.home-assistant.io/integrations/ai_task/)
   entity of your choice, with no tools and no LLM API access, asking it
   to extract a bill/renewal/appointment/expiry/statement's kind, title,
   counterparty, amount, date and a verbatim supporting quote.
4. Mechanically re-validates every field of the model's response against
   the original email text — in particular, the quote the model claims
   supports the date/amount must be an exact substring of the email. This
   is the real defense against prompt injection, not the instructions
   given to the model.
5. Puts validated items in a **Needs review** to-do list. Nothing reaches
   your calendar until you check an item off (or reject it).
6. Confirmed items appear on a **Household obligations** calendar, plus
   sensors for the next due date, amount due in the next 30 days, and how
   many items are waiting on your review.

## Installation

This is a HACS **custom repository** for now (not in the default HACS
list).

1. In HACS, go to the three-dot menu → **Custom repositories**.
2. Add this repository's URL, category **Integration**.
3. Install **Admin Inbox**, then restart Home Assistant.

Or, without HACS: copy `custom_components/admin_inbox` into your Home
Assistant `config/custom_components/` directory and restart.

**Minimum Home Assistant version: 2025.12.**

## Setup

Before adding this integration:

1. Set up the **IMAP** integration for the mailbox you want watched.
   Point it at a dedicated folder or label if you can (e.g. a Gmail
   filter that labels bills/renewals/appointments) — the pre-filter
   options below are a second line of defense, not a replacement for
   pointing IMAP at the right folder.
2. Set up an **AI Task**-capable integration (any provider — this
   integration is provider-agnostic and never sends more than the single
   email body being processed).

Then, **Settings → Devices & Services → Add Integration → Admin Inbox**:

1. Pick the IMAP config entry to watch. One Admin Inbox instance watches
   exactly one mailbox — for two mailboxes, add the integration twice.
2. Pick the AI Task entity to use for extraction.
3. Optionally set a sender allowlist (email addresses or `@domain.com`)
   and/or keywords (subject/body substrings or regexes). Leave both
   blank to process everything arriving in the watched mailbox — a
   deliberate "trust the folder" default, since the IMAP folder itself is
   the primary filter.

All of the above, plus retention and reconciliation tuning, can be
changed later from the integration's **Configure** button.

## Using it

- Check the **Needs review** to-do list (`todo.<name>_needs_review`)
  periodically. Each item shows the extracted kind, amount, date,
  confidence and the exact quote the model used — check that quote
  against the source email if anything looks off.
- **Check off** an item to confirm it: it becomes a calendar event on
  **Household obligations** and starts counting toward the "amount due"
  and "next due date" sensors.
- **Delete** an item from the to-do list to reject it (or call
  `admin_inbox.reject_item`).
- An `admin_inbox_item_due` event fires once per confirmed item when its
  date arrives, for automations (e.g. a notification on the day a bill is
  due).

## Privacy

- The full email body is only ever held in memory for the duration of one
  pipeline run. What's persisted to disk is the extracted fields plus a
  short verbatim quote (already validated against the source) and a
  `message_ref` (mailbox/uid/subject/sender/date) to locate the original
  email in your mail client — never the full body.
- The AI Task call has no tools and no LLM API access (`llm_api=None`):
  the model cannot control anything else in your Home Assistant instance
  during extraction, regardless of what's in the email.
- Which provider backs your AI Task entity, and what that provider does
  with the data it receives, is between you and that provider — this
  integration doesn't assume or require any particular one.
- Diagnostics downloads never include email content: no `source_quote`,
  no subject/sender — only counts and state distribution.

## Troubleshooting

- **A repair issue says the AI Task entity is missing**: check the entity
  still exists (Settings → Devices & Services → Entities); if it was
  renamed or its integration reconfigured, update this integration's
  options to point at the new entity.
- **A repair issue says IMAP fetch is degraded**: several email fetches
  failed in the last 24 hours. This is almost always an IMAP-side issue
  (auth, folder permissions, connectivity) — check the IMAP integration's
  own status first.
- **A repair issue says the IMAP account was removed**: the IMAP config
  entry this instance depends on no longer exists. Remove this Admin
  Inbox instance, or restore the IMAP account.
- **Nothing shows up in Needs review**: check the pre-filter isn't too
  strict (an empty allowlist/keyword list processes everything), and that
  the IMAP integration is actually receiving `imap_content` events for
  new mail (check its own logs/diagnostics first).

## Development

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt

ruff check custom_components tests
mypy custom_components/admin_inbox
pytest tests/ -v
```
