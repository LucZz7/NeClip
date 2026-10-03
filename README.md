# NeClip — AI YouTube Shorts Clipping App

Turn long videos into viral 9:16 YouTube Shorts. Paste a YouTube URL or upload a
video, AI finds the best moments, ranks them, and renders vertical clips ready
to upload.

## Stack

- **Frontend** (`web/`): mobile-first PWA, red/black/white glassmorphism UI,
  100% English, premium SVG icons, animations. Auth-first flow: connect YouTube
  before creating clips.
- **Backend** (`app/`): FastAPI — job queue, progress API, file upload,
  YouTube Device Flow login (`google.com/device`, no public URL needed),
  clip upload to YouTube.
- **Engine** (`engine/`): local clipping pipeline — `yt-dlp` download,
  `faster-whisper` transcription, Gemini/OpenAI highlight ranking,
  `ffmpeg` + OpenCV face-aware 9:16 auto-crop.

## Quick start (server)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r engine/requirements-local.txt
pip install fastapi uvicorn python-multipart google-genai
export LLM_PROVIDER=gemini
# Gemini key via env, or the app falls back to the vault CLI
# export GEMINI_API_KEY=your_key
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Deploy the backend (Render, free)

The GitHub Pages site is the static UI only. For real clipping + YouTube
login, deploy the backend once:

1. Sign up at https://render.com with GitHub.
2. Dashboard → **New +** → **Web Service** → select the `NeClip` repo.
3. Render detects `render.yaml` — keep the Free plan, click **Deploy**.
4. After deploy: **Environment** tab → add:
   - `GEMINI_API_KEY` = your Google AI Studio key
   - `YT_CLIENT_ID` = OAuth client ID of type **TVs and Limited Input devices**
     (Google Cloud Console → YouTube Data API v3 enabled)
5. Open your `https://neclip.onrender.com` URL on the phone — full app,
   YouTube connect via `google.com/device` code, no public redirect URL needed.

Note: free tier sleeps after inactivity — first load can take ~30 seconds.

## YouTube login (Device Flow)

1. Google Cloud Console: enable **YouTube Data API v3**.
2. Create OAuth credentials of type **TVs and Limited Input devices**.
3. In the app, tap **Connect YouTube**, open `google.com/device`,
   enter the code, tap Allow.

## Notes

- Use only your own or explicitly authorized footage.
- YouTube Data API quota: video uploads are quota-expensive (~6/day on the
  free tier).
- The `web/` folder is a standalone static PWA and can be hosted on any
  static host; the clipping engine needs the Python backend.
