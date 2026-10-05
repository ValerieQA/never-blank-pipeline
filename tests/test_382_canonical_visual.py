"""Issue #382 (NB-02h): the canonical master visual is nobody's derivative.

Owner decision, #311, 2026-10-04: *"The visual belongs to the shared canonical
editorial material / Golden Engine output, not to Wix and not to an individual
destination"*, and *"Instagram must therefore not depend on Wix having been
published first in order to obtain its image."*

What the code enforced instead, in three places: the derivative channel set was
closed to `{wix, linkedin}`, a Wix derivative was **required**, and
`master_asset_url` **had to equal** the Wix derivative's URL. The canonical
visual and the Wix asset were the same object by validation.

The replacement is **lineage, not resemblance**. A rendition declares which of
four technical transformations it applied, and a rendition that differs from the
master while declaring none is refused. Nothing compares pixels or scores
similarity: that would need a threshold, and a threshold is a product decision
nobody has made. (This repository has paid for that mistake once already — see
the invented `PORTFOLIO_OVERLAP` removed from #351.)

Release 1's product rule — a Wix visual is required for a Wix publication — is
untouched. It moved to where it belongs: the factory, not the model.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest

from src.publishing.image_pipeline import PLATFORM_SIZES
from src.visual.contract import (
    RELEASE1_CHANNELS,
    RENDITION_PLATFORM,
    SUPPORTED_FORMATS,
    ChannelDerivative,
    DerivativeStatus,
    LinkedInVisualState,
    RenditionTransform,
    VisualAssetsRecord,
    VisualGateError,
    build_visual_assets_record,
)

MASTER = "https://res.cloudinary.com/nb/master.png"
DIGEST = "sha256:" + "a" * 64


def _derivative(channel: str, *, url: str, transforms=(), fmt="png"):
    width, height = PLATFORM_SIZES[RENDITION_PLATFORM[channel]]
    return ChannelDerivative(
        channel=channel,
        url=url,
        width=width,
        height=height,
        format=fmt,
        status=DerivativeStatus.VALID,
        transforms=transforms,
    )


def _record(*derivatives, master=MASTER, linkedin=LinkedInVisualState.NOT_REQUESTED):
    return VisualAssetsRecord(
        run_id="run-1",
        origin_run_id="run-1",
        reused=False,
        signal_id="sig-1",
        source_article_digest=DIGEST,
        provider="cloudinary",
        method="generated",
        created_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        design_version="v9",
        status="valid",
        linkedin_visual=linkedin,
        master_asset_url=master,
        derivatives=tuple(derivatives),
    )


# ===========================================================================
# 1 · a record validates without a Wix derivative
# ===========================================================================


def test_a_visual_record_validates_with_no_wix_derivative():
    """The first of the three refusals, gone.

    This is what made Wix the owner: a record describing a visual that exists
    before — or without — any Wix publication could not be constructed at all.
    """

    record = _record(
        _derivative("instagram", url="https://res.cloudinary.com/nb/ig.png",
                    transforms=(RenditionTransform.RESIZE,)),
    )

    assert [item.channel for item in record.derivatives] == ["instagram"]
    assert "wix" not in {item.channel for item in record.derivatives}


# ===========================================================================
# 2 · the master is not a destination derivative URL
# ===========================================================================


def test_the_master_identity_is_not_any_destinations_derivative_url():
    """The master is its own asset, and no validator ties it to a channel."""

    record = _record(
        _derivative("wix", url="https://res.cloudinary.com/nb/wix.png",
                    transforms=(RenditionTransform.RESIZE,)),
        _derivative("linkedin", url="https://res.cloudinary.com/nb/li.png",
                    transforms=(RenditionTransform.RESIZE,)),
        linkedin=LinkedInVisualState.VALID,
    )

    urls = {item.url for item in record.derivatives}
    assert record.master_asset_url == MASTER
    assert record.master_asset_url not in urls, (
        "the canonical master is nobody's rendition"
    )


def test_the_master_may_also_be_one_renditions_asset_untransformed():
    """Not forbidden — a rendition that needed no transformation IS the master.

    The old rule said the master must be Wix's URL. The new one says nothing
    about which asset the master is, so this stays expressible: it is how
    Release 1 actually produces a record today.
    """

    record = _record(_derivative("wix", url=MASTER), master=MASTER)
    assert record.derivatives[0].transforms == ()


# ===========================================================================
# 3 · renditions beyond the original two, at their declared sizes
# ===========================================================================


def test_a_rendition_exists_for_a_destination_outside_the_original_two():
    for channel in ("facebook", "instagram", "threads"):
        record = _record(
            _derivative(channel, url=f"https://res.cloudinary.com/nb/{channel}.png",
                        transforms=(RenditionTransform.RESIZE,)),
        )
        (item,) = record.derivatives
        assert (item.width, item.height) == PLATFORM_SIZES[RENDITION_PLATFORM[channel]]


def test_a_rendition_at_the_wrong_declared_size_is_refused():
    """Widening the vocabulary did not loosen the size contract."""

    with pytest.raises(ValueError, match="dimensions"):
        _record(
            ChannelDerivative(
                channel="instagram",
                url="https://res.cloudinary.com/nb/ig.png",
                width=1200, height=628,  # LinkedIn's size, not Instagram's
                format="png",
                status=DerivativeStatus.VALID,
                transforms=(RenditionTransform.RESIZE,),
            ),
        )


def test_a_channel_with_no_declared_rendition_is_still_refused():
    """The vocabulary is wider, not open."""

    with pytest.raises(ValueError, match="no declared rendition"):
        _record(
            ChannelDerivative(
                channel="mastodon",
                url="https://res.cloudinary.com/nb/x.png",
                width=1080, height=1080, format="png",
                status=DerivativeStatus.VALID,
                transforms=(RenditionTransform.RESIZE,),
            ),
        )


def test_telegram_has_no_rendition_rather_than_an_invented_size():
    """An honest absence, recorded as one.

    `PLATFORM_SIZES` declares no Telegram size and `src/publishing/telegram.py`
    handles no image. Declaring one here would have been inventing product
    policy in a contract module — so Telegram is simply absent, and a Telegram
    rendition is refused like any undeclared channel.
    """

    assert "telegram" not in RENDITION_PLATFORM
    assert "telegram" not in PLATFORM_SIZES
    assert set(RENDITION_PLATFORM) == {
        "wix", "linkedin", "facebook", "instagram", "threads",
    }


# ===========================================================================
# 4 · Instagram without Wix — the decision's central requirement
# ===========================================================================


def test_an_instagram_rendition_needs_no_wix_publication_and_no_wix_derivative():
    """Siblings consuming one authority, not a chain.

    The owner decision is explicit: *"Instagram must therefore not depend on
    Wix having been published first in order to obtain its image. Wix and
    Instagram are sibling destinations consuming the same canonical visual
    authority."*
    """

    record = _record(
        _derivative("instagram", url="https://res.cloudinary.com/nb/ig.png",
                    transforms=(RenditionTransform.CROP,)),
    )

    channels = {item.channel for item in record.derivatives}
    assert channels == {"instagram"}
    # Nothing in the record references a Wix asset, a Wix publication or a
    # Wix-derived master.
    assert record.master_asset_url == MASTER
    assert all("wix" not in item.url for item in record.derivatives)


# ===========================================================================
# 5 · a rendition may change only technical representation
# ===========================================================================


def test_the_transformation_vocabulary_is_closed_to_the_four_allowed():
    """Exactly the owner's list: dimensions, aspect, crop/fit, encoding."""

    assert {item.value for item in RenditionTransform} == {
        "resize", "crop", "fit", "encode",
    }

    with pytest.raises(ValueError):
        ChannelDerivative(
            channel="instagram",
            url="https://res.cloudinary.com/nb/ig.png",
            width=1080, height=1350, format="png",
            status=DerivativeStatus.VALID,
            transforms=("restyle",),  # not a technical transformation
        )


def test_a_rendition_that_differs_from_the_master_must_say_what_it_did():
    """The protection that replaced Wix ownership.

    A different asset with no declared transformation is exactly a silent
    substitution, and it is refused structurally — not by judging the image.
    """

    with pytest.raises(ValueError, match="declares no technical transformation"):
        _record(
            _derivative("instagram", url="https://res.cloudinary.com/nb/other.png"),
        )


def test_the_factory_refuses_a_derivation_it_cannot_establish():
    """The repair of GPT's blocker on `d963fe6`.

    The first version of `_renditions_of` put `FIT` in when the rendition's
    asset differed from the master but its recorded dimensions and format did
    not — inventing a measurement in the one branch that exists *because*
    nothing was measured, three lines under a comment saying the
    crop-versus-fit distinction must not be guessed.

    It now fails closed. The branch is unreachable on the Release 1 path (a
    LinkedIn rendition always differs in size from the blog master), so this
    costs nothing today and removes the one place the contract could fabricate
    lineage.
    """

    from src.visual.contract import _renditions_of

    master = _derivative("wix", url="https://res.cloudinary.com/nb/wix.png")
    # Same recorded dimensions and format as the master, different asset: the
    # one input for which neither a resize nor an encode is observable.
    same_shape = master.model_copy(
        update={"channel": "wix", "url": "https://res.cloudinary.com/nb/other.png"}
    )

    with pytest.raises(VisualGateError, match="no technical derivation"):
        _renditions_of(master, same_shape)

    # Tested at the function rather than through `build_visual_assets_record`
    # because the factory cannot reach this branch: `_validate_channel` pins
    # every channel to its own declared size first, and no declared size
    # equals the blog master's 1920x1080 — so any other channel's rendition
    # necessarily differs in dimensions and yields a resize. The guard is
    # defensive, and that is the honest description of it.
    assert PLATFORM_SIZES["blog"] == (1920, 1080)
    assert all(
        PLATFORM_SIZES[key] != PLATFORM_SIZES["blog"]
        for destination, key in RENDITION_PLATFORM.items()
        if destination != "wix"
    )


def test_a_caller_that_knows_its_transformation_may_still_declare_it():
    """Failing closed in the factory is not forbidding the truth in the model.

    `FIT` and `CROP` remain declarable — what was removed is this contract
    *inferring* them. A producer that genuinely performed a fit records it.
    """

    record = _record(
        _derivative(
            "instagram",
            url="https://res.cloudinary.com/nb/ig.png",
            transforms=(RenditionTransform.FIT,),
        ),
    )
    assert record.derivatives[0].transforms == (RenditionTransform.FIT,)


def test_the_contract_never_infers_a_transformation_it_did_not_measure():
    """No branch assigns a transform without a property difference behind it.

    Asserted on the parsed source: every `RenditionTransform` member named in
    `_renditions_of` must be `RESIZE` or `ENCODE`, the only two the recorded
    dimensions and format can establish.
    """

    import ast
    import inspect

    from src.visual import contract

    tree = ast.parse(inspect.getsource(contract._renditions_of))
    named = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "RenditionTransform"
    }
    assert named == {"RESIZE", "ENCODE"}, named


def test_nothing_in_the_contract_compares_images_or_scores_resemblance():
    """No invented threshold, and the absence is asserted rather than trusted.

    "Preserved the editorial visual" is enforced as lineage. A similarity score
    would need a cutoff, and choosing one would be a product decision smuggled
    in as an implementation detail.
    """

    import ast

    # The executable code, with comments and docstrings stripped: a comment
    # explaining that there is no threshold is not a threshold. (This test
    # caught exactly that in its first form, which is the same trap as the
    # workflow test that read a `git add` out of a comment saying there is
    # none.)
    tree = ast.parse(pathlib.Path("src/visual/contract.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant
            ) and isinstance(body[0].value.value, str):
                body.pop(0)
    code = ast.unparse(tree).lower()

    for smell in ("similarity", "threshold", "perceptual", "phash", "ssim"):
        assert smell not in code, smell
    # And no numeric cutoff pretending to be a contract constant.
    assert "0." not in code.replace("0.0", ""), "no fractional constant in the contract"


# ===========================================================================
# 6 · one identity across several renditions
# ===========================================================================


def test_one_visual_identity_is_preserved_across_several_renditions():
    record = _record(
        _derivative("wix", url="https://res.cloudinary.com/nb/wix.png",
                    transforms=(RenditionTransform.RESIZE,)),
        _derivative("linkedin", url="https://res.cloudinary.com/nb/li.png",
                    transforms=(RenditionTransform.RESIZE,)),
        _derivative("instagram", url="https://res.cloudinary.com/nb/ig.png",
                    transforms=(RenditionTransform.CROP,)),
        _derivative("facebook", url="https://res.cloudinary.com/nb/fb.png",
                    transforms=(RenditionTransform.RESIZE, RenditionTransform.ENCODE),
                    fmt="jpeg"),
        linkedin=LinkedInVisualState.VALID,
    )

    assert len(record.derivatives) == 4
    # One master, one editorial material, one design — for all of them.
    assert record.master_asset_url == MASTER
    assert record.source_article_digest == DIGEST
    assert record.design_version == "v9"
    for item in record.derivatives:
        assert item.transforms, f"{item.channel} states its lineage"
        assert item.format in SUPPORTED_FORMATS


# ===========================================================================
# 7 · Release 1 behaviour remains expressible, and its product rule stands
# ===========================================================================


def test_release_1_still_requires_a_wix_visual_where_that_rule_belongs():
    """Moved, not weakened: the factory keeps it, the model no longer claims it.

    `wednesday_golden.yml` is still publishing Wix and LinkedIn (owner
    decision, #326), so this rule has to keep working exactly as it did.
    """

    with pytest.raises(VisualGateError, match="required Wix visual is missing"):
        build_visual_assets_record(
            {"_design_version": "v9"},
            run_id="run-1",
            signal_id="sig-1",
            article_body="body",
            design_version="v9",
        )

    # And the Release 1 requirement table still says so, unchanged.
    assert RELEASE1_CHANNELS == {"wix": ("blog", True), "linkedin": ("linkedin", False)}


def test_the_release_1_record_is_still_what_it_was():
    """The two-channel passport Release 1 produces, built by the real factory."""

    record = build_visual_assets_record(
        {
            "_design_version": "v9",
            "blog": {"url": "https://res.cloudinary.com/nb/wix.png", "size": "1920x1080"},
            "linkedin": {"url": "https://res.cloudinary.com/nb/li.png", "size": "1200x628"},
        },
        run_id="run-1",
        signal_id="sig-1",
        article_body="body",
        design_version="v9",
    )

    assert [item.channel for item in record.derivatives] == ["wix", "linkedin"]
    assert record.linkedin_visual is LinkedInVisualState.VALID
    # The master is still the Wix asset in a Release 1 run — now because that
    # is what the factory produced, not because the model demanded it.
    assert record.master_asset_url == record.derivatives[0].url
    assert record.derivatives[0].transforms == ()
    # And the LinkedIn rendition states the resize that produced it.
    assert record.derivatives[1].transforms == (RenditionTransform.RESIZE,)


def test_the_package_provenance_gate_is_not_weakened():
    """#382 gives the gate a master to find; it must still refuse what it did.

    The package builder's visual/provenance refusal is the fail-closed boundary
    #308's S-14 relies on, so this asserts the gate's own module still carries
    its refusal rather than trusting that nothing moved.
    """

    import inspect

    from src.publishing import package

    source = inspect.getsource(package)
    assert "PackageFailureCategory.PROVENANCE" in source
    assert "visual" in source.lower()
