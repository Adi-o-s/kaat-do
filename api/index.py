"""Vercel entry point: the whole FastAPI app (pages, audio and API) as one function."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATA_DIR", "/tmp/kaatdo")

from api.app import app  # noqa: E402,F401
