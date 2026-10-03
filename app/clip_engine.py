"""Stage-by-stage wrapper around the repo's local clipping engine.

We call the engine's stage functions directly (instead of its one-shot
pipeline) so the website can show real progress between stages.
"""
import os
import sys
import traceback

from . import config

sys.path.insert(0, config.ENGINE_DIR)

STAGES = [
    ("source", "Video la raha hoon..."),
    ("transcribe", "Awaz ko text me badal raha hoon..."),
    ("highlights", "AI viral moments dhoondh raha hai..."),
    ("clip", "Shorts kaat raha hoon..."),
]


def _stub_llm(prompt: str) -> str:
    """Temporary stand-in until the user provides a Gemini API key.

    Returns one highlight covering the middle of the video so the
    transcribe -> clip path can be tested end to end.
    """
    import json

    # The engine parses JSON from the LLM; keep the contract minimal.
    return json.dumps(
        {
            "highlights": [
                {
                    "title": "Test highlight",
                    "score": 85,
                    "start_time": 5,
                    "end_time": 25,
                    "hook_sentence": "Test hook",
                    "virality_reason": "Engine test (LLM stubbed)",
                }
            ]
        }
    )


def run_clip_job(job_dir: str, source: str, num_clips: int,
                 progress_cb, log_cb) -> dict:
    """Run the full local pipeline. progress_cb(stage, pct). Returns result dict."""
    from shorts_generator.local.downloader import download_youtube_local
    from shorts_generator.local.transcriber import transcribe_local
    from shorts_generator.local.clipper import crop_highlights_local
    from shorts_generator.highlights import get_highlights

    os.makedirs(job_dir, exist_ok=True)
    out_dir = os.path.join(job_dir, "clips")
    os.makedirs(out_dir, exist_ok=True)

    # Make engine read our env (whisper model etc.)
    os.environ.setdefault("LOCAL_OUTPUT_DIR", out_dir)
    if config.LLM_PROVIDER == "gemini":
        # Engine's call_gemini_llm prefers GEMINI_API_KEY from env, and falls
        # back to the vault-backed skill CLI (custom.gemini) when it is missing.
        os.environ["LLM_PROVIDER"] = "gemini"
        if config.GEMINI_API_KEY:
            os.environ["GEMINI_API_KEY"] = config.GEMINI_API_KEY

    def _set(stage, pct):
        progress_cb(stage, pct)

    try:
        # 1. Source: download URL or use uploaded local file
        _set("source", 5)
        log_cb("Downloading / locating source video...")
        source_path = download_youtube_local(source, fmt="720", out_dir=job_dir)
        _set("source", 15)

        # 2. Transcribe with faster-whisper
        _set("transcribe", 20)
        log_cb("Transcribing audio with Whisper...")
        transcript = transcribe_local(source_path, language=None)
        segments = transcript.get("segments", [])
        if not segments:
            raise RuntimeError("Is video me koi awaz/speech nahi mili.")
        log_cb(f"Transcript ready: {len(segments)} segments, "
               f"{transcript.get('duration', 0):.0f}s")
        _set("transcribe", 50)

        # 3. AI highlight ranking (real LLM if a key is available, else stub)
        _set("highlights", 55)
        # A key source counts as: env key, or the vault-backed Gemini skill CLI
        # (custom.gemini connector) when LLM_PROVIDER=gemini.
        _vault_cli = os.path.expanduser(
            "~/workspace/skills/gemini/bin/gemini_generate.py"
        )
        has_key = bool(config.GEMINI_API_KEY or config.OPENAI_API_KEY) or (
            config.LLM_PROVIDER == "gemini" and os.path.isfile(_vault_cli)
        )
        use_stub = not has_key
        if use_stub:
            log_cb("Gemini key nahi hai — test mode me 1 sample highlight.")
            llm_fn = _stub_llm
        else:
            log_cb("AI viral moments dhoondh raha hai...")
            from shorts_generator.local.llm import call_local_llm
            llm_fn = call_local_llm
        highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=llm_fn)
        all_highlights = highlights_result.get("highlights", [])
        if not all_highlights:
            raise RuntimeError("AI ko koi highlight nahi mila.")
        top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)),
                     reverse=True)[:num_clips]
        log_cb(f"{len(all_highlights)} candidates → top {len(top)} selected")
        _set("highlights", 70)

        # 4. Cut + vertical crop each highlight
        log_cb(f"{len(top)} shorts render ho rahe hain...")
        shorts = crop_highlights_local(source_path, top,
                                       aspect_ratio="9:16", out_dir=out_dir)
        ok = [s for s in shorts if s.get("clip_url")]
        _set("clip", 100)

        return {
            "highlights": all_highlights,
            "shorts": [
                {
                    "title": s.get("title", f"Short {i+1}"),
                    "score": s.get("score", 0),
                    "hook": s.get("hook_sentence", ""),
                    "reason": s.get("virality_reason", ""),
                    "file": os.path.basename(s["clip_url"]) if s.get("clip_url") else None,
                    "error": s.get("error"),
                }
                for i, s in enumerate(shorts)
            ],
            "rendered": len(ok),
        }
    except Exception as e:
        log_cb(f"ERROR: {e}")
        traceback.print_exc()
        raise
