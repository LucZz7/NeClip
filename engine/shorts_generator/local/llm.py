"""Local LLM backend — OpenAI or Gemini, selected by LLM_PROVIDER."""
import os
import subprocess
import sys

from ..config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    require_gemini_key,
    require_openai_key,
)

# Vault-backed Gemini CLI (uses the stored custom.gemini connector; no raw key).
_GEMINI_CLI = os.path.expanduser("~/workspace/skills/gemini/bin/gemini_generate.py")


def _call_gemini_via_vault_cli(prompt: str) -> str:
    """Fallback: run the vault-backed Gemini CLI when no env key is set."""
    proc = subprocess.run(
        [sys.executable, _GEMINI_CLI, prompt],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Gemini vault CLI failed: {proc.stderr.strip()[:300]}"
        )
    return proc.stdout.strip()


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(api_key=require_openai_key())
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def call_gemini_llm(prompt: str) -> str:
    """Gemini backend used by --mode local when LLM_PROVIDER=gemini.

    Prefers GEMINI_API_KEY from env; when it is missing, falls back to the
    vault-backed skill CLI (custom.gemini connector, no raw key on disk).
    """
    try:
        api_key = require_gemini_key()
    except RuntimeError:
        api_key = None
    if api_key is None:
        return _call_gemini_via_vault_cli(prompt)
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 8192,
        },
    )
    return response.text or ""


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai' or 'gemini'."
    )
