"""
Integration test for Google Drive package upload.

Creates a minimal synthetic content package, uploads it to Drive,
appends a manifest entry, then verifies the result.

Run: python scripts/test_drive_upload.py
Requires: NB_GOOGLE_SHEETS_CREDENTIALS_JSON, NB_GOOGLE_DRIVE_PACKAGES_FOLDER_ID
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.google_drive import upload_package
from src.utils.logger import get_logger

log = get_logger("test_drive_upload")

PACKAGES_DIR  = Path("reports/content_packages")
MANIFEST_FILE = Path("data/research/packages_manifest.jsonl")
TEST_SIGNAL_ID = "test_drive_integration_check"


def run_test() -> bool:
    folder_id = os.environ.get("NB_GOOGLE_DRIVE_PACKAGES_FOLDER_ID", "").strip()
    creds_set = bool(os.environ.get("NB_GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip())

    print(f"NB_GOOGLE_DRIVE_PACKAGES_FOLDER_ID: {'set (' + folder_id[:8] + '...)' if folder_id else 'MISSING'}")
    print(f"NB_GOOGLE_SHEETS_CREDENTIALS_JSON:  {'set' if creds_set else 'MISSING'}")

    if not folder_id or not creds_set:
        print("FAIL: required env vars not set")
        return False

    # 1. Create a minimal synthetic package
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    pkg_path = PACKAGES_DIR / f"{TEST_SIGNAL_ID}.json"
    package = {
        "SIGNAL_ID":   TEST_SIGNAL_ID,
        "HEADLINE":    "Drive integration test — safe to delete",
        "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "content":     {"blog": {"headline": "test", "angle": "test"}},
        "images":      {},
    }
    pkg_path.write_text(json.dumps(package, indent=2))
    print(f"Created test package: {pkg_path}")

    # 2. Upload to Drive
    try:
        file_id, web_url = upload_package(pkg_path)
    except Exception as exc:
        print(f"FAIL: Drive upload raised exception: {exc}")
        return False

    if not file_id:
        print("FAIL: upload returned empty file_id")
        return False

    print(f"OK: uploaded to Drive")
    print(f"   file_id = {file_id}")
    print(f"   url     = {web_url}")

    # 3. Write manifest entry
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "signal_id":     TEST_SIGNAL_ID,
        "headline":      package["HEADLINE"],
        "generated_at":  package["prepared_at"],
        "drive_file_id": file_id,
        "drive_url":     web_url,
        "status":        "test",
    }
    with open(MANIFEST_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"OK: manifest entry written to {MANIFEST_FILE}")

    # 4. Verify manifest is readable
    lines = MANIFEST_FILE.read_text().strip().splitlines()
    last = json.loads(lines[-1])
    assert last["signal_id"] == TEST_SIGNAL_ID, "manifest last entry mismatch"
    assert last["drive_file_id"] == file_id, "manifest file_id mismatch"
    print(f"OK: manifest verified ({len(lines)} total entries)")

    # Clean up test package from local disk
    pkg_path.unlink()
    print(f"Cleaned up local test file. Drive copy remains at: {web_url}")

    print("\nALL CHECKS PASSED — Drive upload integration is working.")
    return True


if __name__ == "__main__":
    ok = run_test()
    sys.exit(0 if ok else 1)
