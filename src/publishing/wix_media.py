"""
Wix Media importer for Never Blank.

Imports an external image (Cloudinary URL) into Wix Media Manager
and returns a WixMediaAsset with the Wix-native file ID.

That file ID is then used in the blog draft payload — Wix Blog v3
does not accept raw external URLs as cover media; it requires a
Wix Media Manager reference.

API:
  POST https://www.wixapis.com/site-media/v1/files/import

Response normalization:
  Wix may return the ID as "id" or "fileId", and the URL as "url" or "fileUrl".
  Both variants are handled. A 2xx response without a file ID is treated as
  an import failure — there is no silent fallback to the source URL.

Errors:
  WixMediaImportError — raised when import fails for any reason.
  Callers (WixPublisher) must catch this and mark the Wix channel as failed
  without blocking other publishing channels.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from src.publishing.base import _fetch


_IMPORT_URL = "https://www.wixapis.com/site-media/v1/files/import"


class WixMediaImportError(Exception):
    """
    Raised when a Cloudinary image cannot be imported into Wix Media Manager.
    Contains a human-readable reason; callers should fail the Wix channel only.
    """


@dataclass(frozen=True)
class WixMediaAsset:
    """
    Result of a successful Wix Media import.
    file_id is always non-empty (enforced at construction time).
    """
    file_id:      str
    url:          Optional[str] = None
    display_name: Optional[str] = None

    def __post_init__(self):
        if not self.file_id or not self.file_id.strip():
            raise ValueError("WixMediaAsset.file_id cannot be empty")


def import_image(
    source_url:   str,
    display_name: str,
    api_key:      str,
    site_id:      str,
    mime_type:    str = "image/jpeg",
) -> WixMediaAsset:
    """
    Import an image from source_url (e.g. Cloudinary) into Wix Media Manager.

    Args:
        source_url:   publicly accessible image URL (Cloudinary or similar)
        display_name: filename shown in Wix Media Manager
        api_key:      NB_WIX_API_KEY
        site_id:      NB_WIX_SITE_ID
        mime_type:    MIME type of the image (default: image/jpeg)

    Returns:
        WixMediaAsset with the Wix-native file_id needed for blog draft payload.

    Raises:
        WixMediaImportError: if the import fails for any reason, including
            HTTP errors, missing file_id in a 2xx response, or invalid JSON.
    """
    if not source_url:
        raise WixMediaImportError("import_image: source_url is required")
    if not api_key or not site_id:
        raise WixMediaImportError("import_image: NB_WIX_API_KEY and NB_WIX_SITE_ID are required")

    headers = {
        "Authorization": api_key,
        "wix-site-id":   site_id,
        "Content-Type":  "application/json",
    }
    payload = json.dumps({
        "url":         source_url,
        "displayName": display_name,
        "mimeType":    mime_type,
    }).encode()

    code, resp, raw = _fetch(_IMPORT_URL, method="POST", headers=headers, body=payload)

    if code not in (200, 201):
        err = resp.get("message", resp.get("_raw", raw[:200]))
        raise WixMediaImportError(
            f"Wix Media import failed (HTTP {code}): {err}"
        )

    # Wix returns the file object at response["file"] or at the top level.
    file_obj = resp.get("file", resp)

    # Normalize: Wix returns id as "id" or "fileId"
    file_id = file_obj.get("id") or file_obj.get("fileId") or ""
    if not file_id:
        raise WixMediaImportError(
            "Wix Media import returned HTTP success but no file ID in response. "
            f"Response keys: {list(file_obj.keys())}"
        )

    # Normalize: Wix returns URL as "url" or "fileUrl"
    file_url = file_obj.get("url") or file_obj.get("fileUrl") or None

    return WixMediaAsset(
        file_id=file_id,
        url=file_url,
        display_name=display_name,
    )
