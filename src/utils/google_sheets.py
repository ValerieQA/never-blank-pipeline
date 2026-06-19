import os
import json
from src.utils.logger import get_logger

log = get_logger("google_sheets")

# STUB — implemented in Phase 8 (Reporting)
# Requires: NB_GOOGLE_SHEETS_CREDENTIALS_JSON, NB_GOOGLE_SHEET_ID


def _get_client():
    raise NotImplementedError("Google Sheets client not implemented until Phase 8")


def read_sheet(tab_name: str) -> list[dict]:
    """Read all rows from a named tab. Returns list of dicts (header as keys)."""
    log.warning("google_sheets.read_sheet() is a stub — returning empty list")
    return []


def write_row(tab_name: str, row: dict) -> None:
    """Append a row to a named tab."""
    log.warning("google_sheets.write_row() is a stub — row not written: %s", row)


def update_cell(tab_name: str, row_id: str, col: str, value: str) -> None:
    """Update a single cell identified by row_id and column name."""
    log.warning("google_sheets.update_cell() is a stub — update not applied")
