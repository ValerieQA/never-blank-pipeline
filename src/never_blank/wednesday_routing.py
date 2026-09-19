"""Which editorial pipeline does this run use? (Issue #209)

The single routing seam between the production entrypoint and Never Blank's
two editorial products. It exists so that wiring the restored July Wednesday
path into the lifecycle costs one branch at one call site, and so that the
restored package (``wednesday_july``) stays byte-identical to ``c7d3a23``.

    Wednesday  → src.never_blank.wednesday_july.generate_wednesday_article
    everything → src.editorial.pipeline.generate_article   (unchanged)

Monday is not mentioned here and is not affected: any role that is not the
declared Wednesday role takes exactly the path it took before.

**Why an adapter and not a change to the restored modules.** July's Never
Blank Voice names the branded closing line ``signature``; the current
lifecycle reads ``echo_line``. It is the same value under two historical
names. July's Platform Composer also returns ``{word_count, body}`` with no
``title``, and July had no Pattern Extractor, so no ``pattern`` key exists.
Rather than edit restored files — which would break the verbatim-port
guarantee that is the whole point of #207 — the shape is reconciled here, at
the boundary, where the translation is visible and testable.

The absent ``title`` is deliberately *not* synthesised: July published the
source headline as the article title, the entrypoint already falls back to
exactly that when a composition returns no title, and inventing one here
would be a silent editorial change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.never_blank.wednesday_july import generate_wednesday_article
from src.utils.llm_client import model_input_addendum
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.editorial.editorial_plan import EditorialPlan
    from src.strategy.client_contracts import ClientContracts

log = get_logger("never_blank.wednesday_routing")

#: The declared role whose generation runs the restored July path. Matching is
#: on the configured role id, so a run reaches this path only when it was
#: explicitly dispatched as Wednesday.
WEDNESDAY_ROLE_ID = "never-blank-wednesday-golden"


def is_wednesday_role(role_identity) -> bool:
    """Does this run execute under the declared Wednesday role?

    Accepts the ``EditorialRoleIdentity`` the entrypoint resolves, a plain
    role-id string, or ``None`` for a role-less run. Anything that is not
    Wednesday answers ``False`` and keeps its existing pipeline.
    """
    if role_identity is None:
        return False
    role_id = getattr(role_identity, "role_id", role_identity)
    return isinstance(role_id, str) and role_id == WEDNESDAY_ROLE_ID


def unexecutable_lens_routes(contracts: ClientContracts | None) -> tuple[str, ...]:
    """Client lens routes the restored Wednesday path cannot execute (#267).

    The restored July modules are pinned verbatim, so a client's text reaches
    them only one way: the run's ``EditorialPlan``, appended to every model
    call they make — which carries the conditional lenses the run activated
    for ``writing``. Nothing else a lens can name reaches this path: standing
    lenses travel with role rules the July stages never read, and Wednesday
    keeps its own acceptance with no reviser context (#254 D10), so nothing
    routed to ``revision`` reaches a reviser.

    Every other route is returned as ``"<lens identity> → <stage>"`` so the
    run can refuse it, rather than load policy that would never execute.
    """
    if contracts is None:
        return ()
    return tuple(
        f"{lens.identity} → {stage}"
        for lens in contracts.lenses
        for stage in lens.stages
        if lens.is_standing or stage != "writing"
    )


def generate_for_wednesday(
    signal: dict, editorial_plan: EditorialPlan | None = None
) -> dict:
    """Run the restored July path and present its result to the lifecycle.

    Returns the same top-level shape the shared engine returns, so every
    downstream stage — acceptance, transparency, composition acceptance,
    packaging, preflight and publication — is reached unchanged.

    Two reconciliations, both additive and both recorded:

    * ``structured_article["echo_line"]`` is filled from July's
      ``signature`` when the restored voice did not emit an ``echo_line``.
      Same branded closing line, historical name difference only.
    * ``pattern`` is an empty mapping. July had no Pattern Extractor, so
      there is no owner-centred pattern to report. The entrypoint reads it
      only for topical hashtags and already tolerates its absence.

    Nothing is invented. No July value is overwritten.

    ``editorial_plan`` (#267) is the run's plan when the client's contract for
    this stream needs one. The restored modules stay verbatim, so the plan is
    not threaded through them: its prompt text is appended to the user message
    of every model call the restored path makes, for this generation only.
    With no plan — Never Blank's Wednesday today — the path is exactly July's.
    """

    if editorial_plan is None:
        result = generate_wednesday_article(signal)
    else:
        with model_input_addendum(editorial_plan.as_prompt_text()):
            result = generate_wednesday_article(signal)

    structured = dict(result.get("structured_article") or {})
    if not structured.get("echo_line"):
        signature = structured.get("signature", "")
        if signature:
            structured["echo_line"] = signature

    log.info(
        "Wednesday routing: restored July path produced %d platform bodies "
        "for signal %s",
        len(result.get("platforms") or {}), signal.get("SIGNAL_ID", "unknown"),
    )
    return {
        **result,
        "structured_article": structured,
        # July produced no Pattern Extractor output; say so explicitly rather
        # than letting a missing key look like a failed stage.
        "pattern": result.get("pattern") or {},
    }
