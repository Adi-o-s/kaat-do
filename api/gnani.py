"""One queued client for the Gnani Speech APIs (api.vachana.ai).

Checked against docs.gnani.ai on 13 Nov 2026:
  STT  POST /stt/v3                              multipart, X-API-Key-ID
  TTS  POST /api/v1/tts/inference                JSON -> audio bytes
  VC   POST /api/v1/tts/voice-clone/embeddings   multipart -> {embedding, shape, dtype}
  VC   POST /api/v1/tts/inference  model=vachana-vc-v1 + speaker_embedding
The key never leaves the server. Calls share a semaphore so a one-request-at-a-time
account is not flooded, retry once on 429/5xx, and raise GnaniUnavailable on
402, auth errors or a missing key so callers can fall back to tap mode.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import httpx

BASE = os.getenv("GNANI_BASE_URL", "https://api.vachana.ai")
_sem = asyncio.Semaphore(int(os.getenv("GNANI_CONCURRENCY", "1")))
_client: httpx.AsyncClient | None = None


class GnaniUnavailable(Exception):
    """No key, no credits, auth failure, or repeated rate limiting."""


class GnaniError(Exception):
    pass


def key() -> str | None:
    k = (os.getenv("GNANI_API_KEY") or "").strip()
    return k or None


def available() -> bool:
    return key() is not None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE, timeout=httpx.Timeout(30.0, connect=5.0))
    return _client


async def _post(path: str, *, timeout: float = 30.0, **kw) -> httpx.Response:
    k = key()
    if not k:
        raise GnaniUnavailable("GNANI_API_KEY is not set")
    headers = kw.pop("headers", {})
    headers["X-API-Key-ID"] = k
    last = None
    for attempt in range(2):
        async with _sem:
            try:
                r = await _http().post(path, headers=headers, timeout=timeout, **kw)
            except httpx.HTTPError as e:
                last = e
                await asyncio.sleep(0.4)
                continue
        if r.status_code == 200:
            return r
        if r.status_code in (401, 403, 402):
            raise GnaniUnavailable(f"{r.status_code}: {r.text[:200]}")
        if r.status_code == 429 or r.status_code >= 500:
            last = GnaniError(f"{r.status_code}: {r.text[:200]}")
            await asyncio.sleep(0.6 * (attempt + 1))
            continue
        raise GnaniError(f"{r.status_code}: {r.text[:300]}")
    if isinstance(last, GnaniError) and str(last).startswith("429"):
        raise GnaniUnavailable(str(last))
    raise GnaniError(str(last))


# --- STT ---------------------------------------------------------------------

async def transcribe(wav: bytes, *, fmt: str | None = None, keyterms: list[str] | None = None,
                     language: str = "hi-IN,en-IN", timeout: float = 12.0) -> dict:
    """Prisma v3.0 REST. Returns {transcript, latency_ms, raw}."""
    data = {"model": "prisma-v3.0", "language_code": language}
    fmt = fmt or os.getenv("STT_FORMAT", "transcribe")
    if fmt:
        data["format"] = fmt
    if keyterms:
        data["keyterms"] = json.dumps(keyterms, ensure_ascii=False)
    t0 = time.perf_counter()
    r = await _post("/stt/v3", timeout=timeout, files={"audio_file": ("reply.wav", wav, "audio/wav")}, data=data)
    j = r.json()
    usage_add("stt_requests", 1)
    return {"transcript": j.get("transcript", "") or "", "latency_ms": int((time.perf_counter() - t0) * 1000), "raw": j}


# --- TTS ---------------------------------------------------------------------

async def tts(text: str, *, model: str, voice: str | None = None, language: str = "hi-IN", speed: float = 1.0,
              sample_rate: int = 24000, embedding: dict | None = None, container: str = "mp3") -> bytes:
    body: dict = {
        "text": text,
        "model": model,
        "audio_config": {"sample_rate": sample_rate, "num_channels": 1, "sample_width": 2, "container": container},
    }
    if container == "mp3":
        body["audio_config"]["bitrate"] = "64k"
    else:
        body["audio_config"]["encoding"] = "linear_pcm"
    if embedding is not None:
        body["speaker_embedding"] = embedding
    else:
        body.update({"voice": voice, "language": language, "speed": speed})
    r = await _post("/api/v1/tts/inference", timeout=45.0, json=body)
    usage_add("tts_chars", len(text))
    return r.content


async def clone_embedding(wav: bytes) -> dict:
    r = await _post("/api/v1/tts/voice-clone/embeddings", timeout=45.0,
                    files={"audio_file": ("consent.wav", wav, "audio/wav")})
    j = r.json()
    usage_add("clone_embeddings", 1)
    return {"embedding": j["embedding"], "shape": j.get("shape", [1, 768]), "dtype": j.get("dtype", "torch.bfloat16")}


# --- usage counters (process-local, persisted by app) ------------------------

USAGE: dict[str, float] = {}


def usage_add(k: str, v: float) -> None:
    USAGE[k] = USAGE.get(k, 0) + v
