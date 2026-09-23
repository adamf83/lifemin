# admin_inbox

A Home Assistant custom integration that turns bills, renewals, appointment
confirmations and expiry notices arriving by email into structured, dated
household obligations — gated behind human review before anything becomes
a calendar event.

See [`PLAN.md`](PLAN.md) for the full design: architecture, data model,
prompt-injection defenses, test strategy and milestone breakdown.

## What it does

1. Watches one mailbox for new mail, via either of two mail sources you
   choose at setup (see [Mail source](#mail-source-imap-or-webhook)
   below):
   - **IMAP** — the built-in `imap` integration, for mailboxes it can log
     into directly.
   - **Webhook** — an external automation with its own access to the
     mailbox pushes new mail to Admin Inbox. Needed for mailboxes IMAP
     can't reach, notably **Microsoft 365 / Exchange Online**.
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

Before adding this integration, set up an **AI Task**-capable integration
(any provider — this integration is provider-agnostic and never sends
more than the single email body being processed). Then decide which mail
source applies to you — see the next section — and complete its
prerequisite (an `imap` config entry, or nothing extra yet for webhook).

Then, **Settings → Devices & Services → Add Integration → Admin Inbox**:

1. Choose the mail source: **IMAP** or **Webhook**.
2. **IMAP** → pick the IMAP config entry to watch. **Webhook** → nothing
   to pick here; a webhook URL is generated and shown to you at the end
   of the flow (see below for how to wire it up).
3. Pick the AI Task entity to use for extraction.
4. Optionally set a sender allowlist (email addresses or `@domain.com`)
   and/or keywords (subject/body substrings or regexes). Leave both
   blank to process everything arriving — a deliberate "trust the source"
   default, since for IMAP the mailbox folder is the primary filter, and
   for webhook it's whatever the external automation already decided to
   forward.

One Admin Inbox instance watches exactly one mail source — for two
mailboxes, or a mix of IMAP and webhook, add the integration again for
each. All of the above, plus retention and reconciliation tuning, can be
changed later from the integration's **Configure** button (the mail
source itself is fixed at setup — remove and re-add to change it).

## Mail source: IMAP or webhook?

**Use IMAP** if your mailbox is one the built-in `imap` integration can
log into with a username and password (or app password) — most personal
IMAP providers (Fastmail, most self-hosted mail, Gmail with an app
password). Set up the **IMAP** integration first, pointed at a dedicated
folder or label if you can (e.g. a filter that labels bills/renewals/
appointments) — Admin Inbox's own allowlist/keyword filters are a second
line of defense, not a replacement for pointing IMAP at the right folder.

**Use Webhook** if IMAP login simply doesn't work for your mailbox — the
main case is **Microsoft 365 / Exchange Online**, which retired
Basic Auth (username+password) for IMAP entirely; HA's `imap` integration
has no OAuth2/Modern Auth support, so there's no configuration fix for
this — the mailbox is just unreachable over IMAP. The webhook source
sidesteps it: an external automation with its own (OAuth-based) access to
the mailbox pushes new mail to a URL Admin Inbox generates for you.

### Wiring up Microsoft 365 via Power Automate

This is the reference setup for the webhook source, using a first-party
Microsoft tool that already has proper OAuth access to your mailbox —
no app registration or token management needed on your end.

1. In [Power Automate](https://make.powerautomate.com), create an
   **Automated cloud flow**.
2. Trigger: **Office 365 Outlook — When a new email arrives (V3)**.
   Point it at the folder you want watched, same reasoning as the IMAP
   folder advice above.
3. (Optional but recommended) Add a **Html to text** action on the
   trigger's `Body` output — extraction works better on plain text than
   raw HTML.
4. Add an **HTTP** action:
   - Method: `POST`
   - URI: the webhook URL Admin Inbox showed you at the end of its config
     flow. Lost it? It's shown again (read-only) at the top of the
     integration's **Configure** screen — it doesn't change.
   - Headers: `Content-Type: application/json`
   - Body:
     ```json
     {
       "message_id": "@{triggerOutputs()?['body/Id']}",
       "sender": "@{triggerOutputs()?['body/From']}",
       "subject": "@{triggerOutputs()?['body/Subject']}",
       "date": "@{triggerOutputs()?['body/DateTimeReceived']}",
       "text": "@{body('Html_to_text')}"
     }
     ```
     (swap the last line for `"text": "@{triggerOutputs()?['body/Body']}"` if
     you skipped the Html-to-text step)
5. Save and turn the flow on. `message_id` is required — Admin Inbox uses
   it to deduplicate, and rejects (HTTP 400) any request missing it.

Home Assistant must be reachable from Microsoft's cloud for this to work
(Nabu Casa remote access or your own reverse proxy/port-forward with a
valid certificate — a purely local-only HA instance can't receive this).

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
- **A repair issue says IMAP fetch is degraded** (IMAP source only):
  several email fetches failed in the last 24 hours. This is almost
  always an IMAP-side issue (auth, folder permissions, connectivity) —
  check the IMAP integration's own status first.
- **A repair issue says the IMAP account was removed** (IMAP source
  only): the IMAP config entry this instance depends on no longer exists.
  Remove this Admin Inbox instance, or restore the IMAP account.
- **Nothing shows up in Needs review, IMAP source**: check the pre-filter
  isn't too strict (an empty allowlist/keyword list processes
  everything), and that the IMAP integration is actually receiving
  `imap_content` events for new mail (check its own logs/diagnostics
  first).
- **Nothing shows up in Needs review, webhook source**: check the
  external automation is actually running (Power Automate's flow run
  history shows every trigger and HTTP call, including failures) and
  that the HTTP action got a `200` back — a `400` means the JSON body was
  malformed or missing `message_id`; anything else (timeout, connection
  refused) usually means Home Assistant isn't reachable from outside your
  network.

## Development

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt

ruff check custom_components tests
mypy custom_components/admin_inbox
pytest tests/ -v
```
