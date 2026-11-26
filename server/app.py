"""Salon / Ateliers — backend FastAPI.

Un salon de discussion local entre le chef (toi) et deux agents IA qui tournent
sur Ollama, avec de vrais outils (bash, fichiers, web). Tout est local : aucune
donnée ne sort de ta machine, à part les appels à ton serveur Ollama.

Lancement :
    python run.py
ou :
    uvicorn server.app:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# ---- import du moteur (server/room.py) ----
sys.path.insert(0, str(Path(__file__).resolve().parent))
from room import ROOM  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA.startswith("http"):
    OLLAMA = "http://" + OLLAMA


def _clean(o):
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


class SafeJSON(JSONResponse):
    def render(self, content):
        from fastapi.encoders import jsonable_encoder
        return json.dumps(_clean(jsonable_encoder(content)), ensure_ascii=False).encode()


app = FastAPI(default_response_class=SafeJSON, title="Salon / Ateliers")


@app.get("/")
def index():
    built = DIST / "index.html"
    if not built.exists():
        raise HTTPException(503, "Interface non buildée : lance `cd web && pnpm install && pnpm build`.")
    return FileResponse(built)


# ---------- Ollama : liste des modèles + chat simple ----------
@app.get("/api/models")
async def models():
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{OLLAMA}/api/tags")
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    payload = {"model": body["model"], "messages": body["messages"], "stream": True,
               "think": body.get("think", True), "options": body.get("options", {})}

    async def gen():
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                async with c.stream("POST", f"{OLLAMA}/api/chat", json=payload) as r:
                    if r.status_code != 200 and payload["think"]:
                        payload["think"] = False  # modèle sans mode réflexion : on réessaie sans
                        async with c.stream("POST", f"{OLLAMA}/api/chat", json=payload) as r2:
                            async for line in r2.aiter_lines():
                                if line:
                                    yield f"data: {line}\n\n"
                        return
                    async for line in r.aiter_lines():
                        if line:
                            yield f"data: {line}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------- Salon à trois (chef + 2 agents) ----------
@app.get("/api/room")
def room_state():
    return ROOM.snapshot()


@app.get("/api/room/stream")
async def room_stream():
    import asyncio
    q: asyncio.Queue = asyncio.Queue()
    backlog = list(ROOM.events)
    ROOM.subs.add(q)

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'hello', **ROOM.snapshot()}, ensure_ascii=False)}\n\n"
            for ev in backlog:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 10)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type": "ping"}\n\n'
        finally:
            ROOM.subs.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/room/say")
async def room_say(req: Request):
    b = await req.json()
    text = str(b.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "message vide")
    ROOM.say(text, to=b.get("to") or None)
    return {"ok": True}


@app.post("/api/room/nudge/{who}")
def room_nudge(who: str):
    ROOM.nudge(who)
    return {"ok": True}


@app.post("/api/room/config")
async def room_config(req: Request):
    ROOM.configure(await req.json())
    return ROOM.snapshot()


@app.post("/api/room/approve")
async def room_approve(req: Request):
    b = await req.json()
    ROOM.approve(b["id"], bool(b.get("ok")), str(b.get("reason") or ""))
    return {"ok": True}


@app.post("/api/room/stop")
def room_stop():
    ROOM.stop()
    return {"ok": True}


@app.get("/api/room/sessions")
def room_sessions():
    return ROOM.sessions()


@app.post("/api/room/load/{sid}")
def room_load(sid: str):
    if not ROOM.load(sid):
        raise HTTPException(404)
    return ROOM.snapshot()


@app.post("/api/room/session/{sid}/delete")
def room_session_delete(sid: str):
    ROOM.delete_session(sid)
    return {"ok": True}


@app.post("/api/room/edit/{mid}")
async def room_edit(mid: str, req: Request):
    b = await req.json()
    text = str(b.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "message vide")
    if not ROOM.edit_message(mid, text):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/room/message/{mid}/delete")
def room_message_delete(mid: str):
    if not ROOM.delete_message(mid):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/room/reset")
def room_reset():
    ROOM.reset()
    return ROOM.snapshot()


# Fichiers statiques de l'interface (après les routes /api)
if DIST.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=DIST), name="web")
