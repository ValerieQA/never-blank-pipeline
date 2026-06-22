"""
Stage 8 — Narrow pull-back from Google Sheets.
Only pulls NOTES, APPROVED_OVERRIDE, and angle overrides.
JSONL is source of truth.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger

log = get_logger("research.sync_from_sheets")

ACTIVE_FILE    = Path("data/research/signals_active.jsonl")
ALLOWED_FIELDS = {"NOTES", "APPROVED_OVERRIDE", "LINKEDIN_ANGLE", "BLOG_ANGLE", "THREADS_ANGLE", "STORY_ANGLE"}


def _get_creds():
    import json as _json
    import google.oauth2.service_account as sa
    raw = os.environ.get("NB_GOOGLE_SERVICE_ACCOUNT_JSON") or os.environ.get("NB_GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    if not raw:
        raise EnvironmentError("NB_GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = _json.loads(raw) if raw.strip().startswith("{") else _json.load(open(raw))
    return sa.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])


def _get_service():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=_get_creds(), cache_discovery=False)


def pull_edits_from_sheets() -> int:
    if not ACTIVE_FILE.exists():
        return 0

    try:
        sid = os.environ.get("NB_RESEARCH_SHEET_ID", "")
        if not sid:
            log.warning("NB_RESEARCH_SHEET_ID not set — skipping pull")
            return 0

        tab     = os.environ.get("NB_RESEARCH_SHEET_TAB", "Signals")
        service = _get_service()
        result  = service.spreadsheets().values().get(
            spreadsheetId=sid,
            range=f"'{tab}'",
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return 0

        headers     = rows[0]
        sheet_by_id = {}
        for row in rows[1:]:
            row_dict = dict(zip(headers, row + [""] * (len(headers) - len(row))))
            sig_id   = row_dict.get("SIGNAL_ID", "")
            if sig_id:
                sheet_by_id[sig_id] = row_dict

    except Exception as exc:
        log.warning("Sheets pull failed: %s", exc)
        return 0

    signals = []
    with open(ACTIVE_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    updated = 0
    for sig in signals:
        sheet_row = sheet_by_id.get(sig.get("SIGNAL_ID", ""))
        if not sheet_row:
            continue
        for field in ALLOWED_FIELDS:
            sheet_val = sheet_row.get(field, "").strip()
            if sheet_val and sheet_val != sig.get(field, ""):
                sig[field] = sheet_val
                updated += 1

    with open(ACTIVE_FILE, "w") as f:
        for sig in signals:
            f.write(json.dumps(sig, ensure_ascii=False) + "\n")

    log.info("Pulled %d field updates from Sheets", updated)
    return updated


if __name__ == "__main__":
    n = pull_edits_from_sheets()
    print(f"Updated {n} fields from Sheets")
