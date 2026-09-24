"""Bridges a service-call file upload into a media_source identifier.

ai_task's `attachments` parameter only resolves `media-source://` identifiers
(or a camera/image entity snapshot) -- not raw bytes or an arbitrary local
path (see homeassistant/components/ai_task/task.py's _resolve_attachments).
So a file uploaded via the admin_inbox.upload_document service has to be
copied into a local media_source directory before it can be handed to
async_generate_data. See PLAN.md section 1b.
"""
from __future__ import annotations

import logging
import mimetypes
import shutil
from pathlib import Path

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.core import HomeAssistant
from homeassistant.util import raise_if_invalid_filename
from homeassistant.util.ulid import ulid_now

from .const import UPLOAD_ALLOWED_CONTENT_TYPES, UPLOAD_MAX_SIZE_BYTES

_LOGGER = logging.getLogger(__name__)

MEDIA_SUBDIR = "admin_inbox"


class UploadRejected(Exception):
    """Raised when an uploaded file fails MIME/size validation."""


def _guess_content_type(filename: str) -> str:
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or "application/octet-stream"


def _blocking_store(hass: HomeAssistant, entry_id: str, file_id: str) -> str:
    """Validate and copy the uploaded file; returns the new filename.

    Runs in the executor: process_uploaded_file does blocking filesystem
    I/O, and so does the copy. Raises UploadRejected or ValueError (an
    unknown file_id, from process_uploaded_file itself) on failure.
    """
    with process_uploaded_file(hass, file_id) as temp_path:
        content_type = _guess_content_type(temp_path.name)
        if content_type not in UPLOAD_ALLOWED_CONTENT_TYPES:
            raise UploadRejected(f"unsupported content type: {content_type}")

        size = temp_path.stat().st_size
        if size > UPLOAD_MAX_SIZE_BYTES:
            raise UploadRejected(f"file too large: {size} bytes (max {UPLOAD_MAX_SIZE_BYTES})")

        extension = temp_path.suffix or (mimetypes.guess_extension(content_type) or "")
        filename = f"{ulid_now()}{extension}"
        raise_if_invalid_filename(filename)

        media_dir = Path(hass.config.path("media", MEDIA_SUBDIR, entry_id))
        media_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(temp_path, media_dir / filename)

    return filename


async def async_store_uploaded_file(hass: HomeAssistant, entry_id: str, file_id: str) -> str:
    """Move an uploaded file into local media storage; return its media_content_id.

    Raises UploadRejected if the file fails MIME/size validation, or
    ValueError if file_id doesn't correspond to an in-progress upload.
    """
    filename = await hass.async_add_executor_job(_blocking_store, hass, entry_id, file_id)
    return f"media-source://media_source/local/{MEDIA_SUBDIR}/{entry_id}/{filename}"
