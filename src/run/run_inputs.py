"""Where a run's §4.1 input versions come from (Issue #336, slice SL-1).

``src/run/run_manifest.py`` fixes the **shape** a run states its inputs in.
This module fills it in: it reads the identity of each Step 3 §4.1 input out
of the contracts and the register the run actually loaded, so that what the
manifest says was read is derived from the reading rather than described
beside it.

The knowledge register identity (Step 4 §9.1)
---------------------------------------------
"Register version = the git commit of the ``knowledge/`` tree plus a digest
over the loaded files." Both halves are here, once, so that the knowledge
slices reference this instead of each inventing an identity of its own:

- the **commit** is the last commit that touched the register directory. It is
  the tree's identity in the repository's own terms, and it is ``None`` for a
  register in no repository or one nobody has committed — an honest absence,
  not a zero;
- the **digest** is over what :func:`~src.knowledge.loader.load_register`
  kept: every record, ladder and check, by ID, version and file digest. Over
  the *loaded* files, because §9.2 does not load retired records and a run is
  identified by the knowledge it could actually use.

The two answer different questions and are recorded together for that reason.
The commit covers the whole tree and says nothing about uncommitted edits; the
digest covers the loaded files and moves the moment one of them changes,
committed or not.

What a run cannot state
-----------------------
Two of the seven §4.1 inputs have no artifact in this repository yet: the
Audience Profile, which #335 owns, and the reference library. Their absence is
**stated** — :meth:`InputVersion.absent` with a reason — rather than filled in
with a plausible value, because a manifest that invents an identity is worse
evidence than one that says it had none.

Sources: ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§4.1; ``docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md`` §9.1.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Final, Optional, Sequence

from src.knowledge.loader import KnowledgeBase
from src.knowledge.validator import DEFAULT_LADDER_NAME, LADDERS_DIR_NAME

# The repository's one read-only git call, reused rather than copied: it
# already answers "or None" for every way git can be unavailable — no binary,
# no repository, no permission, a timeout — and a second answer to that would
# eventually become a different answer.
from src.run.code_identity import _git
from src.run.run_manifest import (
    InputKind,
    InputVersion,
    PlatformVerification,
    RunInputs,
)
from src.strategy.client_contracts import ClientContracts

#: The serializations each multi-document input's digest is taken over. Bump
#: one only when the meaning of its payload changes, never when the documents
#: do — the digest is how a changed input is noticed.
CANONICAL_REGISTER_SERIALIZATION: Final[str] = "knowledge-register-loaded-v1"
CANONICAL_LENSES_SERIALIZATION: Final[str] = "client-lenses-v1"
CANONICAL_PLATFORM_SERIALIZATION: Final[str] = "platform-knowledge-dates-v1"

#: Platform knowledge is the destination family (§2.2): what a platform does,
#: recorded per destination and re-verified on a date.
PLATFORM_RECORD_PREFIX: Final[str] = "K-DST-"

#: What a run says when an input has no artifact to read. Each one states a
#: fact about this repository, not a guess about the run.
NO_CLIENT_CONTRACT: Final[str] = "this run read no client contract"
NO_AUDIENCE_PROFILE: Final[str] = (
    "no Audience Profile artifact exists yet (#335); this run read none"
)
NO_EDITORIAL_LENS: Final[str] = "the client contract carried no lens"
NO_KNOWLEDGE_REGISTER: Final[str] = "this run loaded no knowledge register"
NO_PLATFORM_KNOWLEDGE: Final[str] = (
    f"the loaded register held no {PLATFORM_RECORD_PREFIX}* record"
)
NO_REFERENCE_LIBRARY: Final[str] = (
    "no reference library artifact exists yet; this run read none"
)
NO_STRENGTH_LADDER: Final[str] = (
    f"the loaded register held no {LADDERS_DIR_NAME}/{DEFAULT_LADDER_NAME}"
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class RunInputsError(ValueError):
    """A run cannot honestly state one of its §4.1 inputs."""


def run_inputs(
    *,
    contracts: Optional[ClientContracts] = None,
    knowledge: Optional[KnowledgeBase] = None,
    register_dir: Optional[Path] = None,
) -> RunInputs:
    """The §4.1 input versions of a run that loaded these inputs.

    Every argument is optional and each absence is recorded as one: a run that
    loaded no register states that for the register, the ladder and the
    platform knowledge alike, because all three are read out of it.
    """

    if knowledge is not None and register_dir is None:
        raise RunInputsError(
            "a loaded register is identified by its directory as well as its "
            "files (§9.1: the git commit of the knowledge/ tree); pass "
            "register_dir beside knowledge"
        )
    return RunInputs.of(
        client_contract=client_contract_version(contracts),
        audience_profile=InputVersion.absent(
            InputKind.AUDIENCE_PROFILE, NO_AUDIENCE_PROFILE
        ),
        editorial_lens=editorial_lens_version(contracts),
        knowledge_register=knowledge_register_version(
            knowledge, register_dir=register_dir
        ),
        platform_knowledge=platform_knowledge_version(knowledge),
        reference_library=InputVersion.absent(
            InputKind.REFERENCE_LIBRARY, NO_REFERENCE_LIBRARY
        ),
        strength_ladder=strength_ladder_version(
            knowledge, register_dir=register_dir
        ),
    )


# ----------------------------------------------------------------------
# The client's own documents
# ----------------------------------------------------------------------


def client_contract_version(
    contracts: Optional[ClientContracts],
) -> InputVersion:
    """The Client Contract the run executed against: the stream contract.

    Its digest is the one ``client_contracts`` already computes over the file
    as written, so the manifest and the plan lineage a run records name the
    same bytes.
    """

    if contracts is None:
        return InputVersion.absent(
            InputKind.CLIENT_CONTRACT, NO_CLIENT_CONTRACT
        )
    return InputVersion(
        kind=InputKind.CLIENT_CONTRACT,
        identities=(contracts.stream.identity,),
        digest=contracts.stream.digest,
    )


def editorial_lens_version(
    contracts: Optional[ClientContracts],
) -> InputVersion:
    """The Editorial Lens the run carried — every lens the contract holds.

    §4.1 names one input and a client routes several lenses to several stages,
    so the input is all of them: the identities are listed in the order the
    contract declares them, and the digest is over each lens's own digest, so
    a lens edited, added or dropped moves it. Zero lenses is a valid state
    (``client_contracts``), and is stated as an absence rather than as an
    input with an empty digest.
    """

    if contracts is None or not contracts.lenses:
        return InputVersion.absent(InputKind.EDITORIAL_LENS, NO_EDITORIAL_LENS)
    return InputVersion(
        kind=InputKind.EDITORIAL_LENS,
        identities=tuple(lens.identity for lens in contracts.lenses),
        digest=_digest_over(
            CANONICAL_LENSES_SERIALIZATION,
            [[lens.identity, lens.digest] for lens in contracts.lenses],
        ),
    )


# ----------------------------------------------------------------------
# The knowledge register (Step 4 §9.1)
# ----------------------------------------------------------------------


def knowledge_register_version(
    knowledge: Optional[KnowledgeBase], *, register_dir: Optional[Path]
) -> InputVersion:
    """The register identity §9.1 gives a run: the commit, and the files.

    This is the one definition of that identity. A slice that needs to say
    which register a run used calls this rather than digesting the directory
    its own way, so two runs of the same register cannot disagree about what
    it was.
    """

    if knowledge is None or register_dir is None:
        return InputVersion.absent(
            InputKind.KNOWLEDGE_REGISTER, NO_KNOWLEDGE_REGISTER
        )
    commit = register_tree_commit(register_dir)
    return InputVersion(
        kind=InputKind.KNOWLEDGE_REGISTER,
        identities=(commit,) if commit is not None else (),
        digest=_digest_over(
            CANONICAL_REGISTER_SERIALIZATION, _loaded_files(knowledge)
        ),
    )


def register_tree_commit(register_dir: Path) -> Optional[str]:
    """The last commit that touched the register tree, or ``None``.

    ``None`` for a register in no repository, one git cannot be run over, and
    one nobody has committed yet — a fixture register in a temporary directory
    is all three. None of those is a defect: the digest over the loaded files
    identifies the register either way, and a fabricated commit would be worse
    than a stated absence (the ``code_identity`` precedent).

    It deliberately says nothing about uncommitted edits. Those move the
    digest, which is the half of the identity that notices them.
    """

    # ``-C`` puts git inside the register itself, so the repository is found
    # from the tree that was actually loaded and the pathspec is simply "this
    # directory" — no caller has to say where the repository root is, and no
    # path has to be made relative to it.
    output = _git(Path(register_dir), "log", "-1", "--format=%H", "--", ".")
    if output is None:
        return None
    commit = output.strip()
    return commit if _SHA_RE.match(commit) else None


def platform_knowledge_version(
    knowledge: Optional[KnowledgeBase],
) -> InputVersion:
    """The platform knowledge a run held, by its verification dates (§4.1).

    Every loaded ``K-DST-*`` record, with the day it was last verified. A
    record without one is refused rather than recorded undated: Step 4 §8 rule
    8 requires the date on every one of them, so a register that has one
    without is a register no run started on.
    """

    if knowledge is None:
        return InputVersion.absent(
            InputKind.PLATFORM_KNOWLEDGE, NO_KNOWLEDGE_REGISTER
        )
    platform = [
        loaded
        for loaded in knowledge.records
        if loaded.identity.startswith(PLATFORM_RECORD_PREFIX)
    ]
    if not platform:
        return InputVersion.absent(
            InputKind.PLATFORM_KNOWLEDGE, NO_PLATFORM_KNOWLEDGE
        )

    verified: list[PlatformVerification] = []
    rows: list[list[str]] = []
    for loaded in sorted(platform, key=lambda item: item.identity):
        verified_on = loaded.record.verified_on
        if not verified_on:
            raise RunInputsError(
                f"{loaded.identity} carries no `verified_on`, and §4.1 records "
                "platform knowledge by its verification dates. Step 4 §8 rule "
                "8 requires the date, so this register is one no run started on"
            )
        verified.append(
            PlatformVerification(
                record_id=loaded.identity, verified_on=verified_on
            )
        )
        rows.append([loaded.identity, verified_on, loaded.digest])
    return InputVersion(
        kind=InputKind.PLATFORM_KNOWLEDGE,
        identities=tuple(entry.record_id for entry in verified),
        verified_on=tuple(verified),
        digest=_digest_over(CANONICAL_PLATFORM_SERIALIZATION, rows),
    )


def strength_ladder_version(
    knowledge: Optional[KnowledgeBase], *, register_dir: Optional[Path]
) -> InputVersion:
    """The strength ladder ID the run's claims were measured against (§4.1).

    The universal ladder, ``ladders/default.md`` (Step 4 §7), by its record ID
    and the digest of the file. A client may restrict it in its contract, and
    that restriction is part of the Client Contract input rather than a second
    ladder here: the client ladder has no identity of its own, it is a plan
    slot of a contract this manifest already records.
    """

    if knowledge is None or register_dir is None:
        return InputVersion.absent(
            InputKind.STRENGTH_LADDER, NO_KNOWLEDGE_REGISTER
        )
    path = Path(register_dir) / LADDERS_DIR_NAME / DEFAULT_LADDER_NAME
    ladder = next(
        (
            loaded
            for loaded in knowledge.records
            if Path(loaded.record.path) == path
        ),
        None,
    )
    if ladder is None:
        return InputVersion.absent(
            InputKind.STRENGTH_LADDER, NO_STRENGTH_LADDER
        )
    return InputVersion(
        kind=InputKind.STRENGTH_LADDER,
        identities=(ladder.identity,),
        digest=ladder.digest,
    )


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _loaded_files(knowledge: KnowledgeBase) -> list[list[str]]:
    """Every file the loader kept, as ``[id, version, digest]`` rows.

    Records and checks together, because a run is routed both and a check
    changed under it is as much a different register as a record is.
    """

    return [
        [item.identity, str(item.version), item.digest]
        for item in (*knowledge.records, *knowledge.checks)
    ]


def _digest_over(serialization: str, rows: Sequence[Sequence[str]]) -> str:
    """``sha256:<hex>`` over these rows, sorted, under a named payload shape.

    Sorted, so the value does not depend on the order the loader happened to
    read in; named, so a later change to what the rows mean is a new
    serialization rather than a silently different digest of the same name.
    """

    payload = json.dumps(
        {
            "serialization": serialization,
            "rows": sorted([list(row) for row in rows]),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
