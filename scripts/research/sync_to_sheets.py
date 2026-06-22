"""
Stage 7 — Google Sheets sync (write).
Writes active signals to research sheet. Failure is non-fatal.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger

log = get_logger("research.sync_to_sheets")

ACTIVE_FILE = Path("data/research/signals_active.jsonl")


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


def _read_active_signals() -> list[dict]:
    if not ACTIVE_FILE.exists():
        return []
    signals = []
    with open(ACTIVE_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return signals


def sync_to_sheets() -> bool:
    try:
        signals = _read_active_signals()
        if not signals:
            log.info("No active signals to sync")
            return True

        sid = os.environ.get("NB_RESEARCH_SHEET_ID", "")
        if not sid:
            log.warning("NB_RESEARCH_SHEET_ID not set — skipping sync")
            return False

        tab     = os.environ.get("NB_RESEARCH_SHEET_TAB", "Signals")
        service = _get_service()

        all_keys: list[str] = []
        seen_keys: set[str] = set()
        for s in signals:
            for k in s:
                if k not in seen_keys and not k.startswith("_"):
                    all_keys.append(k)
                    seen_keys.add(k)

        meta = service.spreadsheets().get(spreadsheetId=sid).execute()
        existing_tabs = [sh["properties"]["title"] for sh in meta.get("sheets", [])]
        if tab not in existing_tabs:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sid,
                body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
            ).execute()

        rows = [all_keys]
        for s in signals:
            row = [str(s.get(k, "") or "") for k in all_keys]
            rows.append(row)

        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

        log.info("Synced %d signals to Sheets tab '%s'", len(signals), tab)
        return True

    except Exception as exc:
        log.warning("Sheets sync failed (non-fatal): %s", exc)
        return False


if __name__ == "__main__":
    ok = sync_to_sheets()
    sys.exit(0 if ok else 1)
