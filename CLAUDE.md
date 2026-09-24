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
registered webhook via the `hass_client_no_auth` fixture instead);
`test_upload_document.py` is the manual-upload counterpart (POSTs a real
file to `/api/file_upload` via the authenticated `hass_client` fixture,
then calls the service).
`test_config_flow.py`, `test_calendar.py`, `test_todo.py`, `test_sensor.py`,
`test_repairs.py` are entity/flow-level tests. `tests/helpers.py` holds
shared setup helpers used by the entity-rendering tests
(`async_setup_admin_inbox` for IMAP source, `async_setup_admin_inbox_webhook`
for webhook source); `tests/conftest.py` holds the `FakeAITaskEntity`
(pass `supports_attachments=True` to `async_setup_fake_ai_task` for
upload/attachment tests), `async_create_local_media_file` (a resolvable
`media-source://` identifier without going through the upload HTTP layer),
and mock-IMAP-entry fixtures used everywhere.

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

## Manual upload (admin_inbox.upload_document)

A third entry point, orthogonal to the mail source above (works
regardless of whether the entry is IMAP- or webhook-sourced) — see
`PLAN.md` section 1b for the rationale (Power Automate's HTTP action is a
Premium-licensed connector, so the webhook path isn't available to
everyone either).

- `uploads.py`'s `async_store_uploaded_file` bridges a
  `file_upload`-uploaded file into a `media-source://` identifier
  (`ai_task`'s `attachments` param only resolves those, or a camera/image
  entity snapshot -- never raw bytes or an arbitrary path). It copies the
  file into `admin_inbox/<entry_id>/` under `hass.config.media_dirs["local"]`
  -- **not** `hass.config.path("media")`. Those two are only the same path
  off Docker; on Docker/HAOS/Supervised installs (the common case)
  `media_dirs["local"]` defaults to the fixed path `/media` instead (see
  `core_config.py`). Writing to `hass.config.path("media")` directly
  shipped once, passed every test (this sandbox isn't a Docker env, so
  `hass.config.media_dirs["local"]` happened to equal
  `hass.config.path("media")` here), and broke for a real user with a
  "does not exist" error from `ai_task`'s attachment resolution --
  `test_upload_document_respects_configured_local_media_root` pins
  `hass.config.media_dirs` to a directory that deliberately isn't
  `hass.config.path("media")` specifically to catch a regression back to
  that. The copy also **does not delete the file afterwards** (unlike
  `process_uploaded_file`'s own temp copy, which is single-use and
  auto-deleted) -- that's intentional (the AI Task call needs the file to
  still exist when it resolves the attachment, asynchronously, after this
  function returns) but means storage grows unbounded; there's no cleanup
  job for it yet.
- `pipeline.async_handle_uploaded_document` calls the same
  `_async_process_fetched` the IMAP/webhook paths use, with three flags
  set for upload-specific behavior: `skip_prefilter=True`,
  `check_content_hash=False` (see the content-hash collision risk noted
  in `_async_process_fetched`'s docstring/PLAN.md 1b if you're tempted to
  turn this back on), `verify_source_quote=False`. If you add a fourth
  entry point, prefer adding another flag over copy-pasting the method.
- `validator.validate_extraction`'s `verify_source_quote=False` path
  still requires `source_quote` to be present and non-empty after
  whitespace normalization -- it only skips checking it's a substring of
  `raw_email.text`. Don't relax this further without re-reading PLAN.md
  1b's reasoning for why it's already a weaker check than the email path.
- Testing an upload end-to-end needs `supports_attachments=True` passed to
  `async_setup_fake_ai_task` (the real `async_generate_data` rejects
  attachments otherwise via `AITaskEntityFeature.SUPPORT_ATTACHMENTS`),
  and a real POST to `/api/file_upload` through the authenticated
  `hass_client` fixture (not `hass_client_no_auth` -- that endpoint
  requires auth, unlike the webhook view) to get a real `file_id`. See
  `test_upload_document.py`.

## Service field selectors

`entry_id` on all four `admin_inbox.*` services uses
`selector.config_entry(integration: admin_inbox)` in `services.yaml`, not
a plain text field -- it renders as a dropdown of this integration's
instances by title in the frontend (Developer Tools -> Actions), so users
never need to look up or type a raw config entry id. Don't revert this to
`selector.text` (that was the original design and a real user complained
they couldn't find the id anywhere). The Python-side schema
(`UPLOAD_DOCUMENT_SCHEMA` etc. in `__init__.py`) still validates it as a
plain `cv.string` -- only the YAML-declared selector (UI widget) changed,
the submitted value is unchanged. Similarly, `todo.py`'s
`_todo_item_from_stored` prints `Item ID: {item.id}` at the end of each
to-do item's description specifically so `confirm_item`/`reject_item`
are usable from a script -- don't remove that line, since there's no
selector type for "pick a to-do item" to replace it with.
