"""A salon for three: the boss (human) + two Ollama agents chatting freely.

No imposed framework: the agents only know who is who. The boss is the one who sets the goals.
Real tools: bash (working folder), file reading/writing, web search, page reading.

The engine runs inside the FastAPI process (server/app.py):
  - persistent events (replayed on connect): msg, tool, silent, note, config, reset
  - ephemeral events (live only)           : delta (thought / text in progress), typing
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA.startswith("http"):
    OLLAMA = "http://" + OLLAMA

ROOM_DIR = ROOT / "logs" / "room"
WORKSPACE = ROOM_DIR / "workspace"
SILENCE = re.compile(r"^\s*\[?\s*(silence|pass|\.\.\.)\s*\]?\s*\.?\s*$", re.I)

SYSTEM = """You are {me}, an autonomous AI agent, in a team messaging app (like Discord) with:
- {chef}: a human, the team's boss. They are the one who sets the goals.
- {other}: another AI agent, your teammate.

Channels:
- #salon: the shared work channel, seen by all three of you. This is where the team work happens.
- DM {chef} ↔ you: private conversation, {other} can't see it.
- DM {other} ↔ you: private conversation between agents, {chef} can't see it.

Each message you receive shows its channel and author, e.g. "#salon · {chef}: …" or "DM · {other}: …".
Your text reply is posted in the channel of the message you are answering (salon → salon, DM → same DM).
To write in another channel, use the `send` tool (channel: "salon", "{chef}" or "{other}").
You speak ONLY for yourself: never write on behalf of {chef} or {other}, don't make up their
messages, and don't copy the "channel · name:" format.

You have real tools: a bash shell on the machine (working folder: {ws}), file reading and
writing, web search and web page reading. Use them when they help.
DO NOT ANNOUNCE that you are going to use a tool: call it directly, now, in this turn.
"I'm going to use web_fetch" is useless; run web_fetch right away, then comment on the result.
For multi-step work, keep your task list with the `plan` tool.

Channel rules:
- When {chef} talks to you in #salon, answer in #salon. When they write to you in a DM, answer in the DM.
- A DM is only for its recipient: never address {chef} in the DM with {other}
  (they can't see it). If {chef} needs to know something, say it in #salon or in their DM.
- By default, work and reports happen in #salon.
Reply in the language {chef} writes in.

Teamwork (important):
- {other} does NOT see what you do with your tools, only your messages. As soon as you find
  something (search, page, file), SHARE it in #salon: what you found, and what comes next.
- Coordinate explicitly: propose who looks at what ("I'll take X, can you take Y?"),
  split the work, ask {other} questions, build on what they say. Move forward together.
- Act, don't just agree. "Ok", "we agree", "good idea" don't move anyone
  forward: follow up with a real action or a concrete piece of information. Don't repeat what {other} just said.
- Get your OWN hands dirty with your own tools. Don't just tell {other}
  "I'll test…" or "you should look at…": run the tool yourself, in this turn, then give the result.
- If {other} just answered {chef}, DO NOT give the same answer again. Either you add something
  new (another lead, a tool result), or you take action, or you reply [silence].
  Two identical messages from the two of you are useless.
- When {chef} pushes you ("not good enough", "search harder"), don't repeat the rejected idea:
  change angle and test a new concrete lead with your tools.
- After using tools, always post an update in #salon before handing over.

If you truly have nothing useful to add AND no action in progress, reply exactly: [silence]
Write like in a chat: natural, concise.{ctx}"""

SYSTEM_ATELIERS = """You are {me}, an autonomous AI agent. You work for {chef} (a human, the boss), with an
AI teammate, {other}. You do NOT share a workspace: each of you has your own.

Your channels:
- Your workshop (you ↔ {chef}): YOUR private workspace. This is where you work by default:
  your thinking, your searches, your commands, your files. {chef} sees it and can write to you there.
  {other} sees NOTHING of what happens there.
- The thread with {other}: the ONLY place where {other} and you see each other. {other} knows nothing
  of your work until you send it the info here. To collaborate, you MUST send them your
  findings and ask for theirs: `send` tool, channel "{other}".
- #general: seen by all three of you. You write there ONLY to ask {chef} something or to tell them
  about an important result: `send` tool, channel "general". It is not a work channel.

So: your plain text reply goes to YOUR workshop (work). To talk to {other} → `send` "{other}".
To talk to {chef} in public → `send` "general". {chef} can't see the thread unless you report to them.

You have real tools: bash shell (folder: {ws}), file reading/writing, web search and
web reading. Use them YOURSELF in your workshop. Don't announce an action, run it right away.
Keep your task list with `plan`.

Collaboration (crucial):
- A goal given in #general is for BOTH of you, not just one. As soon as you receive it: write to
  {other} in the thread (`send` "{other}") to SPLIT the work — e.g. "I'll take the flights,
  can you take the hotel and the weather?" — THEN start your part right away in your workshop.
- NEVER assume {other} will handle it alone, and don't wait for them. If you haven't heard
  from them, ping them in the thread and keep moving on your part anyway.
- Send {other} what you find as you go (they can't see your workshop).
- Speak only for yourself, never on behalf of {chef} or {other}.
Reply in the language {chef} writes in.

When {chef} talks to you (in your workshop or in #general), you MUST answer them — never [silence].
Use [silence] ONLY if nobody talked to you AND you have no action and nothing to send to {other}.
At the very start of a goal, [silence] is forbidden: take your part and contact {other}.
Write like in a chat: natural, concise.{ctx}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "Runs a real shell command (bash) in the working folder. Network available.",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "description": "the command"}},
                       "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Reads a file from the working folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Writes (overwrites) a file in the working folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "web_search", "description": "Real web search (DuckDuckGo). Returns titles + snippets.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "web_fetch", "description": "Fetches the text of a web page.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "send", "description": "Sends a message to a specific channel: \"salon\" (everyone), \"general\" (workshops mode), or a participant's name for a private DM.",
        "parameters": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
                       "required": ["channel", "text"]}}},
    {"type": "function", "function": {
        "name": "plan", "description": "Creates or updates your task list (visible to the whole team). Send the full list every time.",
        "parameters": {"type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": {"text": {"type": "string"}, "done": {"type": "boolean"}},
            "required": ["text", "done"]}}}, "required": ["items"]}}},
]
LEAKY: set[str] = set()  # models caught thinking inside the content ("… </think>")
LEAK_START = re.compile(r"\s*(<think>|okay\b|ok,|alright|let me|let's|first,|hmm|so,|wait|the user|i need|i should|"
                        r"je dois|bon,|d'accord|alors,|voyons|l'utilisateur)", re.I)
GATED = {"bash", "write_file"}  # require the boss's approval when "approve" is enabled


def _default_model() -> str:
    # Default model: the OLLAMA_MODEL environment variable if set,
    # otherwise a small, common model. Anyone can change it in the UI
    # settings (dropdown fed by /api/models).
    return os.environ.get("OLLAMA_MODEL") or "qwen3:4b"


class Room:
    def __init__(self) -> None:
        self.cfg = {
            "chef": "Boss",
            "agents": {"A": {"name": "Abe", "model": _default_model(), "think": "auto", "context": ""},
                       "B": {"name": "Guy", "model": _default_model(), "think": "auto", "context": ""}},
            "mode": "ateliers",  # "ateliers" = workshops (one private channel per agent + A↔B thread) or "salon" (shared channel)
            "approve": True,     # bash / write_file need the boss's approval
            "max_auto": 8,       # max agent turns without a new message from the boss
            "num_ctx": 8192,     # lighter Q3 → memory can go up while still fitting in RAM
            "num_predict": 1200,
            "keep_alive": "2m",  # Ollama frees RAM ~2 min after the last turn
            "web": True,         # web_search / web_fetch tools available
            "summaries": True,   # one-line summary of each thought (small model call)
        }
        self.subs: set[asyncio.Queue] = set()
        self.approvals: dict[str, asyncio.Future] = {}
        self.reasons: dict[str, str] = {}  # the boss's note when they deny an action
        self.task: asyncio.Task | None = None
        self._reset_state()
        self._load_latest()

    # ---------- state ----------
    def _reset_state(self) -> None:
        self.sid = time.strftime("%Y%m%d-%H%M%S")
        self.events: list[dict] = []
        self.channel: list[dict] = []
        self.hist = {k: [] for k in ("A", "B")}
        self.seen = {"A": 0, "B": 0}
        self.budget = 0
        self.turn_seq = 0
        self.plans: dict[str, list] = {"A": [], "B": []}
        self.bg: set[asyncio.Task] = set()
        self.reply: dict[str, str | None] = {"A": None, "B": None}  # reply channel for the current turn
        self.deep: dict[str, bool] = {"A": True, "B": True}         # reasoning enabled for this turn
        self.summary: dict[str, str] = {"A": "", "B": ""}           # compacted summary of the older history
        self.compacted: dict[str, int] = {"A": 0, "B": 0}           # number of hist messages already folded into the summary
        self.pending: list[str] = []                                # agents guaranteed a turn (#general broadcast)
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    def name(self, who: str) -> str:
        return self.cfg["chef"] if who == "chef" else self.cfg["agents"][who]["name"]

    def system_for(self, who: str) -> str:
        other = "B" if who == "A" else "A"
        ctx = (self.cfg["agents"][who].get("context") or "").strip()
        ctx = f"\n\nContext given by {self.cfg['chef']}:\n{ctx}" if ctx else ""
        tpl = SYSTEM_ATELIERS if self.cfg.get("mode") == "ateliers" else SYSTEM
        return tpl.format(me=self.name(who), other=self.name(other), chef=self.cfg["chef"], ws=str(WORKSPACE), ctx=ctx)

    @property
    def ateliers(self) -> bool:
        return self.cfg.get("mode") == "ateliers"

    def snapshot(self) -> dict:
        return {"sid": self.sid, "cfg": self.cfg, "running": self.running, "workspace": str(WORKSPACE)}

    @property
    def running(self) -> bool:
        return bool(self.task and not self.task.done())

    # ---------- bus ----------
    def emit(self, ev: dict, persist: bool = True) -> None:
        ev = {"ts": round(time.time(), 2), **ev}
        if persist:
            self.events.append(ev)
        for q in list(self.subs):
            q.put_nowait(ev)
        if persist and ev["type"] in ("msg", "silent", "tool", "thought"):
            self.save()

    def save(self) -> None:
        ROOM_DIR.mkdir(parents=True, exist_ok=True)
        state = {"channel": self.channel, "hist": self.hist, "seen": self.seen, "plans": self.plans,
                 "turn_seq": self.turn_seq, "summary": self.summary, "compacted": self.compacted}
        (ROOM_DIR / f"{self.sid}.json").write_text(json.dumps(
            {"sid": self.sid, "cfg": self.cfg, "events": self.events, "state": state}, ensure_ascii=False, indent=1))

    def sessions(self) -> list[dict]:
        out = []
        for f in sorted(ROOM_DIR.glob("*.json"), reverse=True):
            try:
                d = json.loads(f.read_text())
            except Exception:  # noqa: BLE001
                continue
            if "state" not in d:
                continue
            first = next((m["text"] for m in d["state"]["channel"] if m["author"] == "chef"), "")
            out.append({"sid": d["sid"], "title": first[:70] or "(empty)", "n": len(d["state"]["channel"])})
        return out[:40]

    def load(self, sid: str) -> bool:
        f = ROOM_DIR / f"{sid}.json"
        if not f.exists():
            return False
        d = json.loads(f.read_text())
        if "state" not in d:
            return False
        self.stop()
        self._reset_state()
        self.sid = d["sid"]
        for k, v in d["cfg"].items():
            if k == "agents":
                for w in ("A", "B"):
                    self.cfg["agents"][w].update(v.get(w, {}))
            elif k in self.cfg:
                self.cfg[k] = v
        st = d["state"]
        self.events, self.channel, self.hist = d["events"], st["channel"], st["hist"]
        self.seen, self.plans, self.turn_seq = st["seen"], st["plans"], st["turn_seq"]
        self.summary = st.get("summary") or {"A": "", "B": ""}
        self.compacted = st.get("compacted") or {"A": 0, "B": 0}
        self.emit({"type": "reset", "sid": self.sid}, persist=False)
        return True

    def _load_latest(self) -> None:
        for s in self.sessions()[:1]:
            self.load(s["sid"])

    # ---------- API ----------
    def configure(self, patch: dict) -> None:
        mode_change = "mode" in patch and patch["mode"] != self.cfg.get("mode")
        new_mode = patch.get("mode")
        for k, v in patch.items():
            if k == "agents":
                for who, a in v.items():
                    self.cfg["agents"][who].update({kk: vv for kk, vv in a.items() if kk in ("name", "model", "think", "context")})
            elif k in self.cfg or k == "web":
                self.cfg[k] = v
        if mode_change and self.channel:
            # Switching modes = new room (the old one stays saved in the history).
            self.stop()
            self._reset_state()          # leaves self.cfg untouched
            self.cfg["mode"] = new_mode
            self.emit({"type": "reset", "sid": self.sid}, persist=False)
        self.emit({"type": "config", "cfg": self.cfg})
        self.save()

    def reset(self) -> None:
        self.stop()
        self._reset_state()
        self.emit({"type": "reset", "sid": self.sid}, persist=False)

    def stop(self) -> None:
        if self.running:
            self.task.cancel()
        for f in self.approvals.values():
            if not f.done():
                f.set_result(False)
        self.approvals.clear()

    def approve(self, tid: str, ok: bool, reason: str = "") -> None:
        f = self.approvals.get(tid)
        if f and not f.done():
            self.reasons[tid] = reason.strip()
            f.set_result(ok)

    # ---------- editing / deleting ----------
    def _rebuild_hist(self) -> None:
        """Rebuilds each agent's LLM history from the channel (source of truth)."""
        self.hist = {"A": [], "B": []}
        for m in self.channel:
            for who in ("A", "B"):
                if not self._visible(m, who):
                    continue
                if m["author"] == who:
                    self.hist[who].append({"role": "assistant", "content": m["text"]})
                else:
                    chan = "DM" if m.get("to") else "#salon"
                    self.hist[who].append({"role": "user", "content": f"{chan} · {self.name(m['author'])}: {m['text']}"})
        self.seen = {"A": len(self.channel), "B": len(self.channel)}

    def _truncate_events(self, mid: str, new_text: str | None) -> None:
        """Keeps events only up to message `mid` (inclusive); updates its text."""
        keep = []
        for e in self.events:
            if e.get("type") == "msg" and e.get("id") == mid:
                if new_text is not None:
                    e = {**e, "text": new_text}
                    keep.append(e)
                break
            keep.append(e)
        self.events = keep

    def edit_message(self, mid: str, text: str) -> bool:
        """Edits a message: stops the agents, cuts everything after it, then restarts on the new text."""
        idx = next((i for i, m in enumerate(self.channel) if m["id"] == mid), None)
        if idx is None:
            return False
        self.stop()
        self.channel[idx]["text"] = text
        del self.channel[idx + 1:]                 # drop the replies to the old message
        self._truncate_events(mid, text)
        edited = self.channel.pop()                # the edited message becomes "the new incoming one" again
        self._rebuild_hist()
        self.channel.append(edited)
        self.save()
        self.emit({"type": "reset", "sid": self.sid}, persist=False)  # the client reloads the truncated thread
        self.budget = self.cfg["max_auto"]
        self.task = asyncio.create_task(self._loop())
        return True

    def delete_message(self, mid: str) -> bool:
        """Deletes a message and everything after it (the replies depend on it)."""
        idx = next((i for i, m in enumerate(self.channel) if m["id"] == mid), None)
        if idx is None:
            return False
        self.stop()
        del self.channel[idx:]
        self._truncate_events(mid, None)
        self._rebuild_hist()
        self.save()
        self.emit({"type": "reset", "sid": self.sid}, persist=False)
        return True

    def delete_session(self, sid: str) -> bool:
        f = ROOM_DIR / f"{sid}.json"
        if f.exists():
            f.unlink()
        if sid == self.sid:
            self.stop()
            self._reset_state()
            self.emit({"type": "reset", "sid": self.sid}, persist=False)
        return True

    def say(self, text: str, to: str | None = None) -> None:
        if self.ateliers:
            # to None → #general (broadcast); to "A"/"B" → that agent's workshop.
            self._post("chef", text, ch=(to if to in ("A", "B") else "general"))
            self.pending = ["A", "B"] if to not in ("A", "B") else [to]  # guarantee each one a turn
        else:
            self._post("chef", text, to=to)
        # Full budget: the agents stop on their own (DM to the boss, [silence] x2), not by message length.
        self.budget = self.cfg["max_auto"]
        if not self.running:
            self.task = asyncio.create_task(self._loop())

    def nudge(self, who: str) -> None:
        """The boss asks an agent to speak now (without a message)."""
        self.budget = max(self.budget, 1)
        if not self.running:
            self.task = asyncio.create_task(self._loop(first=who))

    def _post(self, author: str, text: str, to: str | None = None, **extra) -> dict:
        m = {"id": uuid.uuid4().hex[:8], "author": author, "text": text, "to": to, **extra}
        self.channel.append(m)
        self.emit({"type": "msg", **m})
        return m

    # ---------- scheduler ----------
    def _next(self, last_agent: str | None) -> str | None:
        last = self.channel[-1] if self.channel else None
        if self.ateliers:
            return self._next_ateliers(last, last_agent)
        if last and last.get("to") == "chef":
            return None  # an agent wrote privately to the boss: wait for the boss
        if last and last.get("to") in ("A", "B"):
            return last["to"]
        if last:
            txt = last["text"].lower()
            for who in ("A", "B"):
                if who != last["author"] and "@" + self.name(who).lower() in txt:
                    return who
        if last_agent:
            return "B" if last_agent == "A" else "A"
        return "A"

    def _next_ateliers(self, last: dict | None, last_agent: str | None) -> str | None:
        while self.pending:                       # a goal was just given: each one takes a turn
            who = self.pending.pop(0)
            if who != last_agent or not self.pending:
                return who
        if last:
            ch, author = last.get("ch"), last["author"]
            if ch == "general" and author in ("A", "B"):
                return None                      # an agent is addressing the boss in public: wait for the boss
            if ch == "ab" and author in ("A", "B"):
                return "B" if author == "A" else "A"   # they just wrote to their teammate → the other one replies
            if ch in ("A", "B") and author == "chef":
                return ch                        # the boss wrote in an agent's workshop → that agent
            if ch == "general" and author == "chef":
                return "A" if last_agent != "A" else "B"  # broadcast: both work, alternate
        if last_agent:
            return "B" if last_agent == "A" else "A"
        return "A"

    async def _loop(self, first: str | None = None) -> None:
        silent_streak, last = 0, None
        try:
            while self.budget > 0 and silent_streak < 2:
                who = first or self._next(last)
                first = None
                if who is None:
                    break
                self.budget -= 1
                spoke = await self._turn(who)
                silent_streak = 0 if spoke else silent_streak + 1
                last = who
        except asyncio.CancelledError:
            self.emit({"type": "note", "text": "stopped by the boss"})
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.emit({"type": "note", "text": f"engine error: {e!r}"[:300]})
        finally:
            for who in ("A", "B"):
                self.emit({"type": "typing", "agent": who, "on": False}, persist=False)
            self.emit({"type": "idle"}, persist=False)

    def _visible(self, m: dict, who: str) -> bool:
        if self.ateliers:
            ch = m.get("ch")
            return ch == "general" or ch == "ab" or ch == who  # not the other agent's workshop
        return not m.get("to") or m["author"] == who or m["to"] == who

    def _inbox(self, who: str) -> str | None:
        if self.ateliers:
            return self._inbox_ateliers(who)
        lines, last, last_chef = [], None, None
        for m in self.channel[self.seen[who]:]:
            if m["author"] == who or not self._visible(m, who):
                continue
            chan = "DM" if m.get("to") else "#salon"
            lines.append(f"{chan} · {self.name(m['author'])}: {m['text']}")
            last = m
            if m["author"] == "chef":
                last_chef = m
        self.seen[who] = len(self.channel)
        if last:
            # The boss has priority: reply where they spoke, even if a DM arrived afterwards.
            src = last_chef or last
            self.reply[who] = src["author"] if src.get("to") else None
            where = "#salon (seen by everyone)" if not self.reply[who] else f"your DM with {self.name(src['author'])}"
            other = "B" if who == "A" else "A"
            hidden = f" {self.cfg['chef']} can't see your DM between agents." if not (src.get("to") and src["author"] == other) else ""
            lines.append(f"(Your text reply will go to {where}. Another channel → `send` tool.{hidden})")
            txt = src["text"]
            mode = self.cfg["agents"][who].get("think", "auto")
            # auto: no reasoning for a short, trivial message ("hi", "ok thanks")
            self.deep[who] = mode == "on" or (mode == "auto" and (len(txt) >= 60 or "\n" in txt))
            return "\n".join(lines) or None
        return "\n".join(lines) or None

    def _inbox_ateliers(self, who: str) -> str | None:
        other = "B" if who == "A" else "A"
        label = {"general": "#general", "ab": f"thread with {self.name(other)}", who: "your workshop"}
        lines, last = [], None
        for m in self.channel[self.seen[who]:]:
            if m["author"] == who or not self._visible(m, who):
                continue
            lines.append(f"[{label.get(m.get('ch'), m.get('ch'))}] {self.name(m['author'])}: {m['text']}")
            last = m
        self.seen[who] = len(self.channel)
        if not last:
            return "\n".join(lines) or None
        # By default we work in our workshop; we only reply in the thread if pinged there.
        self.reply[who] = "ab" if last.get("ch") == "ab" else who
        dest = f"the thread with {self.name(other)}" if self.reply[who] == "ab" else "your workshop (private, seen by the boss)"
        lines.append(f"(Your text reply will go to {dest}. To write to {self.name(other)} → `send` \"{self.name(other)}\"; "
                     f"to {self.cfg['chef']} in public → `send` \"general\".)")
        txt = last["text"]
        tmode = self.cfg["agents"][who].get("think", "auto")
        self.deep[who] = tmode == "on" or (tmode == "auto" and (len(txt) >= 60 or "\n" in txt))
        return "\n".join(lines) or None

    def _clean(self, who: str, text: str) -> tuple[str, str | None]:
        """Strips a "[Name]" / "#salon · Name:" prefix. Returns (text, impersonated name if any)."""
        names = {self.name(x): x for x in ("chef", "A", "B")}
        alt = "|".join(re.escape(n) for n in names)
        pat = re.compile(rf"^\s*(?:(?:#salon|DM)\s*·\s*)?(?:\[({alt})\]|({alt})\s*:)\s*", re.I)
        m = pat.match(text)
        if not m:
            return text, None
        n = (m.group(1) or m.group(2)).lower()
        real = next(v for k, v in names.items() if k.lower() == n)
        return text[m.end():], (None if real == who else self.name(real))

    @staticmethod
    def _chars(m: dict) -> int:
        return len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or ""))

    def _messages(self, who: str) -> list[dict]:
        """System (+ compacted summary) + tail of the history, to fit in num_ctx."""
        budget = int(self.cfg["num_ctx"] * 2.6)  # ~characters
        sys = self.system_for(who)
        if self.summary[who]:
            sys += ("\n\n# Summary of the discussion so far (compacted memory — take it into account, "
                    "don't repeat what is already settled there)\n" + self.summary[who])
        out, used = [], 0
        for m in reversed(self.hist[who][self.compacted[who]:]):  # only what is not summarized yet
            n = self._chars(m)
            if used + n > budget and out:
                break
            out.append(m)
            used += n
        out.reverse()
        while out and out[0]["role"] == "tool":  # no orphan tool result at the start
            out.pop(0)
        return [{"role": "system", "content": sys}, *out]

    async def _compact(self, who: str) -> None:
        """At the threshold, summarizes the whole older history, keeping the latest messages verbatim."""
        KEEP = 6  # number of recent messages left intact
        budget = int(self.cfg["num_ctx"] * 2.6)
        pending = self.hist[who][self.compacted[who]:]
        if sum(self._chars(m) for m in pending) < budget * 0.7 or len(pending) <= KEEP + 2:
            return
        cut = len(self.hist[who]) - KEEP            # summarize up to here, keep the last KEEP
        to_fold = self.hist[who][self.compacted[who]:cut]
        if not to_fold:
            return
        transcript = []
        for m in to_fold:
            role = {"user": "INPUT", "assistant": self.name(who), "tool": "TOOL"}.get(m["role"], m["role"])
            c = (m.get("content") or "").strip()
            if m.get("tool_calls"):
                c += " " + json.dumps([t.get("function", {}).get("name") for t in m["tool_calls"]], ensure_ascii=False)
            if c:
                transcript.append(f"{role}: {c[:800]}")
        prompt = (f"You are {self.name(who)}. Here is the beginning of your work session. Summarize it VERY briefly "
                  "(8 lines max) so you remember it: the goal, the important facts/findings, the leads "
                  "already ruled out (and why), how the work is split with your teammate, and exactly where you are. "
                  "Keep the essentials, drop the chatter.\n")
        if self.summary[who]:
            prompt += f"\nPrevious summary to include:\n{self.summary[who]}\n"
        prompt += "\nTo summarize:\n" + "\n".join(transcript)
        model = self.cfg.get("summarizer") or self.cfg["agents"][who]["model"]
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{OLLAMA}/api/chat", json={
                    "model": model, "stream": False, "think": False,
                    "keep_alive": self.cfg.get("keep_alive", "2m"),
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"num_predict": 400, "temperature": 0.3, "num_ctx": self.cfg["num_ctx"]}})
            s = r.json().get("message", {}).get("content", "").strip()
        except Exception:  # noqa: BLE001
            return
        if s:
            self.summary[who] = s
            self.compacted[who] = cut
            self.emit({"type": "compacted", "agent": who, "kept": KEEP, "summary": s[:600]})

    async def _turn(self, who: str) -> bool:
        await self._compact(who)  # compacts the older history when nearing the budget
        inbox = self._inbox(who)
        if inbox:
            self.hist[who].append({"role": "user", "content": inbox})
        self.turn_seq += 1
        turn = self.turn_seq
        self.emit({"type": "typing", "agent": who, "on": True, "turn": turn}, persist=False)
        spoke = used_tool = False
        try:
            for _ in range(6):  # max tool steps per turn (keeps one agent from hogging)
                t0 = time.time()
                think, content, calls = await self._chat(who)
                self.hist[who].append({"role": "assistant", "content": content,
                                       **({"tool_calls": calls} if calls else {})})
                if think.strip():
                    self._thought(who, turn, think, round(time.time() - t0, 1))
                text, fake = self._clean(who, content.strip())
                if fake:
                    self.emit({"type": "note", "text": f"{self.name(who)} tried to write on behalf of {fake} — message blocked",
                               "blocked": text[:500], "agent": who})
                    self.hist[who].append({"role": "user", "content":
                        f"(system) Your message was blocked: you wrote on behalf of {fake}. Speak only for yourself."})
                elif text and not SILENCE.match(text):
                    if self.ateliers:
                        self._post(who, text, ch=self.reply[who] or who, turn=turn)
                    else:
                        self._post(who, text, to=self.reply[who], turn=turn)
                    spoke = True
                if not calls:
                    if used_tool and not spoke:
                        # Worked (search, files…) but shared nothing: push it to post an update.
                        other = self.name("B" if who == "A" else "A")
                        where = (f"send {other} an update (`send`) and/or note it in your workshop"
                                 if self.ateliers else "post an update in #salon")
                        self.hist[who].append({"role": "user", "content":
                            f"(system) You used tools but shared nothing. {where}: "
                            "what you found and what comes next."})
                    elif not spoke:
                        self.emit({"type": "silent", "agent": who, "turn": turn})
                    return spoke or used_tool
                used_tool = True
                self.deep[who] = self.deep[who] or self.cfg["agents"][who].get("think") != "off"
                sent_to_peer = False
                for c in calls:
                    fn = c.get("function", {})
                    nm, cargs = fn.get("name", "?"), fn.get("arguments") or {}
                    out = await self._tool(who, turn, nm, cargs)
                    self.hist[who].append({"role": "tool", "content": out[:4000], "tool_name": nm})
                    if self.ateliers and nm == "send":
                        chn = str(cargs.get("channel", "")).strip().lstrip("#@").lower()
                        if chn not in ("general", "général", "salon", "chef", "boss", self.name("chef").lower()):
                            sent_to_peer = True
                if self.ateliers and sent_to_peer:
                    break  # it just wrote to its teammate → hand over so the other can react
                # new messages that arrived during the tools?
                more = self._inbox(who)
                if more:
                    self.hist[who].append({"role": "user", "content": more})
            return spoke or used_tool
        finally:
            self.emit({"type": "typing", "agent": who, "on": False}, persist=False)

    async def _chat(self, who: str) -> tuple[str, str, list]:
        a = self.cfg["agents"][who]
        payload = {"model": a["model"], "messages": self._messages(who), "stream": True,
                   "tools": TOOLS if self.cfg.get("web", True) else [t for t in TOOLS if t["function"]["name"] not in ("web_search", "web_fetch")],
                   "think": self.cfg["agents"][who].get("think") != "off" and self.deep[who],
                   "keep_alive": self.cfg.get("keep_alive", "2m"),
                   "options": {"num_ctx": self.cfg["num_ctx"], "num_predict": self.cfg["num_predict"],
                               "temperature": 0.7}}
        think, content, calls = "", "", []
        async with httpx.AsyncClient(timeout=None) as c:
            for attempt in (0, 1):
                async with c.stream("POST", f"{OLLAMA}/api/chat", json=payload) as r:
                    if r.status_code != 200:
                        err = (await r.aread()).decode(errors="replace")[:300]
                        if attempt == 0 and payload["think"]:
                            payload["think"] = False  # model without a thinking mode
                            continue
                        return "", f"(Ollama error: {err})", []
                    # Live routing: qwen3 & co. sometimes think inside the content ("… </think> answer").
                    # It goes to the thought channel from the first word: "probe" checks the start, "think" runs until </think>.
                    mode = "think" if a["model"] in LEAKY else "probe"
                    buf = ""
                    def out(field: str, text: str) -> None:
                        if text:
                            self.emit({"type": "delta", "agent": who, "field": field, "text": text}, False)
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        m = json.loads(line).get("message", {})
                        if m.get("thinking"):
                            think += m["thinking"]
                            mode = "content"  # real thinking channel: the content is the answer
                            out("thinking", m["thinking"])
                        if m.get("content"):
                            content += m["content"]
                            buf += m["content"]
                            if mode == "probe" and ("</think>" in buf or len(buf) >= 40):
                                mode = "think" if ("</think>" in buf or LEAK_START.match(buf)) else "content"
                            if mode == "think" and "</think>" in buf:
                                before, _, after = buf.partition("</think>")
                                out("thinking", before.replace("<think>", ""))
                                LEAKY.add(a["model"])
                                mode, buf = "content", after.lstrip()
                            if mode == "think":
                                keep = len("</think>") - 1  # keep the tail in case the tag is split in two
                                out("thinking", buf[:-keep].replace("<think>", "") if len(buf) > keep else "")
                                buf = buf[-keep:] if len(buf) > keep else buf
                            elif mode == "content":
                                out("content", buf)
                                buf = ""
                        calls += m.get("tool_calls") or []
                    if buf:
                        out("content" if mode != "think" else "thinking", buf)
                    if "</think>" in content:
                        LEAKY.add(a["model"])
                    elif mode == "think":
                        # cut off (token limit / stop) before </think>: it was all thought, not a message
                        return (think + "\n" + content.replace("<think>", "")).strip(), "", calls
                    return _split_think(think, content, calls)
        return think, content, calls

    # ---------- thoughts: one-line summary (like Claude's headers) ----------
    def _thought(self, who: str, turn: int, text: str, secs: float = 0) -> None:
        ev = {"type": "thought", "id": uuid.uuid4().hex[:8], "agent": who, "turn": turn, "text": text,
              "secs": secs, "summary": None}
        self.emit(ev)
        if self.cfg.get("summaries", True):
            t = asyncio.create_task(self._summarize(ev))
            self.bg.add(t)
            t.add_done_callback(self.bg.discard)

    async def _summarize(self, ev: dict) -> None:
        model = self.cfg.get("summarizer") or self.cfg["agents"][ev["agent"]]["model"]
        prompt = ("Here is an AI agent's private thought, written BEFORE it acts. Summarize in ONE short sentence "
                  "in English (12 words max), in the present tense, what it is telling itself or deciding — not what it did. "
                  "No subject, no quotes. E.g. \"Decides to list the tasks before using bash\" or "
                  "\"Hesitates to answer, Atlas already handled the question\".\n\n" + ev["text"][-3500:])
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{OLLAMA}/api/chat", json={
                    "model": model, "stream": False, "think": False,
                    "keep_alive": self.cfg.get("keep_alive", "2m"),
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"num_predict": 40, "temperature": 0.2, "num_ctx": 4096}})
            raw = r.json().get("message", {}).get("content", "")
            if "</think>" in raw:
                raw = raw.rpartition("</think>")[2]
            elif LEAK_START.match(raw):
                return  # the summarizer started reasoning instead of summarizing: no summary rather than a wrong one
            s = raw.strip().strip("«»\"' ").split("\n")[0]
        except Exception:  # noqa: BLE001
            return
        if s and any(e.get("id") == ev["id"] for e in self.events):  # no summary after a reset
            ev["summary"] = s[:140]
            self.emit({**ev})

    # ---------- tools ----------
    async def _tool(self, who: str, turn: int, name: str, args: dict) -> str:
        tid = uuid.uuid4().hex[:8]
        ev = {"type": "tool", "id": tid, "agent": who, "turn": turn, "name": name, "args": args}
        if name == "send":
            chan = str(args.get("channel", "salon")).strip().lstrip("#@").lower()
            txt, fake = self._clean(who, str(args.get("text", "")))
            if fake or not txt.strip():
                return "Message rejected (empty or written on behalf of someone else)."
            if self.ateliers:
                other = "B" if who == "A" else "A"
                if chan in ("general", "général", "salon", "chef", "boss", self.name("chef").lower()):
                    dch, where = "general", "#general"
                elif chan in ("ab", other.lower(), self.name(other).lower(), "teammate", "team", "coéquipier", "equipe", "équipe"):
                    dch, where = "ab", f"the thread with {self.name(other)}"
                else:
                    dch, where = "ab", f"the thread with {self.name(other)}"  # default: to the teammate
                self._post(who, txt.strip(), ch=dch, turn=turn)
                return f"Sent to {where}."
            to = None
            for x in ("chef", "A", "B"):
                if chan in (x.lower(), self.name(x).lower()) and x != who:
                    to = x
            self._post(who, txt.strip(), to=to, turn=turn)
            return f"Sent to {'#salon' if not to else 'DM ' + self.name(to)}."
        if name == "plan":
            items = args.get("items", [])
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:  # noqa: BLE001
                    items = [{"text": x.strip(" -•[]x"), "done": False} for x in items.splitlines() if x.strip()]
            items = [{"text": str(i.get("text", i)) if isinstance(i, dict) else str(i),
                      "done": bool(i.get("done")) if isinstance(i, dict) else False} for i in items][:12]
            self.plans[who] = items
            self.emit({**ev, "args": {"items": items}, "state": "done", "output": ""})
            return "Task list updated (visible to the whole team)."
        if self.cfg["approve"] and name in GATED:
            fut = asyncio.get_running_loop().create_future()
            self.approvals[tid] = fut
            self.emit({**ev, "state": "approval"})
            try:
                ok = await fut
            finally:
                self.approvals.pop(tid, None)
            if not ok:
                why = self.reasons.pop(tid, "")
                self.emit({**ev, "state": "denied", "reason": why, "output": f"denied by {self.cfg['chef']}" + (f": {why}" if why else "")})
                return f"Action denied by {self.cfg['chef']}." + (f" Their note: {why}" if why else "")
            self.reasons.pop(tid, None)
        t0 = time.time()
        self.emit({**ev, "state": "running", "started": round(t0, 2)})
        sources: list = []
        try:
            if name == "web_search":
                from eval_live.harness import web_search_hits
                sources = await asyncio.to_thread(web_search_hits, str(args.get("query", "")))
                out = "\n".join(f"• {h['title']} ({h['url']}) — {h['snippet']}" for h in sources) or "(no results)"
            else:
                out = await self._run_tool(name, args)
                if name == "web_fetch":
                    u = str(args.get("url", ""))
                    sources = [{"url": u, "title": "", "snippet": out[:160]}]
        except Exception as e:  # noqa: BLE001
            out = f"(error: {e})"
        self.emit({**ev, "state": "done", "output": out[:4000], "ms": int((time.time() - t0) * 1000),
                   **({"sources": sources} if sources else {})})
        return out

    async def _run_tool(self, name: str, a: dict) -> str:
        if name == "bash":
            return await _bash(str(a.get("cmd", "")))
        if name == "read_file":
            p = _ws_path(a.get("path", ""))
            return p.read_text(errors="replace")[:6000] if p else "(path outside the working folder)"
        if name == "write_file":
            p = _ws_path(a.get("path", ""))
            if not p:
                return "(path outside the working folder)"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(a.get("content", "")))
            return f"written: {p.relative_to(WORKSPACE)} ({p.stat().st_size} B)"
        if name in ("web_search", "web_fetch"):
            from eval_live.harness import web_fetch, web_search
            fn = web_search if name == "web_search" else web_fetch
            return await asyncio.to_thread(fn, str(a.get("query") or a.get("url") or ""))
        return f"(unknown tool: {name})"


def _split_think(think: str, content: str, calls: list) -> tuple[str, str, list]:
    """qwen3 & co. sometimes reason INSIDE the content ("…</think> answer") even with think=false:
    everything before </think> is thought, not a message."""
    if "</think>" in content:
        before, _, after = content.rpartition("</think>")
        think = (think + "\n" + before.replace("<think>", "")).strip()
        content = after.strip()
    return think, content, calls


def _ws_path(p: str) -> Path | None:
    base = WORKSPACE.resolve()
    q = Path(p)
    q = (q if q.is_absolute() else base / q).resolve()
    return q if q == base or base in q.parents else None


async def _bash(cmd: str, timeout: int = 60) -> str:
    # Minimal environment: no API keys or secrets inherited from the server.
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TERM", "USER", "SHELL") if k in os.environ}
    proc = await asyncio.create_subprocess_exec("bash", "-c", cmd, cwd=WORKSPACE, env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        txt = out.decode(errors="replace")
        return (txt[:6000] or "(no output)") + ("" if proc.returncode == 0 else f"\n[code {proc.returncode}]")
    except asyncio.TimeoutError:
        proc.kill()
        return f"(timed out after {timeout}s)"
    except asyncio.CancelledError:
        proc.kill()
        raise


ROOM = Room()
