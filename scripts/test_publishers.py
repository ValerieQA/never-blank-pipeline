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
    if code_sp == 200:
        locale = sp.get("properties", {}).get("locale", {}).get("languageCode", "?")
        checks.append(_check("API key valid (site-properties)", True,
                              f"locale={locale}"))
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
    code_dr, draft, _ = _fetch(
        "https://www.wixapis.com/blog/v3/draft-posts",
        method="POST",
        headers=base_headers,
        body=json.dumps({
            "draftPost": {
                "title":      "__connectivity_audit_draft__",
                "richContent": {"nodes": []},
            }
        }).encode(),
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
    else:
        body_msg = draft.get("message", draft.get("_raw", ""))[:120]
        checks.append(_check("Blog write (draft create)", False,
                              f"HTTP {code_dr} — {body_msg}"))
        return Result(provider, Result.WARNING,
                      f"Blog read OK but write test failed (HTTP {code_dr}): {body_msg}",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_linkedin() -> Result:
    provider = "LinkedIn"
    missing = _require("NB_LINKEDIN_ACCESS_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}",
                      failure_type=Result.MISSING_ID)

    token  = _env("NB_LINKEDIN_ACCESS_TOKEN")
    checks = []

    # Step 1a: try /v2/me (works with r_liteprofile / profile scopes — standard OAuth2)
    # NOTE: /v2/userinfo is OpenID Connect; it requires the 'openid' scope and fails with
    # "userinfo.GET.NO_VERSION" when the token has only r_liteprofile. Always try /v2/me first.
    code_me, body_me, _ = _fetch(
        "https://api.linkedin.com/v2/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    me_ok = code_me == 200
    if me_ok:
        member_id = body_me.get("id", "?")
        fn = body_me.get("localizedFirstName", "?")
        checks.append(_check("Token valid (/v2/me)", True, f"id={member_id} firstName={fn!r}"))
    else:
        me_error = body_me.get("message", body_me.get("_raw", ""))
        checks.append(_check("Token valid (/v2/me)", False,
                              f"HTTP {code_me} — {me_error[:120]}"))

        # Step 1b: try /v2/userinfo (OpenID Connect — requires 'openid' scope)
        code_ui, body_ui, _ = _fetch(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        if code_ui == 200:
            sub  = body_ui.get("sub", "?")
            name = body_ui.get("name", body_ui.get("given_name", "?"))
            checks.append(_check("Token valid (/v2/userinfo)", True, f"name={name!r} sub={sub}"))
            checks.append(_check("Note: /v2/me returned 403 but /v2/userinfo passed", True,
                                  "Token has openid scope but not r_liteprofile — unusual"))
            me_ok = True
            member_id = sub
        else:
            ui_error = body_ui.get("message", body_ui.get("_raw", ""))
            checks.append(_check("Token valid (/v2/userinfo)", False,
                                  f"HTTP {code_ui} — {ui_error[:120]}"))

            # Classify the failure
            combined = f"{me_error} {ui_error}".lower()
            if code_me in (401, 403) and ("expire" in combined or "revoke" in combined
                                           or "invalid" in combined):
                ftype = Result.TOKEN_EXPIRED
            elif code_me == 403 and "permission" in combined:
                ftype = Result.MISSING_SCOPE
            elif "no_version" in combined or "not_enough_permissions" in combined:
                # Classic sign of WRONG_ENDPOINT (/v2/userinfo without openid scope)
                # but /v2/me also failed — real token problem
                ftype = Result.MISSING_SCOPE
            elif code_me in (401,):
                ftype = Result.TOKEN_INVALID
            else:
                ftype = Result.UNKNOWN

            return Result(provider, Result.FAIL,
                          f"/v2/me HTTP {code_me}: {me_error[:100]} | "
                          f"/v2/userinfo HTTP {code_ui}: {ui_error[:100]}",
                          failure_type=ftype,
                          checks=checks)

    # Step 2: introspect token for scopes and expiry
    import urllib.parse
    code_i, intro, _ = _fetch(
        "https://api.linkedin.com/v2/introspectToken",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        body=f"token={urllib.parse.quote(token)}".encode(),
    )
    if code_i == 200:
        scopes  = intro.get("scope", "")
        active  = intro.get("active", False)
        exp_at  = intro.get("expires_at", 0)
        has_post = "w_member_social" in scopes or "w_organization_social" in scopes
        checks.append(_check("Token active (introspect)", active,
                              f"active={active} expires_at={exp_at}"))
        checks.append(_check("Posting scope (w_member_social)", has_post,
                              f"scopes={scopes!r}"))
        if not active:
            return Result(provider, Result.FAIL,
                          "LinkedIn token is inactive (introspect says active=false). Re-authorize.",
                          failure_type=Result.TOKEN_EXPIRED,
                          checks=checks)
        if not has_post:
            return Result(provider, Result.FAIL,
                          "Token lacks w_member_social scope — cannot post. "
                          "Re-authorize with 'Share on LinkedIn' (w_member_social) permission.",
                          failure_type=Result.MISSING_SCOPE,
                          checks=checks)
    else:
        intro_err = intro.get("message", intro.get("_raw", ""))
        checks.append(_check("Scope check (introspect)", False,
                              f"HTTP {code_i} — {intro_err[:80]}"))
        return Result(provider, Result.WARNING,
                      "Token identity confirmed but posting scope could not be verified via introspect.",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


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

    # Step 2: direct page access (only if token appeared valid above)
    code_p, page, _ = _fetch(
        f"https://graph.facebook.com/v21.0/{page_id}"
        f"?fields=id,name,tasks"
        f"&access_token={urllib.parse.quote(page_token)}",
    )
    if code_p == 200 and "error" not in page:
        name  = page.get("name", "?")
        tasks = page.get("tasks", [])
        checks.append(_check("Page access", True, f"name={name!r}"))
        can_create = "CREATE_CONTENT" in tasks or not tasks
        checks.append(_check("Create content permission", can_create,
                              f"tasks={tasks}" if tasks else "tasks not returned — assume OK"))
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

    has_pm = any("manage" in s for s in (page.get("tasks") or []))
    if not has_pm and "scopes" in locals() and scopes and "pages_manage_posts" not in scopes:
        return Result(provider, Result.WARNING,
                      "pages_manage_posts scope not confirmed. Posts may be blocked.",
                      checks=checks)

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
    code_ig, ig, _ = _fetch(
        f"https://graph.facebook.com/v21.0/{ig_id}"
        f"?fields=id,name,username,account_type,followers_count,media_count"
        f"&access_token={urllib.parse.quote(token)}",
    )
    if code_ig == 200 and "error" not in ig:
        acct_type   = ig.get("account_type", "?")
        username    = ig.get("username", "?")
        is_business = acct_type in ("BUSINESS", "CREATOR")
        checks.append(_check("Account access", True, f"@{username} type={acct_type}"))
        checks.append(_check("Business/Creator account", is_business,
                              f"account_type={acct_type}"))
        if not is_business:
            return Result(provider, Result.FAIL,
                          f"Account type={acct_type}. Must be BUSINESS or CREATOR for API posting.",
                          failure_type=Result.MISSING_SCOPE,
                          checks=checks)
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
    code_me, me, _ = _fetch(
        f"https://graph.threads.net/v1.0/me"
        f"?fields=id,username,threads_profile_category"
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
            "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
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
        sheets_list = [s["properties"]["title"] for s in sheet_data.get("sheets", [])]
        checks.append(_check("Spreadsheet accessible", True,
                              f"title={title!r} tabs={sheets_list}"))

    except Exception as exc:
        code = getattr(exc, "code", "?")
        if str(code) == "403":
            checks.append(_check("Spreadsheet access", False,
                                  f"403 — service account not shared on spreadsheet"))
            return Result(provider, Result.FAIL,
                          f"Service account '{acct_email}' does not have access to spreadsheet {sheet_id}. "
                          "Share the spreadsheet with the service account email (Viewer or Editor).",
                          checks=checks)
        if str(code) == "404":
            checks.append(_check("Spreadsheet access", False, f"404 — sheet ID not found"))
            return Result(provider, Result.FAIL,
                          f"Spreadsheet ID {sheet_id!r} not found. "
                          "Check NB_GOOGLE_SHEET_ID.",
                          checks=checks)
        checks.append(_check("Spreadsheet access", False, str(exc)))
        return Result(provider, Result.FAIL, f"Google Sheets API call failed: {exc}", checks=checks)

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

    # 3. Image pipeline paths
    logo_path    = ASSETS_DIR / "logo" / "never-blank-logo.png"
    output_paths = [
        Path(__file__).parent.parent / "data" / "images",
        Path(__file__).parent.parent / "data" / "drafts",
    ]
    logo_ok = logo_path.exists()
    checks.append(_check("Logo file exists", logo_ok,
                          str(logo_path) if logo_ok else f"NOT FOUND: {logo_path}"))
    for p in output_paths:
        checks.append(_check(f"Output folder: {p.name}", p.exists(),
                              str(p) if p.exists() else f"NOT FOUND: {p}"))

    if not logo_ok:
        return Result(provider, Result.WARNING,
                      f"Cloudinary credentials work but logo not found at {logo_path}. "
                      "Add logo before generating images.",
                      failure_type=Result.ASSET_MISSING,
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


# ── Secrets presence check ────────────────────────────────────────────────────

REQUIRED_SECRETS = [
    "NB_OPENAI_API_KEY",
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
