#!/usr/bin/env python3
"""Lance le Salon / Ateliers.

    python run.py

Options via variables d'environnement :
    OLLAMA_HOST   adresse du serveur Ollama (def. http://localhost:11434)
    OLLAMA_MODEL  modèle par défaut des agents (def. qwen3:4b)
    PORT          port de l'interface web (def. 8765)
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
    """Charge un .env simple (KEY=VALUE) sans dépendance externe."""
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
        print(f"\n  Salon / Ateliers → {url}\n")
    else:
        print("\n  ⚠  Interface non buildée. Fais d'abord :  cd web && pnpm install && pnpm build\n")
    uvicorn.run("server.app:app", host="0.0.0.0", port=PORT, log_level="info")
