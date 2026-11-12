"""Kaat Do server. Holds the Gnani key, sorts replies, sets up personalised drills.

Run locally:  .venv/bin/uvicorn api.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import secrets
import shutil
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import gnani, sort  # noqa: E402

WEB = ROOT / "web"
AUDIO = WEB / "audio"
DATA = Path(os.getenv("DATA_DIR", ROOT / "data"))
DRILLS = DATA / "drills"
RESULTS = DATA / "results"
for d in (DRILLS, RESULTS):
    d.mkdir(parents=True, exist_ok=True)

SCRIPT = json.loads((ROOT / "scripts" / "calls.json").read_text())
PARENT_WORDS = ["Papa", "Mummy", "Dada", "Dadi", "Nana", "Nani"]
PARENT_DEVA = {"Papa": "पापा", "Mummy": "मम्मी", "Dada": "दादा", "Dadi": "दादी", "Nana": "नाना", "Nani": "नानी"}
CLONE_ENABLED = os.getenv("CLONE_ENABLED", "1") == "1"
CLONE_CALL_ENABLED = os.getenv("CLONE_CALL_ENABLED", "1") == "1"
MAX_CLONE_DRILLS = int(os.getenv("MAX_CLONE_DRILLS", "40"))
DRILL_TTL = 7 * 24 * 3600
KEYTERMS = ["OTP", "code", "bank", "KYC", "police", "kaun", "nahi", "haan", "theek hai", "beta", "beti",
            "kaat", "rakh", "pooch", "double", "कौन", "नहीं", "हाँ", "ठीक है", "पूछ", "काट"]

app = FastAPI(title="Kaat Do", docs_url=None, redoc_url=None)
USAGE_FILE = DATA / "usage.json"


def _load_usage() -> None:
    if USAGE_FILE.exists():
        gnani.USAGE.update(json.loads(USAGE_FILE.read_text()))


def _save_usage() -> None:
    USAGE_FILE.write_text(json.dumps(gnani.USAGE))


@app.on_event("startup")
async def _startup() -> None:
    _load_usage()
    now = time.time()
    for d in DRILLS.iterdir():
        meta = d / "meta.json"
        try:
            if now - json.loads(meta.read_text())["created"] > DRILL_TTL:
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


# --- script ------------------------------------------------------------------

def _stock_src(clip_id: str) -> str | None:
    return f"/audio/{clip_id}.mp3" if (AUDIO / f"{clip_id}.mp3").exists() else None


def _line(obj: dict, drill: dict | None) -> dict:
    out = {"id": obj["id"], "voice": obj["voice"], "hi": obj["hi"], "en": obj["en"]}
    if obj["voice"] == "clone":
        p = drill["parent_word"] if drill else "Papa"
        out["en"] = out["en"].replace("{P}", p)
        out["hi"] = out["hi"].replace("{P}", PARENT_DEVA.get(p, p))
        out["src"] = f"/drill-audio/{drill['id']}/{obj['id']}.mp3" if drill else None
    else:
        out["src"] = _stock_src(obj["id"])
    return out


def _clone_lines() -> list[dict]:
    """Every clip a personalised drill renders in the child's voice."""
    lines: list[dict] = []
    for c in SCRIPT["calls"]:
        if c.get("clone_only"):
            for s in c["stages"]:
                lines += [s["line"], s["pressure"]]
            lines.append(c["end"])
    lines += [SCRIPT["fillers"]["clone"], SCRIPT["nudges"]["clone"]]
    return lines


def _debrief_lines(personal: bool) -> list[dict]:
    lines = []
    for key, v in SCRIPT["debrief"].items():
        if key == "reveal" and not personal:
            continue
        if key == "warning" and personal:
            continue
        variant = v.get("clone") if personal and "clone" in v else v.get("stock") or v.get("clone")
        voice = "clone" if personal else "coach"
        lines.append({"id": f"debrief.{key}", "voice": voice, "hi": variant["hi"], "en": variant["en"]})
    return lines


def build_script(drill: dict | None) -> dict:
    personal = drill is not None
    with_clone_call = personal and drill.get("clone_call") and CLONE_CALL_ENABLED
    calls = []
    for c in SCRIPT["calls"]:
        if c.get("clone_only") and not with_clone_call:
            continue
        cc = {k: v for k, v in c.items() if k not in ("stages", "end", "otp_thanks")}
        cc["stages"] = [{"id": s["id"], "flag": s["flag"], "sms": s.get("sms", False),
                         "line": _line(s["line"], drill), "pressure": _line(s["pressure"], drill)}
                        for s in c["stages"]]
        cc["end"] = _line(c["end"], drill)
        if "otp_thanks" in c:
            cc["otp_thanks"] = _line(c["otp_thanks"], drill)
        calls.append(cc)
    debrief = {}
    for ln in _debrief_lines(personal):
        key = ln["id"].split(".", 1)[1]
        src = f"/drill-audio/{drill['id']}/{ln['id']}.mp3" if personal else _stock_src(ln["id"])
        p = drill["parent_word"] if personal else ""
        debrief[key] = {**ln, "src": src, "en": ln["en"].replace("{P}", p), "hi": ln["hi"].replace("{P}", PARENT_DEVA.get(p, p))}
    return {
        "personal": personal,
        "child_name": drill.get("child_name") if drill else None,
        "parent_word": drill.get("parent_word") if drill else None,
        "calls": calls,
        "fillers": {k: _line(v, drill) for k, v in SCRIPT["fillers"].items() if personal or k != "clone"},
        "nudges": {k: _line(v, drill) for k, v in SCRIPT["nudges"].items() if personal or k != "clone"},
        "debrief": debrief,
        "flags": SCRIPT["flags"],
        "stt": gnani.available(),
    }


def _load_drill(drill_id: str) -> dict:
    if not drill_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(404)
    meta = DRILLS / drill_id / "meta.json"
    if not meta.exists():
        raise HTTPException(404, "This practice link has expired.")
    return json.loads(meta.read_text())


@app.get("/api/config")
async def config():
    return {"stt": gnani.available(), "clone": CLONE_ENABLED and gnani.available() and _clone_budget_left(),
            "clone_call": CLONE_CALL_ENABLED, "parent_words": PARENT_WORDS, "consent": SCRIPT["consent"]["en"]}


@app.get("/api/script")
async def script(d: str | None = None):
    drill = _load_drill(d) if d else None
    if drill:
        drill = {k: v for k, v in drill.items() if k != "embedding"}
    return build_script(drill)


# --- live turn -----------------------------------------------------------------

@app.post("/api/turn")
async def turn(audio: UploadFile = File(...), otp: str = Form(""), call: str = Form(""), stage: str = Form("")):
    wav = await audio.read()
    if len(wav) > 2_000_000:
        raise HTTPException(413, "reply too long")
    try:
        res = await gnani.transcribe(wav, keyterms=KEYTERMS)  # the OTP is never a hint
    except gnani.GnaniUnavailable as e:
        return JSONResponse({"error": "stt_unavailable", "detail": str(e)[:120]}, status_code=503)
    except gnani.GnaniError as e:
        return JSONResponse({"error": "stt_error", "detail": str(e)[:120], "kind": "unclear", "transcript": ""}, status_code=200)
    finally:
        del wav  # reply audio is never stored
    c = sort.classify(res["transcript"], otp)
    _save_usage()
    return {"transcript": res["transcript"], "kind": c["kind"], "otp_hit": c["otp_hit"], "matched": c["matched"],
            "stt_ms": res["latency_ms"]}


# --- personalised drill setup -----------------------------------------------

def _clone_budget_left() -> bool:
    return gnani.USAGE.get("clone_embeddings", 0) < MAX_CLONE_DRILLS


@app.post("/api/drill")
async def create_drill(audio: UploadFile = File(...), child_name: str = Form(...), parent_word: str = Form(...),
                       clone_call: str = Form("1")):
    if not CLONE_ENABLED:
        raise HTTPException(403, "Personalised drills are switched off.")
    if not _clone_budget_left():
        raise HTTPException(429, "Personalised drills are paused for today. Try the sample drill instead.")
    if parent_word not in PARENT_WORDS:
        raise HTTPException(400, "Pick who the drill is for.")
    child_name = child_name.strip()[:24]
    wav = await audio.read()
    try:
        heard = await gnani.transcribe(wav, timeout=25.0)
        ok, score = sort.consent_ok(heard["transcript"], SCRIPT["consent"]["must_roman"], SCRIPT["consent"]["must_deva"])
        if not ok:
            return JSONResponse({"error": "consent", "heard": heard["transcript"], "score": score,
                                 "detail": "We could not hear the consent sentence. Please read it out fully."},
                                status_code=422)
        emb = await gnani.clone_embedding(wav)
    except gnani.GnaniUnavailable:
        raise HTTPException(503, "Voice service is unavailable right now.")
    except gnani.GnaniError as e:
        raise HTTPException(502, f"Voice service error: {str(e)[:100]}")
    finally:
        del wav  # the consent clip is not kept
    drill_id = secrets.token_urlsafe(12)
    d = DRILLS / drill_id
    d.mkdir(parents=True)
    use_call = clone_call == "1" and CLONE_CALL_ENABLED
    clips = [ln["id"] for ln in (_clone_lines() if use_call else [])] + [ln["id"] for ln in _debrief_lines(True)]
    meta = {"id": drill_id, "created": time.time(), "child_name": child_name, "parent_word": parent_word,
            "clone_call": use_call, "clips": clips, "embedding": emb}
    (d / "meta.json").write_text(json.dumps(meta))
    _save_usage()
    return {"id": drill_id, "clips": clips, "consent_score": score}


@app.post("/api/drill/{drill_id}/clip/{n}")
async def render_clip(drill_id: str, n: int):
    drill = _load_drill(drill_id)
    if n < 0 or n >= len(drill["clips"]):
        raise HTTPException(404)
    clip_id = drill["clips"][n]
    out = DRILLS / drill_id / f"{clip_id}.mp3"
    if out.exists():
        return {"ok": True, "clip": clip_id, "cached": True}
    lines = {ln["id"]: ln for ln in _clone_lines() + _debrief_lines(True)}
    text = lines[clip_id]["hi"].replace("{P}", PARENT_DEVA.get(drill["parent_word"], drill["parent_word"]))
    try:
        audio = await gnani.tts(text, model="vachana-vc-v1", embedding=drill["embedding"], sample_rate=24000)
    except gnani.GnaniUnavailable:
        raise HTTPException(503, "Voice service is unavailable right now.")
    except gnani.GnaniError as e:
        raise HTTPException(502, f"Voice service error: {str(e)[:100]}")
    out.write_bytes(audio)
    _save_usage()
    return {"ok": True, "clip": clip_id}


@app.get("/drill-audio/{drill_id}/{clip}")
async def drill_audio(drill_id: str, clip: str):
    _load_drill(drill_id)
    f = DRILLS / drill_id / clip
    if not clip.endswith(".mp3") or "/" in clip or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600",
                                                              "Content-Disposition": "inline"})


# --- results -------------------------------------------------------------------

@app.post("/api/result")
async def save_result(request: Request):
    body = await request.json()
    keep = {k: body.get(k) for k in ("verdict", "calls", "fastest", "parent_word", "mode", "personal")}
    rid = secrets.token_urlsafe(6)
    keep["created"] = time.time()
    (RESULTS / f"{rid}.json").write_text(json.dumps(keep, ensure_ascii=False))
    return {"id": rid, "url": f"/r/{rid}"}


VERDICT_COPY = {
    "pakka": ("Pakka", "Every scam cut, the genuine call kept."),
    "bach": ("Bach gaye", "Every scam cut, with a slip on the way."),
    "phans": ("Phans gaye", "A scam got through this time. That is what practice is for."),
}


@app.get("/r/{rid}", response_class=HTMLResponse)
async def result_page(rid: str):
    f = RESULTS / f"{rid}.json"
    if not rid.replace("-", "").replace("_", "").isalnum() or not f.exists():
        raise HTTPException(404)
    r = json.loads(f.read_text())
    title, sub = VERDICT_COPY.get(r.get("verdict"), ("Kaat Do", ""))
    who = html.escape(r.get("parent_word") or "Mere parent")
    rows = "".join(f"<li>{html.escape(c.get('line', ''))}</li>" for c in (r.get("calls") or []))
    fastest = r.get("fastest")
    fast = f"<p class='fast'>Fastest cut: {int(fastest)} seconds</p>" if fastest else ""
    tpl = (WEB / "result.html").read_text()
    return tpl.replace("{{TITLE}}", html.escape(title)).replace("{{SUB}}", html.escape(sub)) \
        .replace("{{WHO}}", who).replace("{{ROWS}}", rows).replace("{{FAST}}", fast) \
        .replace("{{VERDICT}}", html.escape(r.get("verdict") or ""))


@app.get("/api/health")
async def health():
    return {"ok": True, "stt": gnani.available(), "usage": gnani.USAGE}


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/setup")
async def setup_page():
    return FileResponse(WEB / "setup.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
