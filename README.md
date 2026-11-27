# Salon · Workshops

A **local chat room** where you work with **two AI agents** (Abe and Guy)
running on your own [Ollama](https://ollama.com) models. They have real
tools — shell (bash), file reading/writing, web search and page reading —
and work together to get done what you ask them.

Everything is **100% local**: the only thing that leaves your machine is the calls to
your Ollama server (which you host yourself).

![Salon](web/src/assets/hero.png)

---

## Two modes

- **Workshops** (default) — each agent has its own private channel with you, plus a
  shared "thread" between the two agents. You post a goal in **#general**, the two
  agents split the work and exchange their findings in the thread. You can step
  into Guy's or Abe's workshop to see what each one is doing and thinking, or write
  to them individually.
- **Salon** — a single shared channel seen by all three of you, like a Discord server.

Switch modes in the settings (the gear icon, top right).

---

## Requirements

1. **[Ollama](https://ollama.com/download)** installed and running, with at least one model.
   A model that handles reasoning and tools works best, for example:
   ```bash
   ollama pull qwen3:4b
   ```
   (On a powerful machine: `qwen3:30b-a3b`, smarter.)
2. **[Python 3.10+](https://www.python.org/downloads/)**.

Node.js is **not** required: the UI is already built in `web/dist/`.

---

## Quick start

```bash
git clone https://github.com/leovvx/salon.git
cd salon
pip install -r requirements.txt
python run.py
```

Your browser opens at **http://localhost:8765**. Pick your model in the settings,
write a goal in **#general**, and you're off.

> On Windows, the commands are the same in **PowerShell** or the Command Prompt.

---

## Connecting the app to your Windows models

### Case 1 — everything on the same Windows PC
Ollama and the app run on the same machine: nothing to configure, `python run.py` is enough.
The default model is picked in the settings (dropdown fed by Ollama).

### Case 2 — the app on one machine, Ollama on another PC (LAN)
For example the app on the Mac, the models on the Windows PC.

**On the Windows PC** (the one running Ollama), expose Ollama on the local network by
setting the environment variable and then restarting Ollama:

- PowerShell (temporary):
  ```powershell
  $env:OLLAMA_HOST = "0.0.0.0:11434"
  ollama serve
  ```
- Or permanently: *Windows Settings → Environment variables →*
  new variable `OLLAMA_HOST` = `0.0.0.0:11434`, then restart Ollama.

Find the Windows PC's local IP with `ipconfig` (the "IPv4 Address" line, e.g. `192.168.1.42`).

**On the machine running the app**, point to that PC:
```bash
OLLAMA_HOST=http://192.168.1.42:11434 python run.py
```
or copy `.env.example` to `.env` and put the address in it (see below).

> Remember to allow port **11434** in the Windows firewall if the connection is blocked.

---

## Configuration (optional)

Copy `.env.example` to `.env` and adjust:

| Variable       | Purpose                                     | Default                  |
|----------------|---------------------------------------------|--------------------------|
| `OLLAMA_HOST`  | Ollama server address                       | `http://localhost:11434` |
| `OLLAMA_MODEL` | Default model for the agents                | `qwen3:4b`               |
| `PORT`         | Web UI port                                 | `8765`                   |

The model can be changed at any time in the UI settings.

---

## What you can tweak in the UI

- **Model** for each agent (Abe / Guy).
- **Mode**: Workshops / Salon.
- **Action approval**: bash and file writes can ask for your OK.
- **Auto turns**: how many exchanges the agents chain without you.
- **Memory** (`num_ctx`): the discussion is **compacted automatically** when it
  nears the limit (the model writes a summary so it doesn't lose track).
- Sessions are **saved** and can be reloaded.

Files created by the agents live in `logs/room/workspace/` (ignored by git).

---

## Developing the UI

To work on the front end (React + Vite + Tailwind):

```bash
cd web
pnpm install
pnpm dev     # dev server at http://localhost:5173, proxies /api to :8765
pnpm build   # regenerates web/dist/, served by the backend
```

---

## Architecture

```
run.py            launcher (loads .env, starts uvicorn, opens the browser)
server/
  app.py          FastAPI API: /api/room/*, /api/chat, /api/models + serves web/dist
  room.py         the salon engine (agents, tools, turns, compaction)
web/              React UI (source) + web/dist (built, committed)
```

The engine only needs the Python standard library + `httpx`.
