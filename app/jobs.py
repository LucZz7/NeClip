"""Simple in-memory job queue with a background worker thread."""
import os
import threading
import time
import uuid

from . import config
from .clip_engine import STAGES, run_clip_job

_jobs = {}
_lock = threading.Lock()


def create_job(source: str, num_clips: int, label: str) -> dict:
    job_id = uuid.uuid4().hex[:10]
    job_dir = os.path.join(config.JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    job = {
        "id": job_id,
        "label": label,
        "source": source,
        "num_clips": num_clips,
        "status": "queued",          # queued | running | done | failed
        "stage": None,
        "stage_label": "",
        "progress": 0,
        "log": [],
        "result": None,
        "error": None,
        "created": time.time(),
    }
    with _lock:
        _jobs[job_id] = job
    t = threading.Thread(target=_worker, args=(job_id,), daemon=True)
    t.start()
    return job


def get_job(job_id: str):
    with _lock:
        return _jobs.get(job_id)


def list_jobs():
    with _lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda j: j["created"], reverse=True)
    return jobs


def _worker(job_id: str):
    job = get_job(job_id)
    if not job:
        return
    job_dir = os.path.join(config.JOBS_DIR, job_id)

    def log(msg):
        with _lock:
            job["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def progress(stage, pct):
        label = dict(STAGES).get(stage, stage)
        with _lock:
            job["stage"] = stage
            job["stage_label"] = label
            job["progress"] = pct

    with _lock:
        job["status"] = "running"
    log(f"Job shuru: {job['label']}")
    try:
        result = run_clip_job(job_dir, job["source"], job["num_clips"],
                              progress_cb=progress, log_cb=log)
        with _lock:
            job["result"] = result
            job["status"] = "done"
            job["progress"] = 100
        log(f"Ho gaya! {result.get('rendered', 0)} shorts taiyaar ✅")
    except Exception as e:
        with _lock:
            job["status"] = "failed"
            job["error"] = str(e)
        log(f"Fail: {e}")
