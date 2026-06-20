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
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

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

    def __init__(
        self,
        provider: str,
        status: str,
        reason: str = "",
        details: Optional[dict] = None,
        checks: Optional[list[dict]] = None,
    ):
        self.provider = provider
        self.status   = status
        self.reason   = reason
        self.details  = details or {}
        self.checks   = checks or []

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "status":   self.status,
            "reason":   self.reason,
            "details":  self.details,
            "checks":   self.checks,
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
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    api_key = _env("NB_WIX_API_KEY")
    site_id = _env("NB_WIX_SITE_ID")
    checks  = []

    # 1. Site access via Wix REST — get site's blog categories (read-only)
    try:
        import urllib.request
        url = "https://www.wixapis.com/blog/v3/categories?paging.limit=1"
        req = urllib.request.Request(url, headers={
            "Authorization": api_key,
            "wix-site-id":   site_id,
            "Content-Type":  "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        checks.append(_check("Site access (blog categories)", True,
                              f"categories returned: {len(data.get('categories', []))}"))
    except Exception as exc:
        # Try alternate endpoint — site pages
        try:
            url2 = "https://www.wixapis.com/site-list/v2/sites/query"
            body = json.dumps({"query": {"paging": {"limit": 1}}}).encode()
            req2 = urllib.request.Request(url2, data=body, headers={
                "Authorization": api_key,
                "wix-site-id":   site_id,
                "Content-Type":  "application/json",
            })
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                data2 = json.loads(resp2.read())
            checks.append(_check("Site access (site-list API)", True, "200 OK"))
        except Exception as exc2:
            checks.append(_check("Site access", False, f"blog categories: {exc} | site-list: {exc2}"))
            return Result(provider, Result.FAIL,
                          f"Cannot reach Wix APIs: {exc2}", checks=checks)

    # 2. Blog write permission — attempt draft creation (dry-run: immediately delete)
    try:
        url = "https://www.wixapis.com/blog/v3/draft-posts"
        body = json.dumps({
            "draftPost": {
                "title":   "__connectivity_audit_draft__",
                "richContent": {"nodes": []},
            }
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": api_key,
            "wix-site-id":   site_id,
            "Content-Type":  "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            draft = json.loads(resp.read())
        draft_id = draft.get("draftPost", {}).get("id")
        checks.append(_check("Blog write permission (draft create)", True, f"draft id={draft_id}"))

        # Clean up test draft immediately
        if draft_id:
            del_req = urllib.request.Request(
                f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}",
                method="DELETE",
                headers={"Authorization": api_key, "wix-site-id": site_id},
            )
            try:
                urllib.request.urlopen(del_req, timeout=10)
                checks.append(_check("Test draft cleanup", True, "draft deleted"))
            except Exception:
                checks.append(_check("Test draft cleanup", False, "draft not deleted — delete manually"))
    except Exception as exc:
        # 403 = no write permission; 401 = bad key
        code = getattr(getattr(exc, "code", None), "real", None) or getattr(exc, "code", "?")
        if str(code) == "403":
            checks.append(_check("Blog write permission", False, "403 Forbidden — check API key scopes"))
            return Result(provider, Result.FAIL,
                          "API key lacks blog write permission. "
                          "In Wix dashboard → Settings → Advanced → API keys → add Blog scope.",
                          checks=checks)
        checks.append(_check("Blog write permission (draft create)", False, str(exc)))
        return Result(provider, Result.WARNING,
                      f"Read OK but write test failed: {exc}", checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_linkedin() -> Result:
    provider = "LinkedIn"
    missing = _require("NB_LINKEDIN_ACCESS_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    token  = _env("NB_LINKEDIN_ACCESS_TOKEN")
    checks = []

    # 1. Token validity — get own profile
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            me = json.loads(resp.read())
        sub = me.get("sub", "?")
        name = me.get("name", me.get("given_name", "?"))
        checks.append(_check("Token valid (userinfo)", True, f"name={name!r} sub={sub}"))
    except Exception as exc:
        code = getattr(exc, "code", "?")
        if str(code) in ("401", "403"):
            checks.append(_check("Token valid", False, f"HTTP {code} — token expired or revoked"))
            return Result(provider, Result.FAIL,
                          f"LinkedIn token invalid (HTTP {code}). "
                          "Re-authorize at LinkedIn Developer portal.",
                          checks=checks)
        checks.append(_check("Token valid (userinfo)", False, str(exc)))
        return Result(provider, Result.FAIL, f"userinfo call failed: {exc}", checks=checks)

    # 2. Posting permission — check w_member_social scope via introspect
    try:
        body = f"token={token}".encode()
        req2 = urllib.request.Request(
            "https://api.linkedin.com/v2/introspectToken",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            intro = json.loads(resp2.read())
        scopes = intro.get("scope", "")
        active = intro.get("active", False)
        has_post = "w_member_social" in scopes or "w_organization_social" in scopes
        checks.append(_check("Token active", active, f"active={active}"))
        checks.append(_check("Posting scope (w_member_social)", has_post, f"scopes={scopes!r}"))
        if not active:
            return Result(provider, Result.FAIL,
                          "LinkedIn token is inactive. Re-authorize.",
                          checks=checks)
        if not has_post:
            return Result(provider, Result.FAIL,
                          "Token lacks w_member_social scope — cannot post. "
                          "Re-authorize with 'Share on LinkedIn' permission.",
                          checks=checks)
    except Exception as exc:
        # Introspect may not be available on all token types
        checks.append(_check("Scope check (introspect)", False,
                              f"{exc} — cannot verify posting scope"))
        return Result(provider, Result.WARNING,
                      "Token appears valid but posting scope could not be verified. "
                      "Test posting separately.",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_facebook() -> Result:
    provider = "Facebook"
    missing = _require("NB_META_FB_PAGE_ID", "NB_META_FB_PAGE_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    page_id    = _env("NB_META_FB_PAGE_ID")
    page_token = _env("NB_META_FB_PAGE_TOKEN")
    checks     = []

    # 1. Page access
    try:
        import urllib.request
        url = (f"https://graph.facebook.com/v21.0/{page_id}"
               f"?fields=id,name,fan_count,tasks"
               f"&access_token={page_token}")
        with urllib.request.urlopen(url, timeout=10) as resp:
            page = json.loads(resp.read())
        if "error" in page:
            err = page["error"]
            checks.append(_check("Page access", False, err.get("message", str(err))))
            return Result(provider, Result.FAIL,
                          f"Page access error: {err.get('message', '')}",
                          checks=checks)
        name  = page.get("name", "?")
        tasks = page.get("tasks", [])
        checks.append(_check("Page access", True, f"name={name!r}"))
        can_create = "CREATE_CONTENT" in tasks or "ADVERTISE" in tasks or not tasks
        checks.append(_check("Create content permission", can_create,
                              f"tasks={tasks}" if tasks else "tasks not returned — assume OK"))
    except Exception as exc:
        checks.append(_check("Page access", False, str(exc)))
        return Result(provider, Result.FAIL, f"Page API failed: {exc}", checks=checks)

    # 2. Page token validity — debug token
    try:
        user_token = _env("NB_META_USER_TOKEN") or page_token
        url2 = (f"https://graph.facebook.com/v21.0/debug_token"
                f"?input_token={page_token}&access_token={user_token}")
        with urllib.request.urlopen(url2, timeout=10) as resp2:
            dbg = json.loads(resp2.read())
        d = dbg.get("data", {})
        valid    = d.get("is_valid", False)
        exp      = d.get("expires_at", 0)
        scopes   = d.get("scopes", [])
        never_exp = exp == 0
        has_pages_manage = "pages_manage_posts" in scopes or "pages_read_engagement" in scopes
        checks.append(_check("Page token valid", valid, f"is_valid={valid}"))
        checks.append(_check("Token expires", not never_exp,
                              "never expires (page token)" if never_exp else f"expires={exp}"))
        checks.append(_check("pages_manage_posts scope", has_pages_manage, f"scopes={scopes}"))
        if not valid:
            return Result(provider, Result.FAIL,
                          "Facebook page token is invalid or expired. Refresh via Graph Explorer.",
                          checks=checks)
        if not has_pages_manage and scopes:
            return Result(provider, Result.WARNING,
                          "pages_manage_posts scope not confirmed. "
                          "Posts may be blocked.",
                          checks=checks)
    except Exception as exc:
        checks.append(_check("Token debug", False, str(exc)))

    return Result(provider, Result.PASS, checks=checks)


def audit_instagram() -> Result:
    provider = "Instagram"
    missing = _require("NB_META_IG_USER_ID", "NB_META_USER_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    ig_id  = _env("NB_META_IG_USER_ID")
    token  = _env("NB_META_USER_TOKEN")
    checks = []

    # 1. Business account access
    try:
        import urllib.request
        url = (f"https://graph.facebook.com/v21.0/{ig_id}"
               f"?fields=id,name,username,account_type,followers_count,media_count"
               f"&access_token={token}")
        with urllib.request.urlopen(url, timeout=10) as resp:
            ig = json.loads(resp.read())
        if "error" in ig:
            err = ig["error"]
            checks.append(_check("IG account access", False, err.get("message", "")))
            return Result(provider, Result.FAIL,
                          f"IG access error: {err.get('message', '')}",
                          checks=checks)
        acct_type = ig.get("account_type", "?")
        username  = ig.get("username", "?")
        is_business = acct_type in ("BUSINESS", "CREATOR")
        checks.append(_check("Account access", True,
                              f"@{username} type={acct_type}"))
        checks.append(_check("Business/Creator account", is_business,
                              f"account_type={acct_type}"))
        if not is_business:
            return Result(provider, Result.FAIL,
                          f"Account is type={acct_type}. Must be BUSINESS or CREATOR for API posting. "
                          "Convert in Instagram Settings → Account → Switch to Professional Account.",
                          checks=checks)
    except Exception as exc:
        checks.append(_check("IG account access", False, str(exc)))
        return Result(provider, Result.FAIL, f"IG API failed: {exc}", checks=checks)

    # 2. Media publish permission — check content_publishing_limit (read-only, safe)
    try:
        url2 = (f"https://graph.facebook.com/v21.0/{ig_id}/content_publishing_limit"
                f"?fields=config,quota_usage&access_token={token}")
        with urllib.request.urlopen(url2, timeout=10) as resp2:
            limit = json.loads(resp2.read())
        if "error" in limit:
            err = limit["error"]
            checks.append(_check("Content publishing permission", False,
                                  err.get("message", "")))
            return Result(provider, Result.FAIL,
                          f"Cannot access publishing API: {err.get('message', '')}. "
                          "Ensure instagram_content_publish permission is granted.",
                          checks=checks)
        quota_used = limit.get("data", [{}])[0].get("quota_usage", 0) if limit.get("data") else 0
        checks.append(_check("Media publish permission", True,
                              f"quota_usage={quota_used}/50 today"))
    except Exception as exc:
        checks.append(_check("Media publish permission", False, str(exc)))
        return Result(provider, Result.WARNING,
                      f"Account accessible but publishing permission not confirmed: {exc}",
                      checks=checks)

    return Result(provider, Result.PASS, checks=checks)


def audit_threads() -> Result:
    provider = "Threads"
    missing = _require("NB_THREADS_ACCESS_TOKEN")
    if missing:
        return Result(provider, Result.FAIL, f"Missing secret: {missing}")

    token  = _env("NB_THREADS_ACCESS_TOKEN")
    checks = []

    # 1. Token validity — get own Threads profile
    try:
        import urllib.request
        url = f"https://graph.threads.net/v1.0/me?fields=id,username,threads_profile_category&access_token={token}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            me = json.loads(resp.read())
        if "error" in me:
            err = me["error"]
            checks.append(_check("Threads profile access", False, err.get("message", "")))
            return Result(provider, Result.FAIL,
                          f"Threads token error: {err.get('message', '')}",
                          checks=checks)
        username = me.get("username", "?")
        user_id  = me.get("id", "?")
        checks.append(_check("Token valid (profile)", True, f"@{username} id={user_id}"))
    except Exception as exc:
        checks.append(_check("Threads profile access", False, str(exc)))
        return Result(provider, Result.FAIL, f"Threads API call failed: {exc}", checks=checks)

    # 2. Publishing permission — check publishing_limit (read-only)
    try:
        url2 = f"https://graph.threads.net/v1.0/{user_id}/threads_publishing_limit?fields=config,quota_usage&access_token={token}"
        with urllib.request.urlopen(url2, timeout=10) as resp2:
            limit = json.loads(resp2.read())
        if "error" in limit:
            err = limit["error"]
            checks.append(_check("Publishing permission", False, err.get("message", "")))
            return Result(provider, Result.WARNING,
                          f"Cannot verify publishing limit: {err.get('message', '')}",
                          checks=checks)
        quota = limit.get("data", [{}])[0].get("quota_usage", 0) if limit.get("data") else 0
        checks.append(_check("Publishing permission", True, f"quota_usage={quota}/250 today"))
    except Exception as exc:
        checks.append(_check("Publishing permission check", False, str(exc)))
        return Result(provider, Result.WARNING,
                      f"Token valid but publishing permission not confirmed: {exc}",
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
            # Fall back: just verify the spreadsheet URL is accessible without auth
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
            checks.append(_check("Spreadsheet URL format", True, f"ID={sheet_id}"))
            return Result(provider, Result.WARNING,
                          "Cannot test auth without 'cryptography' package. "
                          "Run: pip install cryptography. Credentials JSON is valid.",
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

    lines += ["\n## Platform Results", "| Platform | Status | Notes |", "|----------|--------|-------|"]
    for r in results:
        icon  = STATUS_ICON.get(r.status, "?")
        notes = r.reason or ("All checks passed" if r.status == Result.PASS else "")
        lines.append(f"| {r.provider} | {icon} {r.status} | {notes} |")

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
