"""Shared fixtures for admin_inbox tests."""
from __future__ import annotations

import pathlib

import pytest
from homeassistant.components.ai_task import AITaskEntity, AITaskEntityFeature, GenDataTaskResult
from homeassistant.config_entries import ConfigEntryState, ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    Mock,
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "emails"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def load_fixture_email(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


class FakeAITaskEntity(AITaskEntity):
    """Returns pre-programmed responses; never calls a real provider."""

    _attr_name = "Fake AI Task"
    _attr_unique_id = "fake_ai_task"

    def __init__(self, responses: list, *, supports_attachments: bool = False) -> None:
        self._responses = responses
        self.instructions_seen: list[str] = []
        self.attachments_seen: list[list | None] = []
        features = AITaskEntityFeature.GENERATE_DATA
        if supports_attachments:
            features |= AITaskEntityFeature.SUPPORT_ATTACHMENTS
        self._attr_supported_features = features

    async def _async_generate_data(self, task, chat_log):
        self.instructions_seen.append(task.instructions)
        self.attachments_seen.append(task.attachments)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return GenDataTaskResult(conversation_id=chat_log.conversation_id, data=response)


async def async_setup_fake_ai_task(
    hass: HomeAssistant, responses: list, *, supports_attachments: bool = False
) -> str:
    """Set up a real ai_task entity backed by FakeAITaskEntity, return its entity_id."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "ai_task", {})

    fake_entity = FakeAITaskEntity(responses, supports_attachments=supports_attachments)

    async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, ["ai_task"])
        return True

    async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
        return await hass.config_entries.async_unload_platforms(entry, ["ai_task"])

    mock_integration(
        hass,
        MockModule(
            domain="fake_ai_task_provider",
            async_setup_entry=async_setup_entry,
            async_unload_entry=async_unload_entry,
        ),
    )

    async def async_setup_entry_platform(hass, config_entry, async_add_entities):
        async_add_entities([fake_entity])

    mock_platform(
        hass,
        "fake_ai_task_provider.ai_task",
        MockPlatform(async_setup_entry=async_setup_entry_platform),
    )
    mock_platform(hass, "fake_ai_task_provider.config_flow", Mock())

    class _FakeAITaskProviderFlow(ConfigFlow, domain="fake_ai_task_provider"):
        pass

    entry = MockConfigEntry(domain="fake_ai_task_provider")
    entry.add_to_hass(hass)
    with mock_config_flow("fake_ai_task_provider", _FakeAITaskProviderFlow):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_ids = hass.states.async_entity_ids("ai_task")
    assert entity_ids, "fake ai_task entity did not register"
    return entity_ids[0]


def add_mock_imap_entry(hass: HomeAssistant, entry_id: str = "imap_test_entry") -> MockConfigEntry:
    entry = MockConfigEntry(domain="imap", title="Mail Test", data={}, entry_id=entry_id)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


async def async_create_local_media_file(
    hass: HomeAssistant, *, subpath: str, content: bytes = b"fake image bytes"
) -> str:
    """Write a real file under the local media_source root; return its media_content_id.

    Bypasses the file_upload HTTP layer (that's exercised separately in
    test_upload_document.py) -- this is for tests that just need a
    resolvable media-source:// identifier, e.g. extractor.py's attachments
    passthrough.
    """
    assert await async_setup_component(hass, "media_source", {})

    def _write() -> None:
        path = pathlib.Path(hass.config.path("media", subpath))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    await hass.async_add_executor_job(_write)
    return f"media-source://media_source/local/{subpath}"
