"""
Google Drive utility — uploads files to a configured folder.

Required env:
  NB_GOOGLE_SHEETS_CREDENTIALS_JSON — service account JSON (same creds as Sheets)
  NB_GOOGLE_DRIVE_PACKAGES_FOLDER_ID — Drive folder ID where packages are stored

The service account must have Editor access to the target folder.
Share the folder with the service account email (visible in the JSON under "client_email").
"""

import json
import os
from pathlib import Path

from src.utils.logger import get_logger

log = get_logger("google_drive")


def _get_drive_creds():
    raw = os.environ.get("NB_GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    if not raw:
        raise EnvironmentError("NB_GOOGLE_SHEETS_CREDENTIALS_JSON is not set")

    import google.oauth2.service_account as sa

    info = json.loads(raw) if raw.strip().startswith("{") else json.load(open(raw))
    return sa.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )


def _get_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_drive_creds(), cache_discovery=False)


def upload_file(
    local_path: Path,
    folder_id: str,
    mime_type: str = "application/json",
) -> tuple[str, str]:
    """
    Upload local_path to Drive folder_id.
    Returns (file_id, web_view_link).
    Raises on failure — caller decides whether to hard-fail or warn.
    """
    from googleapiclient.http import MediaFileUpload

    service = _get_drive_service()
    name = local_path.name

    # Check if a file with this name already exists in the folder and update it.
    existing = (
        service.files()
        .list(
            q=f"name='{name}' and '{folder_id}' in parents and trashed=false",
            fields="files(id,webViewLink)",
            spaces="drive",
        )
        .execute()
        .get("files", [])
    )

    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)

    if existing:
        file_id = existing[0]["id"]
        updated = (
            service.files()
            .update(fileId=file_id, media_body=media, fields="id,webViewLink")
            .execute()
        )
        log.info("drive: updated %s → id=%s", name, file_id)
        return updated["id"], updated.get("webViewLink", "")

    metadata = {"name": name, "parents": [folder_id]}
    created = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,webViewLink")
        .execute()
    )
    log.info("drive: uploaded %s → id=%s", name, created["id"])
    return created["id"], created.get("webViewLink", "")


def upload_package(local_path: Path) -> tuple[str, str]:
    """
    Upload a content package JSON to the configured packages folder.
    Returns (file_id, web_view_link). Returns ("", "") if folder ID is not configured.
    """
    folder_id = os.environ.get("NB_GOOGLE_DRIVE_PACKAGES_FOLDER_ID", "").strip()
    if not folder_id:
        log.warning(
            "drive: NB_GOOGLE_DRIVE_PACKAGES_FOLDER_ID is not set — skipping Drive upload for %s",
            local_path.name,
        )
        return "", ""
    return upload_file(local_path, folder_id)
