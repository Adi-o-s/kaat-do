"""Gate 1: do Prisma, Timbre and the clone work well enough to go on?

Record short replies on your phone and drop them in a folder, named by what they are:
    agree_1.m4a   push_1.m4a   verify_1.m4a   hangup_1.m4a   otp_482977_1.m4a
(any of wav/mp3/m4a/ogg/flac/aac). Then:

    .venv/bin/python -m tools.gate1 recordings/
    .venv/bin/python -m tools.gate1 recordings/ --concurrency    # also send two requests at once
    .venv/bin/python -m tools.gate1 --clone consent.m4a          # render one line in the cloned voice

It runs every clip through Prisma v3.0 with both `transcribe` and `transliterate`,
sorts each reply, and prints a pass/fail line per format. Pass: >= 8/10 kinds, >= 4/5 OTPs.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from api import gnani, sort  # noqa: E402
from api.app import KEYTERMS  # noqa: E402

EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}


def expected(name: str) -> tuple[str, str]:
    parts = name.split("_")
    kind = parts[0]
    otp = parts[1] if kind == "otp" and len(parts) > 1 else ""
    return kind, otp


async def run_dir(folder: Path, concurrency: bool) -> None:
    clips = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXT)
    if not clips:
        sys.exit(f"no audio in {folder}")
    for fmt in ("transcribe", "transliterate"):
        right = otp_right = otp_total = false_otp = 0
        lat = []
        print(f"\n== format={fmt}")
        for p in clips:
            want, otp = expected(p.stem)
            data = p.read_bytes()
            # name it with its real extension: Prisma detects format from it
            t0 = time.perf_counter()
            r = await gnani._post("/stt/v3", files={"audio_file": (p.name, data)},
                                  data={"model": "prisma-v3.0", "language_code": "hi-IN,en-IN", "format": fmt,
                                        "keyterms": __import__("json").dumps(KEYTERMS, ensure_ascii=False)})
            lat.append(time.perf_counter() - t0)
            text = r.json().get("transcript", "")
            probe_otp = otp or "482977"
            got = sort.classify(text, probe_otp)
            ok = got["kind"] == want
            right += ok
            if want == "otp":
                otp_total += 1
                otp_right += got["otp_hit"]
            elif got["otp_hit"]:
                false_otp += 1
            print(f"{'ok ' if ok else 'BAD'} {p.name:28s} want={want:7s} got={got['kind']:7s} | {text}")
        n = len(clips)
        print(f"kinds {right}/{n}  otp {otp_right}/{otp_total}  false-otp {false_otp}  "
              f"median {statistics.median(lat):.2f}s")
    if concurrency:
        data = clips[0].read_bytes()
        async def one():
            try:
                await gnani._post("/stt/v3", files={"audio_file": (clips[0].name, data)},
                                  data={"model": "prisma-v3.0", "language_code": "hi-IN,en-IN"})
                return "ok"
            except Exception as e:
                return str(e)[:80]
        gnani._sem = asyncio.Semaphore(4)
        print("\nconcurrency x2:", await asyncio.gather(one(), one()))


async def run_clone(path: Path) -> None:
    emb = await gnani.clone_embedding(path.read_bytes())
    out = ROOT / "gate1_clone.mp3"
    text = "पापा, मैं हूँ। फ़ोन ख़राब हो गया, यह दोस्त का नंबर है। अभी बीस हज़ार चाहिए।"
    out.write_bytes(await gnani.tts(text, model="vachana-vc-v1", embedding=emb))
    print(f"wrote {out}. Play it to two people who know your voice.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--concurrency", action="store_true")
    ap.add_argument("--clone")
    a = ap.parse_args()
    if not gnani.available():
        sys.exit("GNANI_API_KEY missing in .env")
    if a.clone:
        asyncio.run(run_clone(Path(a.clone)))
    if a.folder:
        asyncio.run(run_dir(Path(a.folder), a.concurrency))


if __name__ == "__main__":
    main()
