# Kaat Do

A fire drill for scam calls. Three practice calls in Hinglish, one of them genuine. In a personalised drill there is a fourth, in your own cloned voice from a "new number", asking for money. Your parent has to tell which calls to cut. It teaches one reflex:

**Darr, Raaz, Paisa. Kaat do.** Fear, secrecy or money: hang up, then call family or 1930.

Built for Gnani's Great Indian AI Internship Challenge. Synthetic data only: every bank, courier and officer is fictional, and the only OTP is a fake one shown on screen.

## How it uses Gnani

| Model | Where | When |
| - | - | - |
| Prisma v3.0 (STT, REST) | Hears each reply the parent speaks, `hi-IN,en-IN`, scam keyterms (never the OTP) | Live, one request per turn |
| Prisma v3.0 | Checks the child really read the consent sentence before cloning | Once per personalised drill |
| Timbre v2.5 / v3.0 (TTS) | Every caller line, at 8 kHz phone quality; v3.0 audio tags (`<shouting>`, `<sigh>`) for the "inspector" | Rendered once at build time |
| Voice cloning (`vachana-vc-v1`) | The fourth call and the debrief in the child's voice, ending with the reveal that it was AI | Once per personalised drill |

Nothing is synthesised while a parent is on a call, so a turn costs one short transcription. Reply sorting is rules in code (`api/sort.py`); no outside LLM is used. Evon is not on the public API.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # paste your Gnani key into .env
.venv/bin/python -m tools.render_stock      # renders ~45 caller clips into web/audio/
.venv/bin/uvicorn api.app:app --port 8000
```

Open http://localhost:8000 (sample drill), http://localhost:8000/setup (send it in your voice), or add `?captions=1` to show both sides as text for filming. The microphone needs HTTPS on a phone; see Deploy.

Without a key, or when the microphone is refused, the drill runs in **tap mode** with large reply buttons, and missing clips fall back to the browser's Hindi voice.

## Switches (.env)

| Variable | Default | Does |
| - | - | - |
| `CLONE_CALL_ENABLED` | `1` | `0` drops the fourth call in the child's voice; the debrief and reveal stay |
| `CLONE_ENABLED` | `1` | `0` turns off personalised drills entirely |
| `MAX_CLONE_DRILLS` | `40` | Credit floor: new personalised drills stop after this many |
| `STT_FORMAT` | `transcribe` | Or `transliterate`; choose with `tools/gate1.py` |
| `GNANI_CONCURRENCY` | `1` | Parallel Gnani requests the server allows |

## Layout

```
scripts/calls.json     every call, stage, line, pressure line, nudge, debrief line, consent sentence
api/app.py             FastAPI: /api/script, /api/turn, /api/drill, /api/result, /r/{id}
api/gnani.py           one queued Gnani client (retry once, 402/429 -> tap mode)
api/sort.py            number words -> digits, exact OTP match, reply kinds
web/                   index.html + call.js (state machine), mic.js (capture, pause detection, WAV), card.js, setup
tools/render_stock.py  renders stock lines with Timbre
tools/gate1.py         gate test: your recorded replies through Prisma, both formats, plus a clone sample
tests/test_sort.py     OTP forms, agree, push back, verify, hang-up words
```

## Safety rules the build follows

- Every screen says Practice. The red button always works. No accident, kidnap or death scripts.
- The cloned voice only speaks fixed script lines, with one slot for Papa / Mummy / Dada / Nani. There is no free-text box.
- The consent sentence is recorded live and Prisma must hear it before an embedding is made. The clip is not kept.
- Reply audio is discarded after transcription. Only the verdict and slip lines are stored.
- Embeddings and cloned clips are deleted seven days after setup. The API key and embeddings never reach the browser.
- A slip is only shown with its evidence: the words heard, or an exact OTP digit match. Unclear replies never count.

## Limits

One drill does not prove a habit, and nothing here proves a fraud was prevented. The live app hears a browser microphone, not a phone line. Parents without a smartphone are not reached.
