"""ClipApp — AI YouTube Shorts clipper. Mobile-first web + PWA."""
import os
import shutil

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, jobs, youtube

app = FastAPI(title="ClipApp")
WEB_DIR = os.path.join(config.BASE_DIR, "web")


@app.get("/api/health")
def health():
    return {"ok": True, "youtube_login": youtube.is_logged_in(),
            "youtube_configured": youtube.is_configured()}


@app.get("/api/youtube/status")
def yt_status():
    return {"configured": youtube.is_configured(),
            "logged_in": youtube.is_logged_in(),
            "channel": youtube.channel_info() if youtube.is_logged_in() else None}


@app.get("/api/youtube/login")
def yt_login():
    # Device flow (google.com/device + code): needs NO public URL or
    # redirect URI. Requires YT_CLIENT_ID of an OAuth client of type
    # "TVs and Limited Input devices".
    if not os.getenv("YT_CLIENT_ID", config.YT_CLIENT_ID):
        return JSONResponse({"error": "YouTube abhi connect nahi hua — setup baki hai."},
                            status_code=400)
    try:
        flow = youtube.device_flow_start()
    except Exception as e:
        return JSONResponse({"error": f"Google error: {e}"}, status_code=400)
    # Poll Google in the background; the frontend polls /api/youtube/status.
    import threading
    t = threading.Thread(target=_device_poll_bg,
                         args=(flow["device_code"], flow.get("interval", 5)),
                         daemon=True)
    t.start()
    return {
        "user_code": flow["user_code"],
        "verification_url": flow.get("verification_url",
                                     "https://www.google.com/device"),
        "expires_in": flow.get("expires_in", 1800),
    }


def _device_poll_bg(device_code: str, interval: int):
    try:
        youtube.device_flow_poll(device_code, interval=interval, timeout=600)
    except Exception:
        pass


@app.get("/oauth/callback")
def oauth_callback(code: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/?login=failed")
    try:
        youtube.exchange_code(code)
        return RedirectResponse("/?login=ok")
    except Exception as e:
        return RedirectResponse(f"/?login=error")


@app.post("/api/jobs")
def create_job(source: str = Form(""), num_clips: int = Form(3),
               label: str = Form("")):
    source = (source or "").strip()
    if not source:
        return JSONResponse({"error": "Video ka link ya file do."}, status_code=400)
    num_clips = max(1, min(int(num_clips or 3), 10))
    job = jobs.create_job(source, num_clips, label or source[:60])
    return {"job_id": job["id"]}


@app.post("/api/jobs/upload")
async def create_job_upload(file: UploadFile = File(...),
                            num_clips: int = Form(3)):
    num_clips = max(1, min(int(num_clips or 3), 10))
    ext = os.path.splitext(file.filename or "")[1].lower() or ".mp4"
    if ext not in (".mp4", ".mov", ".mkv", ".webm"):
        return JSONResponse({"error": "Sirf video file (mp4/mov/mkv/webm)."},
                            status_code=400)
    tmp = os.path.join(config.UPLOADS_DIR, f"up_{os.urandom(6).hex()}{ext}")
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    job = jobs.create_job(tmp, num_clips, file.filename or "upload")
    return {"job_id": job["id"]}


@app.get("/api/jobs")
def jobs_list():
    out = []
    for j in jobs.list_jobs():
        out.append({k: j[k] for k in
                    ("id", "label", "status", "stage_label", "progress",
                     "error", "created")})
    return {"jobs": out}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    j = jobs.get_job(job_id)
    if not j:
        return JSONResponse({"error": "Job nahi mila."}, status_code=404)
    return {
        "id": j["id"], "label": j["label"], "status": j["status"],
        "stage": j["stage"], "stage_label": j["stage_label"],
        "progress": j["progress"], "log": j["log"][-30:],
        "result": j["result"], "error": j["error"],
    }


@app.get("/api/clips/{job_id}/{filename}")
def serve_clip(job_id: str, filename: str):
    path = os.path.normpath(os.path.join(config.JOBS_DIR, job_id, "clips", filename))
    base = os.path.normpath(os.path.join(config.JOBS_DIR, job_id, "clips"))
    if not path.startswith(base) or not os.path.isfile(path):
        return JSONResponse({"error": "File nahi mili."}, status_code=404)
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/upload/{job_id}/{idx}")
def upload_clip(job_id: str, idx: int, title: str = Form(""),
                description: str = Form(""), privacy: str = Form("public")):
    if not youtube.is_logged_in():
        return JSONResponse({"error": "Pehle YouTube se login karo."},
                            status_code=400)
    j = jobs.get_job(job_id)
    if not j or not j.get("result"):
        return JSONResponse({"error": "Job taiyaar nahi hai."}, status_code=400)
    shorts = j["result"].get("shorts", [])
    if idx < 0 or idx >= len(shorts) or not shorts[idx].get("file"):
        return JSONResponse({"error": "Clip nahi mili."}, status_code=404)
    path = os.path.join(config.JOBS_DIR, job_id, "clips", shorts[idx]["file"])
    try:
        res = youtube.upload_short(path, title or shorts[idx]["title"],
                                   description, privacy)
        return res
    except Exception as e:
        return JSONResponse({"error": f"Upload fail: {e}"}, status_code=500)


# Static frontend (must be last — catch-all would shadow /api otherwise,
# so we mount only for real files and serve index explicitly).
@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(WEB_DIR, "manifest.webmanifest"),
                        media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return FileResponse(os.path.join(WEB_DIR, "sw.js"),
                        media_type="application/javascript")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# Serve the web dir at root too, so relative asset paths work both locally
# and when the frontend is hosted under a subpath (e.g. GitHub Pages).
# Registered last: explicit /api routes and / above take precedence.
app.mount("/", StaticFiles(directory=WEB_DIR, html=False), name="web")
