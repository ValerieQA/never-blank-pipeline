import os
from src.utils.logger import get_logger

log = get_logger("env_validator")

# Variables required for each phase.
# Phase 0/1 only needs OpenAI to test the LLM client.
# All 20 variables are required for full pipeline execution.

PHASE_0 = [
    "NB_OPENAI_API_KEY",
    "NB_OPENAI_MODEL",
    "NB_OPENAI_EMBEDDING_MODEL",
]

PHASE_1 = PHASE_0 + [
    "NB_GOOGLE_SHEETS_CREDENTIALS_JSON",
    "NB_GOOGLE_SHEET_ID",
]

ALL = PHASE_1 + [
    "NB_CLOUDINARY_CLOUD_NAME",
    "NB_CLOUDINARY_API_KEY",
    "NB_CLOUDINARY_API_SECRET",
    "NB_WIX_API_KEY",
    "NB_WIX_SITE_ID",
    "NB_LINKEDIN_ACCESS_TOKEN",
    "NB_META_USER_TOKEN",
    "NB_META_IG_USER_ID",
    "NB_META_FB_PAGE_ID",
    "NB_META_FB_PAGE_TOKEN",
    "NB_THREADS_ACCESS_TOKEN",
    "NB_TELEGRAM_BOT_TOKEN",
    "NB_TELEGRAM_CHANNEL_ID",
]

PHASE_SETS = {
    "phase0": PHASE_0,
    "phase1": PHASE_1,
    "all": ALL,
}


def validate(phase: str = "all", strict: bool = True) -> dict:
    """
    Check that required environment variables are set.

    Returns a dict with:
      ok: bool
      missing: list[str]
      present: list[str]
    """
    required = PHASE_SETS.get(phase, ALL)
    missing = [v for v in required if not os.environ.get(v, "").strip()]
    present = [v for v in required if os.environ.get(v, "").strip()]

    if missing:
        msg = f"Missing required environment variables for {phase}: {', '.join(missing)}"
        if strict:
            raise EnvironmentError(msg)
        else:
            log.warning(msg)

    return {"ok": not missing, "missing": missing, "present": present}
