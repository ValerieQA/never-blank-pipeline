import re
from pathlib import Path
import yaml
from src.utils.logger import get_logger

log = get_logger("config_loader")

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def load_yaml(path: str | Path) -> dict:
    """
    Load a YAML file, resolving a relative path against CONFIG_DIR.

    Returns the parsed mapping, or {} for an empty file. A missing file
    raises FileNotFoundError naming both what was asked for and the
    absolute path that was actually opened.
    """
    p = Path(path)
    resolved_against_config_dir = not p.is_absolute()
    if resolved_against_config_dir:
        p = CONFIG_DIR / p
    try:
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError as exc:
        where = (
            f"'{path}' is relative, so it was resolved against the "
            f"configuration directory and looked for at {p}"
            if resolved_against_config_dir
            else f"'{path}' is absolute, so it was opened as given"
        )
        raise FileNotFoundError(
            exc.errno, f"config file not found — {where}", str(p)
        ) from exc


def load_prompt(name: str, variables: dict | None = None) -> dict:
    """
    Load a prompt template from config/prompts/{name}.yaml and fill
    {variable} placeholders with values from the variables dict.

    Returns a dict with at minimum: system, user, name, status.
    Raises ValueError if the prompt is marked status: not_needed.
    """
    path = CONFIG_DIR / "prompts" / f"{name}.yaml"
    data = load_yaml(path)

    if data.get("status") == "not_needed":
        raise ValueError(
            f"Prompt '{name}' is not used in V1 (status: not_needed). "
            f"Reason: {data.get('decision', 'see prompt file')}"
        )

    status = data.get("status", "unknown")
    if status == "stub":
        log.warning("Prompt '%s' is still a stub — system/user content is placeholder", name)
    elif status == "ready":
        log.debug("Prompt '%s' loaded (status=ready)", name)

    if variables:
        system = data.get("system", "")
        user = data.get("user", "")
        for key, value in variables.items():
            system = system.replace("{" + key + "}", str(value))
            user = user.replace("{" + key + "}", str(value))
        data["system"] = system
        data["user"] = user

    return data


def load_brand() -> dict:
    return load_yaml("brand.yaml")


def load_strategy() -> dict:
    return load_yaml("strategy.yaml")


def load_quality() -> dict:
    return load_yaml("quality.yaml")


def load_platforms() -> dict:
    return load_yaml("platforms.yaml")


def load_intelligence() -> dict:
    return load_yaml("intelligence.yaml")
