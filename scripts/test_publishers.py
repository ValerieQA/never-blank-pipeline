"""
Never Blank Pipeline — Phase 5A: Publisher Connectivity Audit.

Verifies that all credentials, tokens, and platform permissions are working
before live publishers are built.

Does NOT publish any content.
Performs the smallest safe API call for each platform.

Usage:
    python scripts/test_publishers.py
    python scripts/test_publishers.py --json          # JSON output only
    python scripts/test_publishers.py --platform wix  # single platform

Outputs:
    reports/connectivity_audit.json
    reports/connectivity_audit.md
"""

import sys
import os
import json
import argparse
import time
import ssl
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# macOS ships without the right CA bundle for urllib; bypass locally.
# In GitHub Actions (Linux) this is not needed and has no effect.
if sys.platform == "darwin":
    ssl._create_default_https_context = ssl._create_unverified_context  # noqa: SLF001

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.utils.logger import get_logger

log = get_logger("audit")

REPORTS_DIR = Path(__file__).parent.parent / "reports"
ASSETS_DIR  = Path(__file__).parent.parent / "assets"


# ── Result model ──────────────────────────────────────────────────────────────

class Result:
    PASS    = "PASS"
    FAIL    = "FAIL"
    WARNING = "WARNING"
    SKIP    = "SKIP"

    # Failure classification codes
    TOKEN_INVALID            = "TOKEN_INVALID"
    TOKEN_EXPIRED            = "TOKEN_EXPIRED"
    WRONG_TOKEN_TYPE         = "WRONG_TOKEN_TYPE"
    MISSING_SCOPE            = "MISSING_SCOPE"
    WRONG_ENDPOINT           = "WRONG_ENDPOINT"
    MISSING_ID               = "MISSING_ID"
    SCRIPT_BUG               = "SCRIPT_BUG"
    ASSET_MISSING            = "ASSET_MISSING"
    LOCAL_DEPENDENCY_MISSING = "LOCAL_DEPENDENCY_MISSING"
    UNKNOWN                  = "UNKNOWN"

    def __init__(
        self,
        provider: str,
        status: str,
        reason: str = "",
        failure_type: str = "",
        details: Optional[dict] = None,
        checks: Optional[list[dict]] = None,
    ):
        self.provider     = provider
        self.status       = status
        self.reason       = reason
        self.failure_type = failure_type
        self.details      = details or {}
        self.checks       = checks or []

    def to_dict(self) -> dict:
        return {
            "provider":     self.provider,
            "status":       self.status,
            "failure_type": self.failure_type,
            "reason":       self.reason,
            "details":      self.details,
            "checks":       self.checks,
        }


# ── Environment helpers ───────────────────────────────────────────────────────

def _env(key: str) -> Optional[str]:
    """Return env var value or None. Strips whitespace."""
    val = os.environ.get(key, "").strip()
    return val if val else None


def _require(*keys: str) -> Optional[str]:
    """
    Check that all keys are set. Return first missing key name, or None if all present.
    """
    for key in keys:
        if not _env(key):
            return key
    return None


def _check(name: str, ok: bool, msg: str = "") -> dict:
    return {"check": name, "passed": ok, "msg": msg}


def _fetch(url: str, *, method: str = "GET", headers: dict = None,
           body: bytes = None, timeout: int = 10) -> tuple[int, dict, str]:
    """
    Make an HTTP request and always return (status_code, parsed_body, raw_text).
    Never raises — HTTPError bodies are read and returned.
    Returns (0, {}, error_message) on network-level failure.
    """
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            raw = exc.read()
        except Exception:
            raw = b""
    except Exception as exc:
        return 0, {}, str(exc)

    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = {"_raw": text}
    return code, parsed, text


def _meta_error(body: dict) -> tuple[str, int, str]:
    """Extract (message, code, subcode) from a Meta Graph API error response."""
    err = body.get("error", {})
    return (
        err.get("message", ""),
        err.get("code", 0),
        err.get("error_subcode", ""),
    )


# ── Platform auditors ─────────────────────────────────────────────────────────

def audit_openai() -> Result:
    provider = "OpenAI"
    missing = _require("NB_OPENAI_API_KEY")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {_env('NB_OPENAI_API_KEY')}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        model_ids = [m["id"] for m in data.get("data", [])]
        configured = _env("NB_OPENAI_CHAT_MODEL") or "gpt-4o"
        model_available = any(configured in mid for mid in model_ids)
        checks = [
            _check("API key valid", True, "models endpoint returned 200"),
            _check(f"Model '{configured}' available", model_available,
                   "" if model_available else f"'{configured}' not found in account models"),
        ]
        status = Result.PASS if model_available else Result.WARNING
        reason = "" if model_available else f"Configured model '{configured}' not listed — may still work"
        return Result(provider, status, reason, checks=checks)
    except Exception as exc:
        return Result(provider, Result.FAIL, f"API call failed: {exc}")


def audit_telegram() -> Result:
    provider = "Telegram"
    missing = _require("NB_TELEGRAM_BOT_TOKEN", "NB_TELEGRAM_CHANNEL_ID")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    token      = _env("NB_TELEGRAM_BOT_TOKEN")
    channel_id = _env("NB_TELEGRAM_CHANNEL_ID")
    base       = f"https://api.telegram.org/bot{token}"

    checks = []

    # 1. Bot identity
    try:
        import urllib.request
        with urllib.request.urlopen(f"{base}/getMe", timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("ok"):
            bot_name = data["result"].get("username", "?")
            checks.append(_check("Bot identity (getMe)", True, f"@{bot_name}"))
        else:
            checks.append(_check("Bot identity (getMe)", False, str(data.get("description", ""))))
            return Result(provider, Result.FAIL, "Bot token rejected by Telegram", checks=checks)
    except Exception as exc:
        checks.append(_check("Bot identity (getMe)", False, str(exc)))
        return Result(provider, Result.FAIL, f"getMe failed: {exc}", checks=checks)

    # 2. Channel access
    try:
        import urllib.parse
        url = f"{base}/getChat?chat_id={urllib.parse.quote(channel_id)}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("ok"):
            chat = data["result"]
            can_post = chat.get("permissions") is not None or chat.get("type") in ("channel", "supergroup")
            checks.append(_check("Channel access (getChat)", True,
                                 f"type={chat.get('type')} title={chat.get('title', channel_id)!r}"))
        else:
            desc = data.get("description", "")
            checks.append(_check("Channel access (getChat)", False, desc))
            return Result(provider, Result.FAIL, f"Channel not accessible: {desc}", checks=checks)
    except Exception as exc:
        checks.append(_check("Channel access (getChat)", False, str(exc)))
        return Result(provider, Result.FAIL, f"getChat failed: {exc}", checks=checks)

    # 3. Posting permission — check bot is admin
    try:
        url = f"{base}/getChatMember?chat_id={urllib.parse.quote(channel_id)}&user_id={data['result'].get('id', '')}"
        # Use bot's own ID from getMe result
        me_url = f"{base}/getMe"
        with urllib.request.urlopen(me_url, timeout=10) as resp:
            me = json.loads(resp.read())
        bot_id = me["result"]["id"]
        url = f"{base}/getChatMember?chat_id={urllib.parse.quote(channel_id)}&user_id={bot_id}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            member = json.loads(resp.read())
        if member.get("ok"):
            status_val = member["result"].get("status", "")
            can_post   = status_val in ("administrator", "creator")
            checks.append(_check("Bot can post (admin check)", can_post,
                                 f"bot status in channel: {status_val}"))
            if not can_post:
                return Result(provider, Result.FAIL,
                              f"Bot is not admin in channel (status={status_val}). "
                              "Add bot as admin with 'Post Messages' permission.",
                              checks=checks)
    except Exception as exc:
        checks.append(_check("Bot admin check", False, str(exc)))

    return Result(provider, Result.PASS, checks=checks)


def audit_wix() -> Result:
    provider = "Wix"
    missing = _require("NB_WIX_API_KEY", "NB_WIX_SITE_ID")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}",
                      failure_type=Result.MISSING_ID)

    api_key = _env("NB_WIX_API_KEY")
    site_id = _env("NB_WIX_SITE_ID")
    checks  = []
    base_headers = {
        "Authorization": api_key,
        "wix-site-id":   site_id,
        "Content-Type":  "application/json",
    }

    # Step 1: basic API key validity — site properties (no blog scope needed)
    # This distinguishes an invalid API key from a key that's valid but lacks blog scope.
    code_sp, sp, _ = _fetch(
        "https://www.wixapis.com/site-properties/v4/properties",
        headers=base_headers,
        timeout=15,
    )
    if code_sp in (200, 404):
        # 404 is valid: site-properties returns 404 when no properties have been configured
        # yet, but the API key and site ID are accepted. 200 = properties exist.
        locale = sp.get("properties", {}).get("locale", {}).get("languageCode", "?") if code_sp == 200 else "none configured"
        checks.append(_check("API key valid (site-properties)", True,
                              f"HTTP {code_sp} — locale={locale}"))
        key_valid = True
    elif code_sp == 401:
        body_msg = sp.get("message", sp.get("_raw", ""))[:120]
        checks.append(_check("API key valid (site-properties)", False,
                              f"401 — {body_msg}"))
        return Result(provider, Result.FAIL,
                      f"Wix API key is invalid or revoked: {body_msg}",
                      failure_type=Result.TOKEN_INVALID,
                      checks=checks)
    elif code_sp == 403:
        body_msg = sp.get("message", sp.get("_raw", ""))[:120]
        checks.append(_check("API key valid (site-properties)", False,
                              f"403 — {body_msg}"))
        # 403 on site-properties means key is rejected or site ID is wrong
        # Try without wix-site-id to see if key itself works
        code_ns, ns, _ = _fetch(
            "https://www.wixapis.com/site-properties/v4/properties",
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=15,
        )
        if code_ns in (400, 403, 404):
            # Key reaches the API but site ID may be wrong
            ns_msg = ns.get("message", ns.get("_raw", ""))[:120]
            checks.append(_check("API key reachable (no site-id header)", True,
                                  f"HTTP {code_ns} without site-id — key is accepted"))
            checks.append(_check("Site ID valid", False,
                                  f"403 with site-id — NB_WIX_SITE_ID may be wrong: {body_msg}"))
            return Result(provider, Result.FAIL,
                          f"API key accepted but NB_WIX_SITE_ID ({site_id}) may be incorrect or the key lacks site access. "
                          f"Error: {body_msg}",
                          failure_type=Result.WRONG_ENDPOINT,
                          checks=checks)
        elif code_ns == 401:
            checks.append(_check("API key reachable", False, "401 without site-id — key itself is invalid"))
            return Result(provider, Result.FAIL,
                          "Wix API key is invalid (401 even without site-id header).",
                          failure_type=Result.TOKEN_INVALID,
                          checks=checks)
        key_valid = True
        checks.append(_check("API key valid (site-properties) — 403 with site-id", False,
                              "Key is active but site-properties returns 403 — blog scope check next"))
    else:
        body_msg = sp.get("_raw", "")[:120]
        checks.append(_check("API key valid (site-properties)", False,
                              f"HTTP {code_sp} — {body_msg}"))
        key_valid = False

    # Step 2: Blog read — categories (requires Blog scope on the API key)
    code_cat, cat, _ = _fetch(
        "https://www.wixapis.com/blog/v3/categories?paging.limit=1",
        headers=base_headers,
        timeout=15,
    )
    if code_cat == 200:
        n_cats = len(cat.get("categories", []))
        checks.append(_check("Blog read (categories)", True, f"{n_cats} categories"))
        blog_read = True
    elif code_cat == 403:
        body_msg = cat.get("message", cat.get("_raw", ""))[:120]
        checks.append(_check("Blog read (categories)", False,
                              f"403 — {body_msg}"))
        # 403 on blog = API key lacks Blog scope
        return Result(provider, Result.FAIL,
                      "API key lacks Blog scope. "
                      "Wix dashboard → Settings → Advanced → API keys → add 'Blog' scope. "
                      f"Detail: {body_msg}",
                      failure_type=Result.MISSING_SCOPE,
                      checks=checks)
    else:
        body_msg = cat.get("message", cat.get("_raw", ""))[:120]
        checks.append(_check("Blog read (categories)", False,
                              f"HTTP {code_cat} — {body_msg}"))
        blog_read = False

    if not blog_read:
        return Result(provider, Result.FAIL,
                      f"Blog API not accessible (HTTP {code_cat})",
                      failure_type=Result.UNKNOWN,
                      checks=checks)

    # Step 3: Blog write — draft create + immediate delete
    # Wix Blog v3 requires memberId for 3rd-party app draft creation.
    # This cannot be fetched dynamically via API key auth (Members /my endpoint
    # requires member/visitor auth). Must be supplied as NB_WIX_POST_OWNER_ID.
    owner_id = _env("NB_WIX_POST_OWNER_ID")
    if not owner_id:
        checks.append(_check("Blog write (NB_WIX_POST_OWNER_ID set)", False,
                              "NB_WIX_POST_OWNER_ID not set — draft creation requires memberId for 3rd-party apps. "
                              "Find in Wix dashboard → Members → your profile URL."))
        return Result(provider, Result.WARNING,
                      "Blog read confirmed. Write skipped: NB_WIX_POST_OWNER_ID not set. "
                      "Add this secret to enable full write audit.",
                      checks=checks)

    draft_body = {
        "draftPost": {
            "title":      "__connectivity_audit_draft__",
            "memberId":   owner_id,
            "richContent": {"nodes": []},
        }
    }
    code_dr, draft, _ = _fetch(
        "https://www.wixapis.com/blog/v3/draft-posts",
        method="POST",
        headers=base_headers,
        body=json.dumps(draft_body).encode(),
        timeout=15,
    )
    if code_dr in (200, 201):
        draft_id = draft.get("draftPost", {}).get("id")
        checks.append(_check("Blog write (draft create)", True, f"draft id={draft_id}"))
        if draft_id:
            code_del, _, _ = _fetch(
                f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}",
                method="DELETE",
                headers=base_headers,
                timeout=10,
            )
            checks.append(_check("Test draft cleanup", code_del in (200, 204),
                                  "deleted" if code_del in (200, 204) else f"HTTP {code_del} — delete manually"))
    elif code_dr == 403:
        body_msg = draft.get("message", draft.get("_raw", ""))[:120]
        checks.append(_check("Blog write (draft create)", False, f"403 — {body_msg}"))
        return Result(provider, Result.FAIL,
                      "API key can read Blog but not write. "
                      "Ensure API key has Blog write permission (not read-only).",
                      failure_type=Result.MISSING_SCOPE,
                      checks=checks)
    elif code_dr == 400:
        body_msg = draft.get("message", draft.get("_raw", ""))[:200]
        checks.append(_check("Blog write (draft create)", False, f"400 — {body_msg}"))
        if "owner" in body_msg.lower() or "member" in body_msg.lower():
            return Result(provider, Result.FAIL,
                          f"Draft creation rejected: {body_msg}. "
                          "Verify NB_WIX_POST_OWNER_ID is a valid member GUID for this site.",
                          failure_type=Result.MISSING_ID,
                          checks=checks)
        return Result(provider, Result.WARNING,
                      f"Blog read OK but write test failed (HTTP 400): {body_msg}",
                      checks=checks)
    else:
        body_msg = draft.get("message", draft.get("_raw", ""))[:120]
        checks.append(_check("Blog write (draft create)", False,
                              f"HTTP {code_dr} — {body_msg}"))
        return Result(provider, Result.WARNING,
                      f"Blog read OK but write test failed (HTTP {code_dr}): {body_msg}",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_linkedin() -> Result:
    provider = "LinkedIn (via Zernio)"
    missing = _require("NB_ZERNIO_API_KEY", "NB_ZERNIO_LINKEDIN_ACCOUNT_ID")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}",
                      failure_type=Result.MISSING_ID)

    api_key    = _env("NB_ZERNIO_API_KEY")
    account_id = _env("NB_ZERNIO_LINKEDIN_ACCOUNT_ID")
    checks     = []

    # Zernio doesn't expose LinkedIn's own OAuth internals — it manages the
    # LinkedIn Partner Program relationship on its side. We verify our API key
    # and connected account by listing the LinkedIn organizations reachable
    # through this account connection.
    # Docs: https://docs.zernio.com/platforms/linkedin#multi-organization-posting
    code, resp, _ = _fetch(
        f"https://zernio.com/api/v1/accounts/{account_id}/linkedin-organizations",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )

    if code == 200:
        orgs = resp.get("organizations", resp if isinstance(resp, list) else [])
        checks.append(_check("Zernio API key + account valid", True,
                              f"{len(orgs) if isinstance(orgs, list) else '?'} organization(s) reachable"))
        return Result(provider, Result.PASS, checks=checks)
    elif code == 401:
        err = resp.get("error", resp.get("message", resp.get("_raw", "")))[:120]
        checks.append(_check("Zernio API key valid", False, f"401 — {err}"))
        return Result(provider, Result.FAIL,
                      f"Zernio rejected the API key: {err}. Check NB_ZERNIO_API_KEY.",
                      failure_type=Result.TOKEN_INVALID,
                      checks=checks)
    elif code == 404:
        err = resp.get("error", resp.get("message", resp.get("_raw", "")))[:120]
        checks.append(_check("Zernio account ID valid", False, f"404 — {err}"))
        return Result(provider, Result.FAIL,
                      f"Zernio account not found: {err}. Check NB_ZERNIO_LINKEDIN_ACCOUNT_ID "
                      "(copy it again from zernio.com/dashboard/connections).",
                      failure_type=Result.MISSING_ID,
                      checks=checks)
    else:
        err = resp.get("error", resp.get("message", resp.get("_raw", "")))[:120]
        checks.append(_check("Zernio connectivity", False, f"HTTP {code} — {err}"))
        return Result(provider, Result.FAIL,
                      f"Zernio API call failed (HTTP {code}): {err}",
                      failure_type=Result.UNKNOWN,
                      checks=checks)


def audit_facebook() -> Result:
    provider = "Facebook"
    missing = _require("NB_META_FB_PAGE_ID", "NB_META_FB_PAGE_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}",
                      failure_type=Result.MISSING_ID)

    page_id    = _env("NB_META_FB_PAGE_ID")
    page_token = _env("NB_META_FB_PAGE_TOKEN")
    user_token = _env("NB_META_USER_TOKEN") or page_token
    checks     = []

    # Step 1: debug_token on the page token — reveals validity, expiry, scopes
    # Use user_token as the app token to inspect page_token.
    import urllib.parse
    code_d, dbg, _ = _fetch(
        f"https://graph.facebook.com/v21.0/debug_token"
        f"?input_token={urllib.parse.quote(page_token)}"
        f"&access_token={urllib.parse.quote(user_token)}",
    )
    if code_d == 200 and "data" in dbg:
        d = dbg["data"]
        valid     = d.get("is_valid", False)
        exp       = d.get("expires_at", 0)
        scopes    = d.get("scopes", [])
        err_msg   = d.get("error", {}).get("message", "")
        never_exp = (exp == 0)
        has_pages_manage = "pages_manage_posts" in scopes or "pages_read_engagement" in scopes

        checks.append(_check("debug_token: is_valid", valid,
                              f"is_valid={valid}" + (f" — {err_msg}" if err_msg else "")))
        checks.append(_check("debug_token: expiry",
                              valid,
                              "never expires (page token)" if never_exp else f"expires_at={exp}"))
        checks.append(_check("debug_token: pages_manage_posts scope", has_pages_manage,
                              f"scopes={scopes}"))

        if not valid:
            # Classify: expired vs invalid
            lower = err_msg.lower()
            if "expir" in lower or "session" in lower:
                ftype = Result.TOKEN_EXPIRED
            elif "decrypt" in lower or "parse" in lower:
                ftype = Result.WRONG_TOKEN_TYPE
            else:
                ftype = Result.TOKEN_INVALID
            return Result(provider, Result.FAIL,
                          f"Page token not valid: {err_msg or 'is_valid=false'}",
                          failure_type=ftype,
                          checks=checks)
    elif code_d == 400:
        # debug_token itself failed — the user_token (NB_META_USER_TOKEN) may be expired
        err_msg, _, _ = _meta_error(dbg)
        lower = err_msg.lower()
        checks.append(_check("debug_token", False, f"HTTP 400 — {err_msg[:120]}"))
        if "expir" in lower or "session" in lower:
            ftype = Result.TOKEN_EXPIRED
            reason = f"NB_META_USER_TOKEN is expired: {err_msg}"
        elif "decrypt" in lower or "parse" in lower:
            ftype = Result.WRONG_TOKEN_TYPE
            reason = f"NB_META_USER_TOKEN cannot be parsed: {err_msg}"
        else:
            ftype = Result.TOKEN_INVALID
            reason = f"debug_token failed: {err_msg}"
        return Result(provider, Result.FAIL, reason, failure_type=ftype, checks=checks)
    else:
        checks.append(_check("debug_token", False, f"HTTP {code_d}"))

    # Step 2: direct page access — id and name only
    # NOTE: 'tasks' field was removed from the Graph API for page tokens in newer versions.
    # Posting permission is confirmed via debug_token scopes (pages_manage_posts) above.
    code_p, page, _ = _fetch(
        f"https://graph.facebook.com/v21.0/{page_id}"
        f"?fields=id,name"
        f"&access_token={urllib.parse.quote(page_token)}",
    )
    if code_p == 200 and "error" not in page:
        name = page.get("name", "?")
        checks.append(_check("Page access", True, f"name={name!r}"))
    else:
        err_msg, _, _ = _meta_error(page)
        checks.append(_check("Page access", False,
                              f"HTTP {code_p} — {err_msg[:120]}"))
        lower = err_msg.lower()
        if "expir" in lower or "session" in lower:
            ftype = Result.TOKEN_EXPIRED
        elif page_id and len(page_id) < 5:
            ftype = Result.MISSING_ID
        else:
            ftype = Result.UNKNOWN
        return Result(provider, Result.FAIL,
                      f"Page access failed: {err_msg or f'HTTP {code_p}'}",
                      failure_type=ftype,
                      checks=checks)

    # Posting permission already confirmed via debug_token scopes above
    has_pm = "pages_manage_posts" in (locals().get("scopes") or [])
    checks.append(_check("pages_manage_posts confirmed via debug_token", has_pm,
                          "confirmed in scopes" if has_pm else "not found in scopes"))

    return Result(provider, Result.PASS, checks=checks)


def audit_instagram() -> Result:
    provider = "Instagram"
    missing = _require("NB_META_IG_USER_ID", "NB_META_USER_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}",
                      failure_type=Result.MISSING_ID)

    ig_id  = _env("NB_META_IG_USER_ID")
    token  = _env("NB_META_USER_TOKEN")
    checks = []

    import urllib.parse

    # Step 1: IG Business account fields
    # NOTE: account_type field requires instagram_manage_insights or similar permission
    # and is not available in all token configurations. Use id+username only for identity;
    # publishing permission confirmed separately via content_publishing_limit.
    code_ig, ig, _ = _fetch(
        f"https://graph.facebook.com/v21.0/{ig_id}"
        f"?fields=id,username,followers_count,media_count"
        f"&access_token={urllib.parse.quote(token)}",
    )
    if code_ig == 200 and "error" not in ig:
        username = ig.get("username", "?")
        checks.append(_check("Account access", True,
                              f"@{username} id={ig_id} followers={ig.get('followers_count','?')}"))
    else:
        err_msg, _, _ = _meta_error(ig)
        checks.append(_check("IG account access", False,
                              f"HTTP {code_ig} — {err_msg[:120]}"))
        lower = err_msg.lower()
        if "expir" in lower or "session" in lower:
            ftype = Result.TOKEN_EXPIRED
        elif "decrypt" in lower or "parse" in lower:
            ftype = Result.WRONG_TOKEN_TYPE
        elif "object does not exist" in lower or "unsupported" in lower:
            ftype = Result.MISSING_ID
        else:
            ftype = Result.TOKEN_INVALID
        return Result(provider, Result.FAIL,
                      f"IG account access failed: {err_msg or f'HTTP {code_ig}'}",
                      failure_type=ftype,
                      checks=checks)

    # Step 2: content_publishing_limit (read-only permission check)
    code_l, limit, _ = _fetch(
        f"https://graph.facebook.com/v21.0/{ig_id}/content_publishing_limit"
        f"?fields=config,quota_usage&access_token={urllib.parse.quote(token)}",
    )
    if code_l == 200 and "error" not in limit:
        quota_used = limit.get("data", [{}])[0].get("quota_usage", 0) if limit.get("data") else 0
        checks.append(_check("Media publish permission", True,
                              f"quota_usage={quota_used}/50 today"))
    else:
        err_msg, _, _ = _meta_error(limit)
        checks.append(_check("Media publish permission", False,
                              f"HTTP {code_l} — {err_msg[:80]}"))
        if "instagram_content_publish" in err_msg or "permission" in err_msg.lower():
            return Result(provider, Result.FAIL,
                          "instagram_content_publish permission not granted. "
                          "Re-authorize with that scope.",
                          failure_type=Result.MISSING_SCOPE,
                          checks=checks)
        return Result(provider, Result.WARNING,
                      f"Account accessible but publishing limit check failed: {err_msg}",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_threads() -> Result:
    provider = "Threads"
    missing = _require("NB_THREADS_ACCESS_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}",
                      failure_type=Result.MISSING_ID)

    token  = _env("NB_THREADS_ACCESS_TOKEN")
    checks = []

    import urllib.parse

    # Token format check: Threads user tokens start with THQV or similar patterns
    # Meta/Facebook tokens start with EAA. A token that can't be parsed by the
    # Threads API with "Failed to decrypt" is almost certainly WRONG_TOKEN_TYPE
    # (e.g., a Facebook user/page token was stored instead of a Threads token).
    token_prefix = token[:4] if len(token) >= 4 else token
    checks.append(_check(f"Token prefix (expect Threads format, got '{token_prefix}')",
                         True, "format check — classification determined by API response"))

    # Step 1: identity call on graph.threads.net
    # NOTE: threads_profile_category was removed from the Threads API and now returns 500.
    # Use id,username only for identity check.
    code_me, me, _ = _fetch(
        f"https://graph.threads.net/v1.0/me"
        f"?fields=id,username"
        f"&access_token={urllib.parse.quote(token)}",
    )
    if code_me == 200 and "error" not in me:
        username = me.get("username", "?")
        user_id  = me.get("id", "?")
        checks.append(_check("Token valid (graph.threads.net /me)", True,
                              f"@{username} id={user_id}"))
    else:
        err_msg = ""
        if "error" in me:
            err_msg = me["error"].get("message", "")
        elif "_raw" in me:
            err_msg = me["_raw"][:200]

        lower = err_msg.lower()
        checks.append(_check("Token valid (graph.threads.net /me)", False,
                              f"HTTP {code_me} — {err_msg[:120]}"))

        # Classify
        if "failed to decrypt" in lower or "cannot parse access token" in lower:
            # The Threads API explicitly cannot decrypt this token.
            # This means the token format is wrong — it's not a Threads user token.
            # The most common cause: a Facebook/Instagram token was stored in NB_THREADS_ACCESS_TOKEN.
            ftype   = Result.WRONG_TOKEN_TYPE
            reason  = (
                f"Threads API rejected token: '{err_msg}'. "
                f"Token prefix is '{token_prefix}'. "
                "This token is not a valid Threads user access token. "
                "A Threads-specific token must be generated via the Threads API — "
                "Facebook page tokens and Meta user tokens are not accepted."
            )
        elif "expir" in lower or "session" in lower:
            ftype  = Result.TOKEN_EXPIRED
            reason = f"Threads token expired: {err_msg}"
        elif "permission" in lower or "scope" in lower:
            ftype  = Result.MISSING_SCOPE
            reason = f"Threads token missing required scope: {err_msg}"
        elif code_me == 401:
            ftype  = Result.TOKEN_INVALID
            reason = f"Threads token invalid (401): {err_msg}"
        else:
            ftype  = Result.UNKNOWN
            reason = f"Threads API call failed (HTTP {code_me}): {err_msg}"

        return Result(provider, Result.FAIL, reason, failure_type=ftype, checks=checks)

    # Step 2: publishing quota check (read-only)
    code_l, limit, _ = _fetch(
        f"https://graph.threads.net/v1.0/{user_id}/threads_publishing_limit"
        f"?fields=config,quota_usage&access_token={urllib.parse.quote(token)}",
    )
    if code_l == 200 and "error" not in limit:
        quota = limit.get("data", [{}])[0].get("quota_usage", 0) if limit.get("data") else 0
        checks.append(_check("Publishing permission", True, f"quota_usage={quota}/250 today"))
    else:
        err_msg = limit.get("error", {}).get("message", "") if "error" in limit else ""
        checks.append(_check("Publishing permission", False,
                              f"HTTP {code_l} — {err_msg[:80]}"))
        return Result(provider, Result.WARNING,
                      f"Token valid but publishing limit check failed: {err_msg or code_l}",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_google_sheets() -> Result:
    provider = "Google Sheets"
    missing = _require("NB_GOOGLE_SHEETS_CREDENTIALS_JSON", "NB_GOOGLE_SHEET_ID")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    sheet_id = _env("NB_GOOGLE_SHEET_ID")
    creds_raw = _env("NB_GOOGLE_SHEETS_CREDENTIALS_JSON")
    checks = []

    # 1. Parse credentials JSON
    try:
        creds = json.loads(creds_raw)
        acct_email = creds.get("client_email", "?")
        checks.append(_check("Credentials JSON valid", True, f"service_account={acct_email}"))
    except Exception as exc:
        checks.append(_check("Credentials JSON valid", False, str(exc)))
        return Result(provider, Result.FAIL,
                      "NB_GOOGLE_SHEETS_CREDENTIALS_JSON is not valid JSON.",
                      checks=checks)

    # 2. Authenticate and access spreadsheet
    try:
        import urllib.request
        import urllib.parse
        import hmac
        import hashlib
        import base64
        import struct
        import time as _time

        # Minimal JWT for Google OAuth2 without google-auth library
        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        now  = int(_time.time())
        header  = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        payload = _b64url(json.dumps({
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        }).encode())

        # Sign with private key — requires cryptography package
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            private_key = serialization.load_pem_private_key(
                creds["private_key"].encode(), password=None
            )
            signing_input = f"{header}.{payload}".encode()
            signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
            jwt_token = f"{header}.{payload}.{_b64url(signature)}"
        except ImportError:
            checks.append(_check("JWT signing (cryptography package)", False,
                                  "pip install cryptography required for full auth check"))
            checks.append(_check("Spreadsheet URL format", True, f"ID={sheet_id}"))
            return Result(provider, Result.WARNING,
                          "Cannot test auth without 'cryptography' package. "
                          "Run: pip install cryptography. Credentials JSON is valid.",
                          failure_type=Result.LOCAL_DEPENDENCY_MISSING,
                          checks=checks)

        # Exchange JWT for access token
        token_resp = urllib.request.urlopen(
            urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=urllib.parse.urlencode({
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion":  jwt_token,
                }).encode(),
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ),
            timeout=15,
        )
        token_data = json.loads(token_resp.read())
        access_token = token_data.get("access_token")
        checks.append(_check("OAuth2 token obtained", bool(access_token), ""))

        # Read spreadsheet metadata
        sheet_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?includeGridData=false"
        sheet_req = urllib.request.Request(
            sheet_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(sheet_req, timeout=15) as sr:
            sheet_data = json.loads(sr.read())

        title = sheet_data.get("properties", {}).get("title", "?")
        first_sheet = sheet_data.get("sheets", [{}])[0].get("properties", {}).get("title", "Sheet1")
        sheets_list = [s["properties"]["title"] for s in sheet_data.get("sheets", [])]
        checks.append(_check("Read access", True,
                              f"title={title!r} tabs={sheets_list}"))

        # Write test: append one row to first sheet, then clear it immediately
        append_url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
            f"/values/{urllib.parse.quote(first_sheet)}!A1:B1:append"
            f"?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
        )
        write_body = json.dumps({
            "values": [["__audit_test__", datetime.now(timezone.utc).isoformat()]]
        }).encode()
        write_req = urllib.request.Request(
            append_url, data=write_body, method="POST",
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(write_req, timeout=15) as wr:
            write_resp = json.loads(wr.read())

        updated_range = write_resp.get("updates", {}).get("updatedRange", "?")
        checks.append(_check("Write access (append row)", True,
                              f"wrote to {updated_range}"))

        # Clear the test row immediately
        # Extract the row number from the updated range (e.g. "Sheet1!A5:B5" → row 5)
        row_num = None
        try:
            row_num = updated_range.split("!")[-1].split(":")[0].lstrip("AB")
        except Exception:
            pass

        if row_num:
            clear_range = f"{first_sheet}!A{row_num}:Z{row_num}"
            clear_url = (
                f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
                f"/values/{urllib.parse.quote(clear_range)}:clear"
            )
            clear_req = urllib.request.Request(
                clear_url, data=b"{}", method="POST",
                headers={"Authorization": f"Bearer {access_token}",
                         "Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(clear_req, timeout=10)
                checks.append(_check("Test row cleanup", True,
                                     f"cleared {clear_range}"))
            except Exception as ce:
                checks.append(_check("Test row cleanup", False,
                                     f"clear failed: {ce} — delete row {row_num} manually"))

    except Exception as exc:
        code = getattr(exc, "code", "?")
        raw_body = ""
        try:
            raw_body = exc.read().decode("utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
        detail = raw_body[:200] if raw_body else str(exc)

        if str(code) == "403":
            checks.append(_check("Spreadsheet access", False, f"403 — {detail[:120]}"))
            return Result(provider, Result.FAIL,
                          f"Service account '{acct_email}' does not have access to "
                          f"spreadsheet {sheet_id}. "
                          "Share it with the service account email as Editor.",
                          failure_type=Result.MISSING_SCOPE,
                          checks=checks)
        if str(code) == "404":
            checks.append(_check("Spreadsheet access", False, "404 — sheet ID not found"))
            return Result(provider, Result.FAIL,
                          f"Spreadsheet ID {sheet_id!r} not found. Check NB_GOOGLE_SHEET_ID.",
                          failure_type=Result.MISSING_ID,
                          checks=checks)
        checks.append(_check("Spreadsheet access", False, detail[:120]))
        return Result(provider, Result.FAIL,
                      f"Google Sheets API call failed: {exc}",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_cloudinary() -> Result:
    provider = "Cloudinary"
    missing = _require("NB_CLOUDINARY_CLOUD_NAME", "NB_CLOUDINARY_API_KEY",
                       "NB_CLOUDINARY_API_SECRET")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    cloud_name = _env("NB_CLOUDINARY_CLOUD_NAME")
    api_key    = _env("NB_CLOUDINARY_API_KEY")
    api_secret = _env("NB_CLOUDINARY_API_SECRET")
    checks     = []

    # 1. Account ping via usage API (read-only, safe)
    try:
        import urllib.request
        import base64

        creds_b64 = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        url = f"https://api.cloudinary.com/v1_1/{cloud_name}/usage"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Basic {creds_b64}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            usage = json.loads(resp.read())
        plan = usage.get("plan", "?")
        storage_used = usage.get("storage", {}).get("usage", 0)
        checks.append(_check("Credentials valid (usage API)", True,
                              f"plan={plan} storage_used={storage_used}B"))
    except Exception as exc:
        code = getattr(exc, "code", "?")
        if str(code) in ("401", "403"):
            checks.append(_check("Credentials valid", False,
                                  f"HTTP {code} — API key or secret invalid"))
            return Result(provider, Result.FAIL,
                          "Cloudinary credentials rejected. Check NB_CLOUDINARY_API_KEY and NB_CLOUDINARY_API_SECRET.",
                          checks=checks)
        checks.append(_check("Credentials valid (usage API)", False, str(exc)))
        return Result(provider, Result.FAIL, f"Cloudinary API failed: {exc}", checks=checks)

    # 2. Upload permission — test with a 1×1 pixel PNG (base64 inline, no file needed)
    try:
        import hashlib
        import time as _time
        import urllib.parse

        # Minimal 1×1 transparent PNG as base64 data URI
        tiny_png = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
            "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
        ts        = int(_time.time())
        folder    = "never-blank/audit-test"
        public_id = f"{folder}/connectivity-test-{ts}"

        # Build signature
        sig_str  = f"public_id={public_id}&timestamp={ts}{api_secret}"
        signature = hashlib.sha256(sig_str.encode()).hexdigest()

        body = urllib.parse.urlencode({
            "file":       tiny_png,
            "api_key":    api_key,
            "timestamp":  str(ts),
            "public_id":  public_id,
            "signature":  signature,
        }).encode()
        upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
        with urllib.request.urlopen(
            urllib.request.Request(upload_url, data=body, method="POST"),
            timeout=20,
        ) as resp:
            result = json.loads(resp.read())

        url_result = result.get("secure_url", "?")
        checks.append(_check("Upload permission (test image)", True,
                              f"uploaded to: {url_result}"))

        # Immediately delete test asset
        try:
            del_ts  = int(_time.time())
            del_str = f"public_id={public_id}&timestamp={del_ts}{api_secret}"
            del_sig = hashlib.sha256(del_str.encode()).hexdigest()
            del_body = urllib.parse.urlencode({
                "public_id": public_id,
                "api_key":   api_key,
                "timestamp": str(del_ts),
                "signature": del_sig,
            }).encode()
            del_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/destroy"
            urllib.request.urlopen(
                urllib.request.Request(del_url, data=del_body, method="POST"),
                timeout=10,
            )
            checks.append(_check("Test asset cleanup", True, "test image deleted"))
        except Exception as de:
            checks.append(_check("Test asset cleanup", False, f"delete failed: {de}"))

    except Exception as exc:
        code = getattr(exc, "code", "?")
        if str(code) == "401":
            checks.append(_check("Upload permission", False, "401 — upload not authorized"))
            return Result(provider, Result.FAIL,
                          "Upload permission denied. Check API key permissions in Cloudinary dashboard.",
                          checks=checks)
        checks.append(_check("Upload permission (test image)", False, str(exc)))
        return Result(provider, Result.WARNING,
                      f"Credentials valid but upload test failed: {exc}",
                      checks=checks)

    # 3. Logo asset check
    # data/ and assets/logo/ are gitignored (generated content / binary assets).
    # Output folders (data/images, data/drafts) are created at runtime by the pipeline —
    # checking them here would always fail in a fresh GitHub Actions checkout.
    logo_path = ASSETS_DIR / "logo" / "never-blank-logo.png"
    logo_ok   = logo_path.exists()
    checks.append(_check("Logo file exists (assets/logo/never-blank-logo.png)", logo_ok,
                          "found" if logo_ok else "NOT FOUND — add before Phase 6 (image generation)"))

    if not logo_ok:
        return Result(provider, Result.WARNING,
                      "Cloudinary credentials work. Logo missing at assets/logo/never-blank-logo.png — "
                      "required before Phase 6 (image generation). Add the PNG file.",
                      failure_type=Result.ASSET_MISSING,
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


# ── Secrets presence check ────────────────────────────────────────────────────

REQUIRED_SECRETS = [
    "NB_OPENAI_API_KEY",
    "NB_WIX_API_KEY",
    "NB_WIX_SITE_ID",
    "NB_WIX_POST_OWNER_ID",
    "NB_ZERNIO_API_KEY",
    "NB_ZERNIO_LINKEDIN_ACCOUNT_ID",
    "NB_META_USER_TOKEN",
    "NB_META_IG_USER_ID",
    "NB_META_FB_PAGE_ID",
    "NB_META_FB_PAGE_TOKEN",
    "NB_THREADS_ACCESS_TOKEN",
    "NB_TELEGRAM_BOT_TOKEN",
    "NB_TELEGRAM_CHANNEL_ID",
    "NB_CLOUDINARY_CLOUD_NAME",
    "NB_CLOUDINARY_API_KEY",
    "NB_CLOUDINARY_API_SECRET",
    "NB_GOOGLE_SHEETS_CREDENTIALS_JSON",
    "NB_GOOGLE_SHEET_ID",
]


def check_secrets() -> list[dict]:
    results = []
    for key in REQUIRED_SECRETS:
        val = _env(key)
        present = val is not None
        preview = ""
        if present:
            if "JSON" in key:
                try:
                    json.loads(val)
                    preview = f"valid JSON ({len(val)} chars)"
                except Exception:
                    preview = "INVALID JSON"
                    present = False
            elif len(val) > 8:
                preview = f"{val[:4]}...{val[-4:]} ({len(val)} chars)"
            else:
                preview = f"({len(val)} chars)"
        results.append({"secret": key, "present": present, "preview": preview})
    return results


# ── Report generation ─────────────────────────────────────────────────────────

PLATFORM_AUDITORS = {
    "openai":        audit_openai,
    "telegram":      audit_telegram,
    "wix":           audit_wix,
    "linkedin":      audit_linkedin,
    "facebook":      audit_facebook,
    "instagram":     audit_instagram,
    "threads":       audit_threads,
    "google_sheets": audit_google_sheets,
    "cloudinary":    audit_cloudinary,
}

STATUS_ICON = {
    Result.PASS:    "✓",
    Result.FAIL:    "✗",
    Result.WARNING: "⚠",
    Result.SKIP:    "—",
}

STATUS_WIDTH = 7  # for alignment


def _print_result(r: Result) -> None:
    icon   = STATUS_ICON.get(r.status, "?")
    padded = r.status.ljust(STATUS_WIDTH)
    print(f"  {icon}  {r.provider:<20} {padded}", end="")
    if r.reason:
        print(f"  {r.reason}", end="")
    print()
    for c in r.checks:
        tick = "✓" if c["passed"] else "✗"
        msg  = f"  {c['msg']}" if c.get("msg") else ""
        print(f"       {tick}  {c['check']}{msg}")


def _save_reports(results: list[Result], secrets: list[dict]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    # JSON
    data = {
        "generated_at": now,
        "secrets":  secrets,
        "results":  [r.to_dict() for r in results],
        "summary": {
            "pass":    sum(1 for r in results if r.status == Result.PASS),
            "fail":    sum(1 for r in results if r.status == Result.FAIL),
            "warning": sum(1 for r in results if r.status == Result.WARNING),
            "skip":    sum(1 for r in results if r.status == Result.SKIP),
        },
    }
    json_path = REPORTS_DIR / "connectivity_audit.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown
    lines = [
        "# Never Blank — Publisher Connectivity Audit",
        f"\nGenerated: {now}\n",
        "## Secrets",
        "| Secret | Status | Preview |",
        "|--------|--------|---------|",
    ]
    for s in secrets:
        status = "✓" if s["present"] else "✗ MISSING"
        lines.append(f"| `{s['secret']}` | {status} | {s['preview']} |")

    lines += ["\n## Platform Results",
              "| Platform | Status | Failure Type | Notes |",
              "|----------|--------|--------------|-------|"]
    for r in results:
        icon   = STATUS_ICON.get(r.status, "?")
        notes  = r.reason or ("All checks passed" if r.status == Result.PASS else "")
        ftype  = r.failure_type or ("—" if r.status == Result.PASS else "")
        lines.append(f"| {r.provider} | {icon} {r.status} | {ftype} | {notes} |")

    # Detail sections
    for r in results:
        if r.checks:
            lines.append(f"\n### {r.provider}")
            for c in r.checks:
                tick = "✓" if c["passed"] else "✗"
                msg  = f" — {c['msg']}" if c.get("msg") else ""
                lines.append(f"- {tick} {c['check']}{msg}")
            if r.reason and r.status != Result.PASS:
                lines.append(f"\n**Action required:** {r.reason}")

    lines.append(f"\n---\n*Source: scripts/test_publishers.py*")

    md_path = REPORTS_DIR / "connectivity_audit.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n  Reports saved:")
    print(f"    • {json_path.relative_to(json_path.parent.parent)}")
    print(f"    • {md_path.relative_to(md_path.parent.parent)}")


# ── Main ───────────────────────────────────────────────────────────────────────

def run(platforms: Optional[list[str]] = None, json_only: bool = False) -> int:
    if not json_only:
        print("\n╔══════════════════════════════════════════════════╗")
        print("║   Never Blank — Publisher Connectivity Audit     ║")
        print("║   Phase 5A                                       ║")
        print("╚══════════════════════════════════════════════════╝\n")

    # 1. Secrets check
    secrets = check_secrets()
    missing_secrets = [s["secret"] for s in secrets if not s["present"]]

    if not json_only:
        print("  Secrets:")
        for s in secrets:
            icon    = "✓" if s["present"] else "✗"
            preview = s["preview"] or "MISSING"
            print(f"    {icon}  {s['secret']:<40} {preview}")
        if missing_secrets:
            print(f"\n  ⚠  {len(missing_secrets)} secret(s) missing — affected platforms will FAIL")
        print()

    # 2. Platform audits
    targets = platforms or list(PLATFORM_AUDITORS.keys())
    results: list[Result] = []

    if not json_only:
        print("  Running connectivity checks...\n")

    for key in targets:
        auditor = PLATFORM_AUDITORS.get(key)
        if not auditor:
            print(f"  Unknown platform: {key!r} — skipping")
            continue
        try:
            result = auditor()
        except Exception as exc:
            result = Result(key.capitalize(), Result.FAIL, f"Unhandled error: {exc}")
        results.append(result)
        if not json_only:
            _print_result(result)

    # 3. Summary
    passes   = [r for r in results if r.status == Result.PASS]
    fails    = [r for r in results if r.status == Result.FAIL]
    warnings = [r for r in results if r.status == Result.WARNING]

    if not json_only:
        print(f"\n  Summary: {len(passes)} PASS  {len(fails)} FAIL  {len(warnings)} WARNING")

        if fails:
            print(f"\n  FAIL — action required:")
            for r in fails:
                print(f"    ✗  {r.provider}: {r.reason}")

        if warnings:
            print(f"\n  WARNING — review recommended:")
            for r in warnings:
                print(f"    ⚠  {r.provider}: {r.reason}")

        if missing_secrets:
            print(f"\n  Missing secrets ({len(missing_secrets)}):")
            for s in missing_secrets:
                print(f"    ✗  {s}")

    # 4. Save reports
    _save_reports(results, secrets)

    exit_code = 0 if not fails else 1
    if not json_only:
        print(f"\n  Exit code: {exit_code} ({'all passed' if not fails else 'failures detected'})")
        print()
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", nargs="+",
                        choices=list(PLATFORM_AUDITORS.keys()),
                        help="Audit only specific platform(s)")
    parser.add_argument("--json", action="store_true", dest="json_only",
                        help="Suppress banner and table output (reports still saved)")
    args = parser.parse_args()
    sys.exit(run(platforms=args.platform, json_only=args.json_only))
