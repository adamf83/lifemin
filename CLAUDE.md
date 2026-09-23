# CLAUDE.md

Pointers for future Claude Code sessions working on this repo.

## What this is

`custom_components/admin_inbox` — a Home Assistant custom integration.
See `PLAN.md` for the full design (architecture, data model, prompt-injection
defenses, milestones) and `README.md` for user-facing install/setup docs.

## Running tests locally

HA's current releases (2026.x) require Python 3.13+; this sandbox's default
`python3` is 3.11, so the venv here was built with `python3.13`.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
ruff check custom_components tests
mypy custom_components/admin_inbox
pytest tests/ -v
```

`.venv/` is gitignored; recreate it rather than committing it.

## Things that are easy to get wrong here (already hit these once)

- **`ai_task.async_generate_data`'s `structure` parameter expects an
  already-built `vol.Schema`**, not the raw
  `{field: {selector, description, required}}` dict. That raw-dict form is
  only auto-converted by the `ai_task.generate_data` *service's* call
  schema (`STRUCTURE_FIELD_SCHEMA`/`_validate_structure_fields` in
  `homeassistant/components/ai_task/__init__.py`), which doesn't run when
  you call `async_generate_data` directly from Python. `extractor.py`
  builds its own `vol.Schema` via `_build_structure_schema` — don't revert
  to passing the raw dict.
- **`AdminInboxStore.delete_item`** must only pop a uid from `_uid_index`
  if that uid still points at the item being deleted — a uid can have been
  reassigned to a different item via `merge_uid_into` (content-hash merge)
  before the placeholder item that originally reserved it gets deleted.
  Got this wrong once; there's a regression test in `test_store.py`
  (`test_content_hash_merge_across_different_uids`) guarding it.
- **Testing against a real `ai_task` entity** requires setting up the
  `homeassistant` component first (`async_setup_component(hass,
  "homeassistant", {})`) before `ai_task`, or `conversation`'s setup fails
  with a `KeyError` on `homeassistant.exposed_entities`. See
  `tests/conftest.py::async_setup_fake_ai_task`.
- **A fake `ai_task` platform entity** needs a real config entry with a
  registered `ConfigFlow` handler behind it (HA's config-entry setup path
  always imports `<domain>.config_flow` and checks `HANDLERS`), not just a
  `MockPlatform` for the entity platform itself. See the same fixture.
- **`imap.fetch`'s service response fields are loosely typed**
  (`JsonValueType`) — coerce explicitly (`str(...)`, `isinstance` checks
  for `parts`) rather than assuming `str`/`list`, or mypy (and a real
  malformed response) will break `fetcher.py`.

## Test structure

Per-stage unit tests (`test_prefilter.py`, `test_extractor.py`,
`test_validator.py`, `test_store.py`) exercise one module directly with
constructed objects. `test_pipeline.py` is the IMAP-source end-to-end test
(fires a real `imap_content` event through the full stack into a `todo`
item); `test_webhook.py` is its webhook-source counterpart (POSTs to the
registered webhook via the `hass_client_no_auth` fixture instead).
`test_config_flow.py`, `test_calendar.py`, `test_todo.py`, `test_sensor.py`,
`test_repairs.py` are entity/flow-level tests. `tests/helpers.py` holds
shared setup helpers used by the entity-rendering tests
(`async_setup_admin_inbox` for IMAP source, `async_setup_admin_inbox_webhook`
for webhook source); `tests/conftest.py` holds the `FakeAITaskEntity` and
mock-IMAP-entry fixtures used everywhere.

## Mail source: IMAP vs webhook

There are two mail sources, chosen once at config-flow time
(`CONF_SOURCE_TYPE`, `imap` | `webhook`) and never changed in place — see
`PLAN.md` section 1a for the full rationale (Microsoft 365 retired Basic
Auth IMAP, which is all HA's core `imap` integration supports).

- `listener.py` (IMAP: subscribes to `imap_content` bus events) and
  `webhook_listener.py` (webhook: registers a HA webhook, parses the
  POSTed JSON body) are the two entry points. Both end up calling into
  `pipeline.py`: `async_handle_fetch_request` (IMAP, fetches the body via
  `imap.fetch` first) or `async_handle_pushed_email` (webhook, body
  already provided). Both converge on the same
  `pipeline._async_process_fetched` (prefilter → extract → validate →
  review queue) — don't duplicate that logic when touching either path.
- `__init__.py`'s `async_setup_entry` branches on `CONF_SOURCE_TYPE` to
  decide which of `listener`/`webhook_id` on `AdminInboxRuntimeData` gets
  set (the other stays `None`) — don't assume `runtime_data.listener` is
  always present.
- Reconciliation (`pipeline.async_reconcile`) only retries IMAP-sourced
  stuck items (it can re-fetch a uid); a stuck webhook-sourced item has no
  payload to retry with and is marked terminal instead.
- `repairs.async_check_imap_entry` is a no-op for webhook-sourced entries.
- The webhook URL is only shown to the user twice: once at the end of the
  config flow (`webhook_confirm` step), and persistently in the options
  flow's `init` step description. Don't add a third mechanism without
  checking whether one of these already covers the need.
