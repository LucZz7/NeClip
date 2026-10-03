"""YouTube OAuth login + upload. Activates once the user provides a
Google Cloud OAuth client (Client ID + Secret). Until then every
function reports 'not configured' instead of crashing.
"""
import json
import os

from . import config

_configured = bool(config.YT_CLIENT_ID and config.YT_CLIENT_SECRET)


def is_configured() -> bool:
    # re-check env in case it was set after import
    return bool(os.getenv("YT_CLIENT_ID") and os.getenv("YT_CLIENT_SECRET"))


def auth_url(state: str = "") -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("YT_CLIENT_ID", config.YT_CLIENT_ID),
                "client_secret": os.getenv("YT_CLIENT_SECRET", config.YT_CLIENT_SECRET),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [config.PUBLIC_URL.rstrip("/") + "/oauth/callback"],
            }
        },
        scopes=config.YT_SCOPES,
    )
    flow.redirect_uri = config.PUBLIC_URL.rstrip("/") + "/oauth/callback"
    url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", state=state,
        include_granted_scopes="true",
    )
    return url


def exchange_code(code: str) -> dict:
    """Exchange the OAuth code for tokens; persist refresh token (0600)."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("YT_CLIENT_ID", config.YT_CLIENT_ID),
                "client_secret": os.getenv("YT_CLIENT_SECRET", config.YT_CLIENT_SECRET),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=config.YT_SCOPES,
    )
    flow.redirect_uri = config.PUBLIC_URL.rstrip("/") + "/oauth/callback"
    flow.fetch_token(code=code)
    creds = flow.credentials
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    fd = os.open(config.YT_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return {"ok": True}


def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    with open(config.YT_TOKEN_FILE) as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )
    return build("youtube", "v3", credentials=creds)


def is_logged_in() -> bool:
    return os.path.exists(config.YT_TOKEN_FILE)


# ---------------------------------------------------------------------------
# Device flow (google.com/device + code) — needs NO public URL / redirect URI.
# Use an OAuth client of type "TVs and Limited Input devices".
# ---------------------------------------------------------------------------

def _client_id() -> str:
    cid = os.getenv("YT_CLIENT_ID", config.YT_CLIENT_ID)
    if not cid:
        raise RuntimeError("YT_CLIENT_ID set nahi hai.")
    return cid


def device_flow_start() -> dict:
    """Step 1: returns {user_code, verification_url, device_code, expires_in}."""
    import json
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({
        "client_id": _client_id(),
        "scope": " ".join(config.YT_SCOPES),
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/device/code", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def device_flow_poll(device_code: str, interval: int = 5,
                     timeout: int = 600) -> dict:
    """Step 2: poll until the user approves on their phone. Saves tokens."""
    import json
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode({
        "client_id": _client_id(),
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }).encode()
    deadline = time.time() + timeout
    wait = max(interval, 5)
    while time.time() < deadline:
        time.sleep(wait)
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                tok = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                err = json.load(e).get("error", "")
            except Exception:
                err = ""
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                wait += 5
                continue
            if err in ("expired_token", "access_denied"):
                raise RuntimeError("Code expire ho gaya ya allow nahi hua. Dobara try karo.")
            raise RuntimeError(f"Google error: {err or e}")
        data = {
            "token": tok.get("access_token"),
            "refresh_token": tok.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": _client_id(),
            "client_secret": os.getenv("YT_CLIENT_SECRET", config.YT_CLIENT_SECRET) or None,
            "scopes": config.YT_SCOPES,
        }
        fd = os.open(config.YT_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        return {"ok": True}

    raise TimeoutError("10 minute ho gaye — code expire. Naya code lo.")


def channel_info():
    """Return the connected channel's title/thumbnail, or None."""
    if not is_logged_in():
        return None
    try:
        svc = _service()
        resp = svc.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return None
        snip = items[0]["snippet"]
        return {
            "title": snip.get("title"),
            "thumb": (snip.get("thumbnails", {}).get("default") or {}).get("url"),
        }
    except Exception:
        return None


def upload_short(video_path: str, title: str, description: str = "",
                 privacy: str = "public", progress_cb=None) -> dict:
    """Resumable upload of one Short. Returns {'video_id', 'url'}."""
    from googleapiclient.http import MediaFileUpload

    svc = _service()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": ["shorts"],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy,   # public | unlisted | private
            "madeForKids": False,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True,
                            chunksize=1024 * 1024)
    req = svc.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status and progress_cb:
            progress_cb(int(status.progress() * 100))
    vid = resp["id"]
    return {"video_id": vid, "url": f"https://www.youtube.com/shorts/{vid}"}
