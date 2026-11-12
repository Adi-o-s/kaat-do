"""Render every stock (non-clone) line in scripts/calls.json to web/audio/<id>.mp3 with Timbre.

    .venv/bin/python -m tools.render_stock            # render missing clips
    .venv/bin/python -m tools.render_stock --force    # re-render all
    .venv/bin/python -m tools.render_stock --only kyc.hook,debrief.rule
Runs once at build time; nothing is synthesised while a parent is on a call.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from api import gnani  # noqa: E402

OUT = ROOT / "web" / "audio"


def stock_lines(script: dict) -> list[dict]:
    lines: list[dict] = []

    def add(obj):
        if obj and obj.get("voice") != "clone":
            lines.append(obj)

    for c in script["calls"]:
        if c.get("clone_only"):
            continue
        for s in c["stages"]:
            add(s["line"]); add(s["pressure"])
        add(c.get("end")); add(c.get("otp_thanks"))
    for k, v in script["fillers"].items():
        add(v)
    for k, v in script["nudges"].items():
        add(v)
    for key, v in script["debrief"].items():
        if "stock" in v:
            lines.append({"id": f"debrief.{key}", "voice": "coach", **v["stock"]})
    return lines


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    if not gnani.available():
        sys.exit("GNANI_API_KEY missing in .env")
    script = json.loads((ROOT / "scripts" / "calls.json").read_text())
    voices = script["voices"]
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, args.only.split(",")))
    lines = stock_lines(script)
    done = 0
    for ln in lines:
        if only and ln["id"] not in only:
            continue
        f = OUT / f"{ln['id']}.mp3"
        if f.exists() and not args.force:
            continue
        v = voices[ln["voice"]]
        text = ln["hi"]
        if v["model"] != "timbre-v3.0":
            import re
            text = re.sub(r"<[^>]+>\s*", "", text)  # audio tags only work on v3.0
        try:
            audio = await gnani.tts(text, model=v["model"], voice=v["voice"], language=v["language"],
                                    speed=v["speed"], sample_rate=v["sample_rate"])
        except Exception as e:  # keep going, report at the end
            print(f"FAIL {ln['id']}: {e}")
            continue
        f.write_bytes(audio)
        done += 1
        print(f"ok   {ln['id']}  ({len(audio)//1024} KB)")
    print(f"rendered {done} of {len(lines)} lines; usage {gnani.USAGE}")


if __name__ == "__main__":
    asyncio.run(main())
