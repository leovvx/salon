#!/usr/bin/env python3
"""Starts Salon / Workshops.

    python run.py

Options via environment variables:
    OLLAMA_HOST   Ollama server address (default http://localhost:11434)
    OLLAMA_MODEL  default model for the agents (default qwen3:4b)
    PORT          web UI port (default 8765)
"""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _load_env(path: Path) -> None:
    """Loads a simple .env (KEY=VALUE) without external dependencies."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env(ROOT / ".env")

PORT = int(os.environ.get("PORT", "8765"))

if __name__ == "__main__":
    url = f"http://localhost:{PORT}"
    if (ROOT / "web" / "dist" / "index.html").exists():
        Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"\n  Salon / Workshops → {url}\n")
    else:
        print("\n  ⚠  UI not built. First run:  cd web && pnpm install && pnpm build\n")
    uvicorn.run("server.app:app", host="0.0.0.0", port=PORT, log_level="info")
