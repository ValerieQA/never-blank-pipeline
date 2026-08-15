"""Canonical Release 1 visual contract and fail-closed channel gate (Issue #96).

A visual reported by Never Blank must be a real publication asset with a
truthful passport: which run produced it, which content it belongs to, how it
was produced, which design version produced it, which channel derivative it
represents, and whether it is actually valid for publication. Visual success
is never claimed merely because an image function returned something.

Authoritative Release 1 product rule:

- the **Wix** visual (the ``blog`` master derivative) is **required** — if it
  cannot be truthfully produced, uploaded, and validated as a publishable
  remote asset, the run fails closed before Wix packaging/publication;
- the **LinkedIn** visual is **optional**: a genuinely absent/not-requested
  LinkedIn visual leaves the valid text-only LinkedIn path open, but an
  attempted LinkedIn visual that failed generation/upload/validation is never
  silently converted into "text-only success" — it fails closed;
- a local filesystem path is never a publishable remote asset URL;
- provider/transport failure is never recorded as successful completion.

The gate validates the **resulting** derivative (actual local render bytes
when available, remote-URL shape, dimensions, format, lineage, design
version), not merely the parameters the renderer was asked for, and persists
one immutable run-scoped ``visual_assets.json``. Real Cloudinary/Wix/LinkedIn
asset proof remains deferred live verification (Stories #19/#21).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.editorial.linkedin_composition import article_digest
from src.publishing.image_pipeline import PLATFORM_SIZES


VISUAL_ASSETS_SCHEMA_VERSION = "1.0"

# Release 1 channel requirements: channel -> (source platform key, required).
RELEASE1_CHANNELS = {
    "wix": ("blog", True),
    "linkedin": ("linkedin", False),
}

SUPPORTED_FORMATS = ("png", "jpeg")

_REMOTE_URL = re.compile(r"^https://[^\s]+$")


class VisualGateError(RuntimeError):
    """The required visual state cannot be truthfully established — fail closed."""


class DerivativeStatus(str, Enum):
    VALID = "valid"


class LinkedInVisualState(str, Enum):
    VALID = "valid"
    NOT_REQUESTED = "not_requested"


class _VisualModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChannelDerivative(_VisualModel):
    channel: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=2000)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    format: str = Field(min_length=1, max_length=20)
    status: DerivativeStatus

    @field_validator("url")
    @classmethod
    def _remote_only(cls, value: str) -> str:
        if not _REMOTE_URL.match(value):
            raise ValueError("derivative URL must be a publishable https URL")
        return value


class VisualAssetsRecord(_VisualModel):
    """Immutable run-scoped passport of the run's publication visuals.

    ``run_id`` is the run this record belongs to (its persistence namespace);
    ``origin_run_id`` is the run that actually produced the visuals. For a
    fresh generation they are identical (``reused=False``). For
    ``--from-package`` reuse the publication run persists a reuse passport
    whose ``origin_run_id`` preserves the true producing run — a reused
    visual is never represented as produced by the new publication run.
    """

    schema_version: str = VISUAL_ASSETS_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    origin_run_id: str = Field(min_length=1, max_length=200)
    reused: bool
    signal_id: str = Field(min_length=1, max_length=200)
    source_article_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    provider: str = Field(min_length=1, max_length=80)
    method: str = Field(min_length=1, max_length=80)
    created_at: datetime
    design_version: str = Field(min_length=1, max_length=80)
    status: str = Field(pattern=r"^valid$")
    linkedin_visual: LinkedInVisualState
    master_asset_url: str = Field(min_length=1, max_length=2000)
    derivatives: tuple[ChannelDerivative, ...] = Field(min_length=1, max_length=4)

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != VISUAL_ASSETS_SCHEMA_VERSION:
            raise ValueError(f"unsupported visual assets schema_version: {value!r}")
        return value

    @model_validator(mode="after")
    def _truthful_origin(self) -> "VisualAssetsRecord":
        if self.reused and self.origin_run_id == self.run_id:
            raise ValueError("a reused visual record cannot claim itself as origin")
        if not self.reused and self.origin_run_id != self.run_id:
            raise ValueError(
                "a freshly produced visual record must be its own origin"
            )
        return self

    def _derivative_url(self, channel: str) -> str | None:
        for item in self.derivatives:
            if item.channel == channel:
                return item.url
        return None

    @property
    def wix_url(self) -> str | None:
        return self._derivative_url("wix")

    @property
    def linkedin_url(self) -> str | None:
        return self._derivative_url("linkedin")


def _actual_image_properties(path_value: str | None) -> tuple[int, int, str] | None:
    """Read actual rendered-file properties when the local render is available."""

    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.width, img.height, (img.format or "").lower()
    except Exception as exc:  # noqa: BLE001 — unreadable render is a truthful failure
        raise VisualGateError(
            f"rendered visual file for validation is unreadable ({type(exc).__name__})"
        ) from exc


def _validate_channel(channel: str, entry: dict, *, required: bool) -> ChannelDerivative:
    if entry.get("upload_failed"):
        raise VisualGateError(
            f"{channel} visual upload failed — provider failure is never recorded "
            "as successful completion"
        )
    url = entry.get("url") or ""
    if not url:
        raise VisualGateError(f"{channel} visual has no remote asset URL")
    if not _REMOTE_URL.match(str(url)):
        raise VisualGateError(
            f"{channel} visual URL is not a publishable remote asset URL "
            "(a local filesystem path never crosses the publishing boundary)"
        )

    platform_key = RELEASE1_CHANNELS[channel][0]
    expected_w, expected_h = PLATFORM_SIZES[platform_key]

    size = str(entry.get("size") or "")
    try:
        width, height = (int(part) for part in size.split("x"))
    except ValueError as exc:
        raise VisualGateError(
            f"{channel} visual has malformed dimensions metadata: {size!r}"
        ) from exc

    fmt = "png"
    actual = _actual_image_properties(entry.get("path"))
    if actual is not None:
        actual_w, actual_h, actual_fmt = actual
        width, height, fmt = actual_w, actual_h, actual_fmt or fmt

    if (width, height) != (expected_w, expected_h):
        raise VisualGateError(
            f"{channel} visual dimensions {width}x{height} do not match the "
            f"required {expected_w}x{expected_h}"
        )
    if fmt not in SUPPORTED_FORMATS:
        raise VisualGateError(f"{channel} visual format {fmt!r} is unsupported")

    return ChannelDerivative(
        channel=channel, url=str(url), width=width, height=height,
        format=fmt, status=DerivativeStatus.VALID,
    )


def _provider_for(url: str) -> str:
    return "cloudinary" if "cloudinary.com" in url else "remote"


def build_visual_assets_record(
    platform_images: dict,
    *,
    run_id: str,
    signal_id: str,
    article_body: str,
    design_version: str,
) -> VisualAssetsRecord:
    """Validate the run's resulting visual derivatives and build the passport.

    Raises ``VisualGateError`` when the required Wix visual state — or an
    attempted-but-invalid LinkedIn visual — cannot be truthfully established.
    """

    if not isinstance(platform_images, dict):
        raise VisualGateError("visual preparation returned no usable image mapping")

    recorded_version = platform_images.get("_design_version")
    if recorded_version != design_version:
        raise VisualGateError(
            f"visual design version {recorded_version!r} does not match the "
            f"current design version {design_version!r}"
        )

    wix_entry = platform_images.get("blog")
    if not isinstance(wix_entry, dict):
        raise VisualGateError(
            "required Wix visual is missing — no valid Wix visual, no Wix "
            "package or publication"
        )
    derivatives = [_validate_channel("wix", wix_entry, required=True)]

    linkedin_entry = platform_images.get("linkedin")
    if linkedin_entry is None:
        linkedin_state = LinkedInVisualState.NOT_REQUESTED
    else:
        if not isinstance(linkedin_entry, dict):
            raise VisualGateError("LinkedIn visual entry is malformed")
        # Attempted LinkedIn visual: optionality never hides its failure.
        derivatives.append(
            _validate_channel("linkedin", linkedin_entry, required=False)
        )
        linkedin_state = LinkedInVisualState.VALID

    master_url = derivatives[0].url
    return VisualAssetsRecord(
        run_id=run_id,
        origin_run_id=run_id,
        reused=False,
        signal_id=signal_id,
        source_article_digest=article_digest(article_body),
        provider=_provider_for(master_url),
        method=str(platform_images.get("_method") or "image-pipeline"),
        created_at=datetime.now(timezone.utc),
        design_version=design_version,
        status="valid",
        linkedin_visual=linkedin_state,
        master_asset_url=master_url,
        derivatives=tuple(derivatives),
    )


def verify_visual_assets_record(
    record: VisualAssetsRecord,
    *,
    run_id: str,
    article_body: str,
) -> None:
    """Fail closed on cross-run or source-content drift."""

    if record.run_id != run_id:
        raise VisualGateError(
            "visual assets record belongs to a different run: "
            f"record={record.run_id!r} expected={run_id!r}"
        )
    if record.source_article_digest != article_digest(article_body):
        raise VisualGateError(
            "visual assets record does not match the accepted source article"
        )


def reuse_visual_assets_record(
    loaded: dict,
    *,
    source_run_id: str,
    publication_run_id: str,
    article_body: str,
) -> VisualAssetsRecord:
    """Build the truthful reuse passport for a ``--from-package`` publication run.

    The ONLY accepted provenance source is the originating run's persisted
    ``visual_assets.json``. Origin is never inferred from ``signal_id`` or
    content shape, and the current publication run is never stamped as the
    visual origin. Fails closed when the source identity cannot be proven.
    """

    if not isinstance(loaded, dict) or not loaded:
        raise VisualGateError(
            "source run has no trustworthy visual passport — reused visuals "
            "cannot prove their originating run; failing closed"
        )
    try:
        source = VisualAssetsRecord.model_validate(loaded)
    except Exception as exc:  # noqa: BLE001 — malformed passport is a truthful stop
        raise VisualGateError(
            "source visual passport is malformed or violates the strict contract"
        ) from exc

    if source.run_id != source_run_id:
        raise VisualGateError(
            "source visual passport belongs to a different run "
            f"(record={source.run_id!r}, requested source={source_run_id!r}) — "
            "cross-run visual laundering is not allowed"
        )
    if source.source_article_digest != article_digest(article_body):
        raise VisualGateError(
            "source visual passport does not match the reused article content"
        )

    return VisualAssetsRecord(
        run_id=publication_run_id,
        origin_run_id=source.origin_run_id,
        reused=True,
        signal_id=source.signal_id,
        source_article_digest=source.source_article_digest,
        provider=source.provider,
        method=source.method,
        created_at=datetime.now(timezone.utc),
        design_version=source.design_version,
        status=source.status,
        linkedin_visual=source.linkedin_visual,
        master_asset_url=source.master_asset_url,
        derivatives=source.derivatives,
    )
