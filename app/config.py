"""ClipApp settings — everything comes from environment, nothing hardcoded."""
import os

# Sanitize proxy bypass lists: bracketed IPv6 entries (e.g. "[::1]") crash
# httpx's proxy-pattern parsing inside huggingface_hub/faster-whisper.
for _k in ("no_proxy", "NO_PROXY"):
    _v = os.environ.get(_k)
    if _v:
        os.environ[_k] = ",".join(p for p in _v.split(",") if "[" not in p)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("CLIPAPP_DATA", os.path.join(BASE_DIR, "data"))
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Public base URL of this app (the cloudflared tunnel URL). Set at runtime.
PUBLIC_URL = os.getenv("CLIPAPP_PUBLIC_URL", "http://localhost:8000")

# YouTube OAuth (user supplies these from Google Cloud Console)
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "")
YT_TOKEN_FILE = os.getenv("YT_TOKEN_FILE", os.path.join(DATA_DIR, "yt_token.json"))
YT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# Clipping engine
ENGINE_DIR = os.path.join(BASE_DIR, "engine")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base")
