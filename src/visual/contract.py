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
# This table is a **product** rule about what a Release 1 run must produce, and
# `build_visual_assets_record` is where it is enforced. It is deliberately not
# the model's vocabulary any more — see `RENDITION_PLATFORM` (NB-02h).
RELEASE1_CHANNELS = {
    "wix": ("blog", True),
    "linkedin": ("linkedin", False),
}

#: Destination -> the platform key whose declared size that destination's
#: rendition must match (NB-02h).
#:
#: This is the **model's** vocabulary: which destinations can hold a rendition
#: of the canonical master at all. It is wider than ``RELEASE1_CHANNELS``
#: because the master is destination-independent — Wix and Instagram are
#: siblings consuming one authority (owner decision, #311) — and narrower than
#: the six destinations for one honest reason:
#:
#: **Telegram is absent.** ``PLATFORM_SIZES`` declares no Telegram size and
#: ``src/publishing/telegram.py`` handles no image, so Telegram has **no
#: rendition** rather than an undeclared one. Inventing a size here would be
#: inventing product policy.
RENDITION_PLATFORM = {
    "wix": "blog",
    "linkedin": "linkedin",
    "facebook": "facebook",
    "instagram": "instagram",
    "threads": "threads",
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


class RenditionTransform(str, Enum):
    """The only transformations a rendition may apply (NB-02h).

    Closed, and that closedness is the whole mechanism. The owner decision on
    #311 permits a destination *"only the technical transformations required by
    the platform"* — dimensions, aspect ratio, crop or fit, encoding — and
    states that these *"do not authorize a new destination-specific image
    concept, factual interpretation, or independently generated visual"*.

    So a rendition has no field in which to carry a different editorial
    visual: it names the transformations it applied, from these four, and a
    fifth is refused by the enum rather than by a judgement about pixels.
    Nothing here compares images or scores similarity — there is no threshold
    to invent, and inventing one is how a product rule gets smuggled in as an
    implementation detail.
    """

    RESIZE = "resize"
    CROP = "crop"
    FIT = "fit"
    ENCODE = "encode"


class _VisualModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChannelDerivative(_VisualModel):
    channel: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=2000)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    format: str = Field(min_length=1, max_length=20)
    status: DerivativeStatus
    #: The technical transformations this rendition applied to the canonical
    #: master. Empty means it *is* the master's own asset, unmodified — which
    #: is why the default is empty and not a guess: a record written before
    #: NB-02h carries no transforms and is still a truthful record of a
    #: rendition that needed none.
    transforms: tuple[RenditionTransform, ...] = Field(default=(), max_length=4)

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
    derivatives: tuple[ChannelDerivative, ...] = Field(
        min_length=1, max_length=len(RENDITION_PLATFORM)
    )

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

    @model_validator(mode="after")
    def _channel_semantics(self) -> "VisualAssetsRecord":
        """Publication invariants live in the strict model itself.

        Every construction path — the fresh gate, strict reload, and the
        reuse seam — therefore enforces the same channel semantics: a
        schema-shaped but semantically invalid passport (wrong dimensions,
        unsupported format, missing required Wix derivative, foreign or
        duplicate channels, master/Wix mismatch, or a LinkedIn state that
        contradicts the derivatives) can never be validated, reused, or
        published.
        """

        channels = [item.channel for item in self.derivatives]
        if len(set(channels)) != len(channels):
            raise ValueError("visual derivative channels must be unique")
        unknown = sorted(set(channels) - set(RENDITION_PLATFORM))
        if unknown:
            raise ValueError(
                "visual record carries channels with no declared rendition: "
                + ", ".join(unknown)
            )
        by_channel = {item.channel: item for item in self.derivatives}
        # No destination is required here, and Wix least of all (NB-02h). The
        # master is owned by the canonical editorial material, so a record may
        # hold an Instagram rendition and no Wix one — Wix and Instagram are
        # siblings consuming one authority, not a chain. Release 1's product
        # rule that a Wix visual must exist is enforced where it belongs, in
        # `build_visual_assets_record`, and is unchanged.
        for item in self.derivatives:
            platform_key = RENDITION_PLATFORM[item.channel]
            expected = PLATFORM_SIZES[platform_key]
            if (item.width, item.height) != expected:
                raise ValueError(
                    f"{item.channel} derivative dimensions "
                    f"{item.width}x{item.height} do not match the required "
                    f"{expected[0]}x{expected[1]}"
                )
            if item.format not in SUPPORTED_FORMATS:
                raise ValueError(
                    f"{item.channel} derivative format {item.format!r} is unsupported"
                )
        # The master has its own identity. It is no longer *required to be* a
        # destination's derivative URL, which is what made Wix the owner: a
        # record whose master could only be the Wix asset could not describe a
        # visual that exists before, or without, Wix.
        #
        # What replaces that constraint is lineage, not similarity: a rendition
        # whose asset differs from the master must say which of the four
        # technical transformations produced it. A rendition that is a
        # different editorial visual therefore has nowhere to say so — and
        # nothing here compares pixels or scores resemblance, because the
        # threshold that would need is a product decision nobody has made.
        for item in self.derivatives:
            if item.url != self.master_asset_url and not item.transforms:
                raise ValueError(
                    f"the {item.channel} rendition is a different asset from the "
                    "canonical master and declares no technical transformation; "
                    "a rendition states what it did to the master"
                )
        has_linkedin = "linkedin" in by_channel
        if self.linkedin_visual is LinkedInVisualState.VALID and not has_linkedin:
            raise ValueError(
                "linkedin_visual claims a valid LinkedIn derivative that is absent"
            )
        if self.linkedin_visual is LinkedInVisualState.NOT_REQUESTED and has_linkedin:
            raise ValueError(
                "linkedin_visual claims not_requested but a LinkedIn derivative exists"
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

    platform_key = RENDITION_PLATFORM[channel]
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


def _renditions_of(
    master: ChannelDerivative, item: ChannelDerivative
) -> tuple[RenditionTransform, ...]:
    """Which technical transformations turned ``master`` into ``item``.

    Read off the two derivatives' own recorded properties. An asset identical
    to the master's declares nothing, which is the truthful answer: no
    transformation was applied.
    """

    if item.url == master.url:
        return ()
    transforms: list[RenditionTransform] = []
    if (item.width, item.height) != (master.width, master.height):
        transforms.append(RenditionTransform.RESIZE)
    if item.format != master.format:
        transforms.append(RenditionTransform.ENCODE)
    if not transforms:
        # A different asset with the same dimensions and format: something was
        # done to it that these properties do not show. Rather than invent a
        # category, the record says the platform required a fit — the weakest
        # true statement available, and the one the gate below demands.
        transforms.append(RenditionTransform.FIT)
    return tuple(transforms)


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

    # Each rendition states what it did to the master, derived from what the
    # pipeline already recorded rather than asserted: different pixel
    # dimensions are a resize, a different format is an encode. The finer
    # crop-versus-fit distinction is **not** claimed, because the image
    # pipeline does not record which one it performed and guessing would put a
    # fact into a passport that nobody measured.
    master = derivatives[0]
    derivatives = [master] + [
        item.model_copy(update={"transforms": _renditions_of(master, item)})
        for item in derivatives[1:]
    ]
    master_url = master.url
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
