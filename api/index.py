"""Vercel serverless entry point: exposes the FastAPI application as `app`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sorvia.api.app import create_app

app = create_app()
