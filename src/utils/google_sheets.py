"""
Google Sheets utility — reads and writes to the Never Blank tracking sheet.

Requires:
  NB_GOOGLE_SHEETS_CREDENTIALS_JSON — path to service account JSON OR JSON string
  NB_GOOGLE_SHEET_ID                — spreadsheet ID from URL

Tabs used:
  Content Matrix — one row per published topic
"""

import json
import os
from typing import Optional

from src.utils.logger import get_logger

log = get_logger("google_sheets")

CONTENT_MATRIX_TAB = "Content Matrix"
CONTENT_MATRIX_HEADERS = [
    "topic_id", "topic", "core_idea", "observation", "mechanism",
    "cost_of_ignoring", "strategic_question", "hook_type", "primary_hook",
    "visual_anchor", "sales_angle", "soft_cta",
    "linkedin_angle", "instagram_angle", "facebook_angle",
    "threads_angle", "telegram_angle", "stories_flow",
    "status", "created_at", "published_at",
]


def _get_creds():
    """Load Google service account credentials."""
    raw = os.environ.get("NB_GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    if not raw:
        raise EnvironmentError("NB_GOOGLE_SHEETS_CREDENTIALS_JSON is not set")

    import google.oauth2.service_account as sa

    if raw.strip().startswith("{"):
        info = json.loads(raw)
    else:
        with open(raw) as f:
            info = json.load(f)

    return sa.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )


def _get_service():
    """Return a Google Sheets API service object."""
    from googleapiclient.discovery import build
    creds = _get_creds()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _sheet_id() -> str:
    sid = os.environ.get("NB_GOOGLE_SHEET_ID", "")
    if not sid:
        raise EnvironmentError("NB_GOOGLE_SHEET_ID is not set")
    return sid


def _ensure_tab(service, tab_name: str, headers: list[str]) -> None:
    """Ensure tab exists. If not, create it and write the header row."""
    sid  = _sheet_id()
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    existing = [s["properties"]["title"] for s in meta.get("sheets", [])]

    if tab_name not in existing:
        log.info("Creating tab: %s", tab_name)
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()
    else:
        result = service.spreadsheets().values().get(
            spreadsheetId=sid,
            range=f"'{tab_name}'!A1:Z1",
        ).execute()
        if not result.get("values"):
            service.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"'{tab_name}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()


def _find_row_by_topic_id(service, tab_name: str, topic_id: str) -> Optional[int]:
    """Return 1-based row number for topic_id, or None."""
    sid = _sheet_id()
    result = service.spreadsheets().values().get(
        spreadsheetId=sid,
        range=f"'{tab_name}'!A:A",
    ).execute()
    for i, row in enumerate(result.get("values", [])):
        if row and row[0] == topic_id:
            return i + 1
    return None


def read_sheet(tab_name: str) -> list[dict]:
    """Read all rows from a named tab. Returns list of dicts (header as keys)."""
    try:
        service = _get_service()
        sid     = _sheet_id()
        result  = service.spreadsheets().values().get(
            spreadsheetId=sid,
            range=f"'{tab_name}'",
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return []
        headers = rows[0]
        return [
            dict(zip(headers, row + [""] * (len(headers) - len(row))))
            for row in rows[1:]
        ]
    except Exception as exc:
        log.warning("read_sheet('%s') failed: %s", tab_name, exc)
        return []


def write_row(tab_name: str, row: dict) -> None:
    """Append a row to a named tab."""
    try:
        service = _get_service()
        _ensure_tab(service, tab_name, list(row.keys()))
        service.spreadsheets().values().append(
            spreadsheetId=sid := _sheet_id(),
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [list(row.values())]},
        ).execute()
    except Exception as exc:
        log.warning("write_row('%s') failed: %s", tab_name, exc)


def update_cell(tab_name: str, row_id: str, col: str, value: str) -> None:
    """Update a single cell identified by topic_id and column name."""
    try:
        service = _get_service()
        _ensure_tab(service, tab_name, CONTENT_MATRIX_HEADERS)
        row_num = _find_row_by_topic_id(service, tab_name, row_id)
        if row_num is None:
            log.warning("update_cell: topic_id '%s' not found in '%s'", row_id, tab_name)
            return

        sid    = _sheet_id()
        result = service.spreadsheets().values().get(
            spreadsheetId=sid,
            range=f"'{tab_name}'!1:1",
        ).execute()
        headers = result.get("values", [[]])[0]
        try:
            col_idx = headers.index(col)
        except ValueError:
            log.warning("update_cell: column '%s' not found", col)
            return

        col_letter = chr(ord("A") + col_idx)
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"'{tab_name}'!{col_letter}{row_num}",
            valueInputOption="RAW",
            body={"values": [[value]]},
        ).execute()
    except Exception as exc:
        log.warning("update_cell() failed: %s", exc)


def write_content_matrix_row(matrix_dict: dict, status: str = "draft") -> bool:
    """
    Write or update a Content Matrix row in the Google Sheet.
    Matches on topic_id — updates if exists, appends if new.
    Returns True on success, False on failure.
    """
    try:
        from datetime import datetime, timezone
        service = _get_service()
        _ensure_tab(service, CONTENT_MATRIX_TAB, CONTENT_MATRIX_HEADERS)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        row: dict[str, str] = {h: "" for h in CONTENT_MATRIX_HEADERS}
        for key in CONTENT_MATRIX_HEADERS:
            val = matrix_dict.get(key, "")
            if isinstance(val, list):
                val = " | ".join(str(v) for v in val)
            row[key] = str(val) if val else ""
        row["status"]       = status
        row["created_at"]   = matrix_dict.get("created_at", now)
        row["published_at"] = ""

        sid     = _sheet_id()
        values  = [row[h] for h in CONTENT_MATRIX_HEADERS]
        row_num = _find_row_by_topic_id(service, CONTENT_MATRIX_TAB, matrix_dict.get("topic_id", ""))

        if row_num:
            service.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"'{CONTENT_MATRIX_TAB}'!A{row_num}",
                valueInputOption="RAW",
                body={"values": [values]},
            ).execute()
            log.info("Content Matrix updated: topic_id=%s row=%d", matrix_dict.get("topic_id"), row_num)
        else:
            service.spreadsheets().values().append(
                spreadsheetId=sid,
                range=f"'{CONTENT_MATRIX_TAB}'!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [values]},
            ).execute()
            log.info("Content Matrix appended: topic_id=%s", matrix_dict.get("topic_id"))

        return True

    except Exception as exc:
        log.warning("write_content_matrix_row() failed: %s", exc)
        return False
