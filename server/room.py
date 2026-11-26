"""Salon à trois : le chef (humain) + deux agents Ollama qui discutent librement.

Aucun cadre imposé : les agents savent seulement qui est qui. C'est le chef qui donne les objectifs.
Outils réels : bash (dossier de travail), lecture/écriture de fichiers, recherche web, lecture de pages.

Le moteur tourne dans le process FastAPI (viewers/dashboard/app.py) :
  - events persistants (rejoués à la connexion) : msg, tool, silent, note, config, reset
  - events éphémères (direct seulement)       : delta (pensée / texte en cours), typing
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

SYSTEM = """Tu es {me}, un agent IA autonome, dans une messagerie d'équipe (comme Discord) avec :
- {chef} : un humain, le chef de l'équipe. C'est lui qui donne les objectifs.
- {other} : un autre agent IA, ton coéquipier.

Canaux :
- #salon : le canal de travail commun, vu par vous trois. C'est là que se fait le travail d'équipe.
- DM {chef} ↔ toi : conversation privée, {other} ne la voit pas.
- DM {other} ↔ toi : conversation privée entre agents, {chef} ne la voit pas.

Chaque message reçu indique son canal et son auteur, ex. « #salon · {chef} : … » ou « DM · {other} : … ».
Ta réponse en texte est publiée dans le canal du message auquel tu réponds (salon → salon, DM → même DM).
Pour écrire dans un autre canal, utilise l'outil `send` (canal : "salon", "{chef}" ou "{other}").
Tu parles UNIQUEMENT en ton nom : n'écris jamais à la place de {chef} ou de {other}, n'invente pas leurs
messages et ne recopie pas le format « canal · nom : ».

Tu as des outils réels : un shell bash sur la machine (dossier de travail : {ws}), lecture et
écriture de fichiers, recherche web et lecture de pages web. Utilise-les quand c'est utile.
N'ANNONCE PAS que tu vas utiliser un outil : appelle-le directement, maintenant, dans ce tour.
« Je vais utiliser web_fetch » ne sert à rien ; lance web_fetch tout de suite, puis commente le résultat.
Pour un travail en plusieurs étapes, tiens ta liste de tâches avec l'outil `plan`.

Règles des canaux :
- Quand {chef} te parle dans #salon, réponds-lui dans #salon. Quand il t'écrit en DM, réponds-lui en DM.
- Un DM ne s'adresse qu'à son destinataire : ne t'adresse jamais à {chef} dans le DM avec {other}
  (il ne le voit pas). Si {chef} doit savoir quelque chose, dis-le dans #salon ou dans son DM.
- Par défaut, le travail et les comptes rendus se font dans #salon.
Réponds dans la langue de {chef} (le français, sauf s'il en change).

Travail en équipe (important) :
- {other} ne voit PAS ce que tu fais avec tes outils, seulement tes messages. Dès que tu trouves
  quelque chose (recherche, page, fichier), PARTAGE-le dans #salon : ce que tu as trouvé, et la suite.
- Coordonnez-vous explicitement : proposez-vous qui regarde quoi (« je prends X, prends-tu Y ? »),
  répartissez le travail, posez des questions à {other}, rebondissez sur ce qu'il dit. Avancez à deux.
- Agis, ne te contente pas de valider. « Ok », « on est d'accord », « bonne idée » ne font avancer
  personne : enchaîne avec une vraie action ou une info concrète. Ne répète pas ce que {other} vient de dire.
- Mets TOI-MÊME la main à la pâte avec tes propres outils. Ne te contente pas de dire à {other}
  « je vais tester… » ou « tu devrais regarder… » : lance l'outil toi-même, dans ce tour, puis donne le résultat.
- Si {other} vient de répondre au {chef}, NE redonne PAS la même réponse. Soit tu ajoutes quelque chose
  de nouveau (une autre piste, un résultat d'outil), soit tu passes à l'action, soit tu réponds [silence].
  Deux messages identiques de vous deux ne servent à rien.
- Quand le {chef} vous pousse (« pas suffisant », « cherchez mieux »), ne répétez pas l'idée rejetée :
  changez d'angle et testez une nouvelle piste concrète avec vos outils.
- Après avoir utilisé des outils, fais toujours un point dans #salon avant de rendre la parole.

Si tu n'as vraiment rien d'utile à ajouter ET que tu n'as aucune action en cours, réponds exactement : [silence]
Écris comme dans un chat : naturel, concis.{ctx}"""

SYSTEM_ATELIERS = """Tu es {me}, un agent IA autonome. Tu travailles pour {chef} (un humain, le chef), avec un
coéquipier IA, {other}. Vous ne partagez PAS d'espace de travail : chacun a le sien.

Tes canaux :
- Ton atelier (toi ↔ {chef}) : TON espace de travail privé. C'est ICI que tu bosses par défaut :
  tes réflexions, tes recherches, tes commandes, tes fichiers. {chef} le voit et peut t'y écrire.
  {other} ne voit RIEN de ce qui s'y passe.
- Le fil avec {other} : le SEUL endroit où {other} et toi vous voyez. {other} ignore tout de ton
  travail tant que tu ne lui envoies pas l'info ici. Pour collaborer, tu DOIS lui envoyer tes
  trouvailles et lui demander les siennes : outil `send`, canal "{other}".
- #général : vu par vous trois. Tu n'y écris QUE pour demander quelque chose à {chef} ou l'informer
  d'un résultat important : outil `send`, canal "général". Ce n'est pas un canal de travail.

Donc : ta réponse en texte simple va dans TON atelier (travail). Pour parler à {other} → `send` "{other}".
Pour parler au {chef} en public → `send` "général". {chef} ne voit pas que tu crois son absence du fil.

Tu as des outils réels : shell bash (dossier : {ws}), lecture/écriture de fichiers, recherche et
lecture web. Utilise-les TOI-MÊME dans ton atelier. N'annonce pas une action, lance-la tout de suite.
Tiens ta liste de tâches avec `plan`.

Collaboration (crucial) :
- Un objectif donné en #général est pour vous DEUX, pas pour un seul. Dès que tu le reçois : écris à
  {other} dans le fil (`send` "{other}") pour vous RÉPARTIR le travail — ex. « je prends les vols,
  tu prends l'hôtel et la météo ? » — PUIS commence ta part tout de suite dans ton atelier.
- Ne suppose JAMAIS que {other} s'en occupe tout seul, et ne l'attends pas. Si tu n'as pas de nouvelles
  de lui, relance-le dans le fil et avance quand même sur ta part.
- Envoie à {other} ce que tu trouves au fur et à mesure (il ne voit pas ton atelier).
- Ne parle qu'en ton nom, jamais à la place de {chef} ou de {other}.
Réponds dans la langue de {chef} (français par défaut).

Quand {chef} t'adresse la parole (dans ton atelier ou en #général), tu DOIS lui répondre — jamais [silence].
N'utilise [silence] QUE si personne ne t'a parlé ET que tu n'as aucune action ni rien à envoyer à {other}.
Au tout début d'un objectif, [silence] est interdit : prends ta part et contacte {other}.
Écris comme dans un chat : naturel, concis.{ctx}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "Exécute une commande shell réelle (bash) dans le dossier de travail. Réseau disponible.",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "description": "la commande"}},
                       "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Lit un fichier du dossier de travail.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Écrit (écrase) un fichier dans le dossier de travail.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "web_search", "description": "Recherche web réelle (DuckDuckGo). Renvoie titres + extraits.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "web_fetch", "description": "Récupère le texte d'une page web.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "send", "description": "Envoie un message dans un canal précis : \"salon\" (tout le monde), ou le nom d'un participant pour un DM privé.",
        "parameters": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
                       "required": ["channel", "text"]}}},
    {"type": "function", "function": {
        "name": "plan", "description": "Crée ou met à jour ta liste de tâches (visible par toute l'équipe). Renvoie la liste complète à chaque fois.",
        "parameters": {"type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": {"text": {"type": "string"}, "done": {"type": "boolean"}},
            "required": ["text", "done"]}}}, "required": ["items"]}}},
]
LEAKY: set[str] = set()  # modèles vus en train de réfléchir dans le contenu (« … </think> »)
LEAK_START = re.compile(r"\s*(<think>|okay\b|ok,|alright|let me|let's|first,|hmm|so,|wait|the user|i need|i should|"
                        r"je dois|bon,|d'accord|alors,|voyons|l'utilisateur)", re.I)
GATED = {"bash", "write_file"}  # demandent l'accord du chef si « approbation » est activée


def _default_model() -> str:
    # Modèle par défaut : variable d'environnement OLLAMA_MODEL si fournie,
    # sinon un petit modèle courant. Chacun peut le changer dans les réglages
    # de l'interface (menu déroulant alimenté par /api/models).
    return os.environ.get("OLLAMA_MODEL") or "qwen3:4b"


class Room:
    def __init__(self) -> None:
        self.cfg = {
            "chef": "Chef",
            "agents": {"A": {"name": "Abe", "model": _default_model(), "think": "auto", "context": ""},
                       "B": {"name": "Guy", "model": _default_model(), "think": "auto", "context": ""}},
            "mode": "ateliers",  # "ateliers" (un canal privé par agent + fil A↔B) ou "salon" (canal commun)
            "approve": True,     # bash / write_file soumis à l'accord du chef
            "max_auto": 8,       # tours d'agents max sans nouvelle intervention du chef
            "num_ctx": 8192,     # Q3 plus légère → on peut remonter la mémoire tout en tenant en RAM
            "num_predict": 1200,
            "keep_alive": "2m",  # Ollama libère la RAM ~2 min après le dernier tour
            "web": True,         # outils web_search / web_fetch disponibles
            "summaries": True,   # résumé en une ligne de chaque pensée (petit appel au modèle)
        }
        self.subs: set[asyncio.Queue] = set()
        self.approvals: dict[str, asyncio.Future] = {}
        self.reasons: dict[str, str] = {}  # note du chef quand il refuse une action
        self.task: asyncio.Task | None = None
        self._reset_state()
        self._load_latest()

    # ---------- état ----------
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
        self.reply: dict[str, str | None] = {"A": None, "B": None}  # canal de réponse du tour en cours
        self.deep: dict[str, bool] = {"A": True, "B": True}         # raisonnement activé pour ce tour
        self.summary: dict[str, str] = {"A": "", "B": ""}           # résumé compacté de l'historique ancien
        self.compacted: dict[str, int] = {"A": 0, "B": 0}           # nb de messages de hist déjà pliés dans le résumé
        self.pending: list[str] = []                                # agents à qui garantir un tour (diffusion #général)
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    def name(self, who: str) -> str:
        return self.cfg["chef"] if who == "chef" else self.cfg["agents"][who]["name"]

    def system_for(self, who: str) -> str:
        other = "B" if who == "A" else "A"
        ctx = (self.cfg["agents"][who].get("context") or "").strip()
        ctx = f"\n\nContexte donné par {self.cfg['chef']} :\n{ctx}" if ctx else ""
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
            out.append({"sid": d["sid"], "title": first[:70] or "(vide)", "n": len(d["state"]["channel"])})
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
            # Changer de mode = nouvelle room (l'ancienne reste sauvegardée dans l'historique).
            self.stop()
            self._reset_state()          # ne touche pas à self.cfg
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

    # ---------- édition / suppression ----------
    def _rebuild_hist(self) -> None:
        """Reconstruit l'historique LLM de chaque agent depuis le canal (source de vérité)."""
        self.hist = {"A": [], "B": []}
        for m in self.channel:
            for who in ("A", "B"):
                if not self._visible(m, who):
                    continue
                if m["author"] == who:
                    self.hist[who].append({"role": "assistant", "content": m["text"]})
                else:
                    chan = "DM" if m.get("to") else "#salon"
                    self.hist[who].append({"role": "user", "content": f"{chan} · {self.name(m['author'])} : {m['text']}"})
        self.seen = {"A": len(self.channel), "B": len(self.channel)}

    def _truncate_events(self, mid: str, new_text: str | None) -> None:
        """Ne garde les événements que jusqu'au message `mid` (inclus) ; met à jour son texte."""
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
        """Modifie un message : arrête les agents, coupe tout ce qui suit, puis relance sur le nouveau texte."""
        idx = next((i for i, m in enumerate(self.channel) if m["id"] == mid), None)
        if idx is None:
            return False
        self.stop()
        self.channel[idx]["text"] = text
        del self.channel[idx + 1:]                 # on jette les réponses à l'ancien message
        self._truncate_events(mid, text)
        edited = self.channel.pop()                # le message édité redevient « le nouvel entrant »
        self._rebuild_hist()
        self.channel.append(edited)
        self.save()
        self.emit({"type": "reset", "sid": self.sid}, persist=False)  # le client recharge le fil tronqué
        self.budget = self.cfg["max_auto"]
        self.task = asyncio.create_task(self._loop())
        return True

    def delete_message(self, mid: str) -> bool:
        """Supprime un message et tout ce qui le suit (les réponses en dépendent)."""
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
            # to None → #général (diffusion) ; to "A"/"B" → l'atelier de cet agent.
            self._post("chef", text, ch=(to if to in ("A", "B") else "general"))
            self.pending = ["A", "B"] if to not in ("A", "B") else [to]  # garantir un tour à chacun
        else:
            self._post("chef", text, to=to)
        # Budget plein : les agents s'arrêtent d'eux-mêmes (DM au chef, [silence] x2) et non par longueur de message.
        self.budget = self.cfg["max_auto"]
        if not self.running:
            self.task = asyncio.create_task(self._loop())

    def nudge(self, who: str) -> None:
        """Le chef demande à un agent de parler maintenant (sans message)."""
        self.budget = max(self.budget, 1)
        if not self.running:
            self.task = asyncio.create_task(self._loop(first=who))

    def _post(self, author: str, text: str, to: str | None = None, **extra) -> dict:
        m = {"id": uuid.uuid4().hex[:8], "author": author, "text": text, "to": to, **extra}
        self.channel.append(m)
        self.emit({"type": "msg", **m})
        return m

    # ---------- ordonnanceur ----------
    def _next(self, last_agent: str | None) -> str | None:
        last = self.channel[-1] if self.channel else None
        if self.ateliers:
            return self._next_ateliers(last, last_agent)
        if last and last.get("to") == "chef":
            return None  # un agent a écrit en privé au chef : on attend le chef
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
        while self.pending:                       # un objectif vient d'être donné : chacun prend son tour
            who = self.pending.pop(0)
            if who != last_agent or not self.pending:
                return who
        if last:
            ch, author = last.get("ch"), last["author"]
            if ch == "general" and author in ("A", "B"):
                return None                      # un agent s'adresse au chef en public : on attend le chef
            if ch == "ab" and author in ("A", "B"):
                return "B" if author == "A" else "A"   # il vient d'écrire à son coéquipier → à l'autre de répondre
            if ch in ("A", "B") and author == "chef":
                return ch                        # le chef a écrit dans l'atelier d'un agent → cet agent
            if ch == "general" and author == "chef":
                return "A" if last_agent != "A" else "B"  # diffusion : les deux bossent, on alterne
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
            self.emit({"type": "note", "text": "arrêté par le chef"})
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.emit({"type": "note", "text": f"erreur du moteur : {e!r}"[:300]})
        finally:
            for who in ("A", "B"):
                self.emit({"type": "typing", "agent": who, "on": False}, persist=False)
            self.emit({"type": "idle"}, persist=False)

    def _visible(self, m: dict, who: str) -> bool:
        if self.ateliers:
            ch = m.get("ch")
            return ch == "general" or ch == "ab" or ch == who  # pas l'atelier de l'autre
        return not m.get("to") or m["author"] == who or m["to"] == who

    def _inbox(self, who: str) -> str | None:
        if self.ateliers:
            return self._inbox_ateliers(who)
        lines, last, last_chef = [], None, None
        for m in self.channel[self.seen[who]:]:
            if m["author"] == who or not self._visible(m, who):
                continue
            chan = "DM" if m.get("to") else "#salon"
            lines.append(f"{chan} · {self.name(m['author'])} : {m['text']}")
            last = m
            if m["author"] == "chef":
                last_chef = m
        self.seen[who] = len(self.channel)
        if last:
            # Le chef est prioritaire : on lui répond là où il a parlé, même si un DM est arrivé après.
            src = last_chef or last
            self.reply[who] = src["author"] if src.get("to") else None
            where = "#salon (vu par tous)" if not self.reply[who] else f"ton DM avec {self.name(src['author'])}"
            other = "B" if who == "A" else "A"
            hidden = f" {self.cfg['chef']} ne voit pas votre DM entre agents." if not (src.get("to") and src["author"] == other) else ""
            lines.append(f"(Ta réponse texte ira dans {where}. Autre canal → outil `send`.{hidden})")
            txt = src["text"]
            mode = self.cfg["agents"][who].get("think", "auto")
            # auto : pas de raisonnement pour un message court et banal (« salut », « ok merci »)
            self.deep[who] = mode == "on" or (mode == "auto" and (len(txt) >= 60 or "\n" in txt))
            return "\n".join(lines) or None
        return "\n".join(lines) or None

    def _inbox_ateliers(self, who: str) -> str | None:
        other = "B" if who == "A" else "A"
        label = {"general": "#général", "ab": f"fil avec {self.name(other)}", who: "ton atelier"}
        lines, last = [], None
        for m in self.channel[self.seen[who]:]:
            if m["author"] == who or not self._visible(m, who):
                continue
            lines.append(f"[{label.get(m.get('ch'), m.get('ch'))}] {self.name(m['author'])} : {m['text']}")
            last = m
        self.seen[who] = len(self.channel)
        if not last:
            return "\n".join(lines) or None
        # Par défaut on bosse dans son atelier ; on ne répond dans le fil que s'il nous y relance.
        self.reply[who] = "ab" if last.get("ch") == "ab" else who
        dest = f"le fil avec {self.name(other)}" if self.reply[who] == "ab" else "ton atelier (privé, vu du chef)"
        lines.append(f"(Ta réponse texte ira dans {dest}. Pour écrire à {self.name(other)} → `send` \"{self.name(other)}\" ; "
                     f"au {self.cfg['chef']} en public → `send` \"général\".)")
        txt = last["text"]
        tmode = self.cfg["agents"][who].get("think", "auto")
        self.deep[who] = tmode == "on" or (tmode == "auto" and (len(txt) >= 60 or "\n" in txt))
        return "\n".join(lines) or None
        return "\n".join(lines) or None

    def _clean(self, who: str, text: str) -> tuple[str, str | None]:
        """Retire un préfixe « [Nom] » / « #salon · Nom : ». Renvoie (texte, nom usurpé éventuel)."""
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
        """Système (+ résumé compacté) + fin de l'historique, pour tenir dans num_ctx."""
        budget = int(self.cfg["num_ctx"] * 2.6)  # ~caractères
        sys = self.system_for(who)
        if self.summary[who]:
            sys += ("\n\n# Résumé de la discussion jusqu'ici (mémoire compactée — tiens-en compte, "
                    "ne répète pas ce qui y est déjà réglé)\n" + self.summary[who])
        out, used = [], 0
        for m in reversed(self.hist[who][self.compacted[who]:]):  # seulement ce qui n'est pas déjà résumé
            n = self._chars(m)
            if used + n > budget and out:
                break
            out.append(m)
            used += n
        out.reverse()
        while out and out[0]["role"] == "tool":  # pas de résultat d'outil orphelin en tête
            out.pop(0)
        return [{"role": "system", "content": sys}, *out]

    async def _compact(self, who: str) -> None:
        """Au seuil, résume tout l'historique ancien en gardant les derniers messages en clair."""
        KEEP = 6  # nb de messages récents laissés intacts
        budget = int(self.cfg["num_ctx"] * 2.6)
        pending = self.hist[who][self.compacted[who]:]
        if sum(self._chars(m) for m in pending) < budget * 0.7 or len(pending) <= KEEP + 2:
            return
        cut = len(self.hist[who]) - KEEP            # on résume jusqu'ici, on garde les KEEP derniers
        to_fold = self.hist[who][self.compacted[who]:cut]
        if not to_fold:
            return
        transcript = []
        for m in to_fold:
            role = {"user": "ENTRÉE", "assistant": self.name(who), "tool": "OUTIL"}.get(m["role"], m["role"])
            c = (m.get("content") or "").strip()
            if m.get("tool_calls"):
                c += " " + json.dumps([t.get("function", {}).get("name") for t in m["tool_calls"]], ensure_ascii=False)
            if c:
                transcript.append(f"{role}: {c[:800]}")
        prompt = (f"Tu es {self.name(who)}. Voici le début de ta session de travail. Résume-la TRÈS court "
                  "(8 lignes max) pour t'en souvenir : l'objectif, les faits/trouvailles importants, les pistes "
                  "déjà écartées (et pourquoi), la répartition avec ton coéquipier, et où tu en es exactement. "
                  "Garde l'essentiel, jette le bavardage.\n")
        if self.summary[who]:
            prompt += f"\nRésumé précédent à intégrer :\n{self.summary[who]}\n"
        prompt += "\nÀ résumer :\n" + "\n".join(transcript)
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
        await self._compact(who)  # compacte l'historique ancien si on approche du budget
        inbox = self._inbox(who)
        if inbox:
            self.hist[who].append({"role": "user", "content": inbox})
        self.turn_seq += 1
        turn = self.turn_seq
        self.emit({"type": "typing", "agent": who, "on": True, "turn": turn}, persist=False)
        spoke = used_tool = False
        try:
            for _ in range(6):  # étapes d'outils max par tour (évite qu'un agent monopolise)
                t0 = time.time()
                think, content, calls = await self._chat(who)
                self.hist[who].append({"role": "assistant", "content": content,
                                       **({"tool_calls": calls} if calls else {})})
                if think.strip():
                    self._thought(who, turn, think, round(time.time() - t0, 1))
                text, fake = self._clean(who, content.strip())
                if fake:
                    self.emit({"type": "note", "text": f"{self.name(who)} a tenté d'écrire au nom de {fake} — message bloqué",
                               "blocked": text[:500], "agent": who})
                    self.hist[who].append({"role": "user", "content":
                        f"(système) Ton message a été bloqué : tu as écrit au nom de {fake}. Parle uniquement en ton nom."})
                elif text and not SILENCE.match(text):
                    if self.ateliers:
                        self._post(who, text, ch=self.reply[who] or who, turn=turn)
                    else:
                        self._post(who, text, to=self.reply[who], turn=turn)
                    spoke = True
                if not calls:
                    if used_tool and not spoke:
                        # A travaillé (recherche, fichiers…) mais n'a rien partagé : on le pousse à faire un point.
                        other = self.name("B" if who == "A" else "A")
                        where = (f"envoie un point à {other} (`send`) et/ou note-le dans ton atelier"
                                 if self.ateliers else "fais un point dans #salon")
                        self.hist[who].append({"role": "user", "content":
                            f"(système) Tu as utilisé des outils mais tu n'as rien partagé. {where} : "
                            "ce que tu as trouvé et la suite."})
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
                        if chn not in ("general", "général", "salon", "chef", self.name("chef").lower()):
                            sent_to_peer = True
                if self.ateliers and sent_to_peer:
                    break  # il vient d'écrire à son coéquipier → on rend la parole pour qu'il réagisse
                # nouveaux messages arrivés pendant les outils ?
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
                            payload["think"] = False  # modèle sans mode réflexion
                            continue
                        return "", f"(erreur Ollama : {err})", []
                    # Routage en direct : qwen3 & co. réfléchissent parfois dans le contenu (« … </think> réponse »).
                    # On l'envoie au canal pensée dès le premier mot : « probe » regarde le début, « think » jusqu'à </think>.
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
                            mode = "content"  # vrai canal de pensée : le contenu est la réponse
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
                                keep = len("</think>") - 1  # garde la fin au cas où la balise est coupée en deux
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
                        # coupé (limite de tokens / arrêt) avant </think> : tout était de la pensée, pas un message
                        return (think + "\n" + content.replace("<think>", "")).strip(), "", calls
                    return _split_think(think, content, calls)
        return think, content, calls

    # ---------- outils ----------
    # ---------- pensées : résumé en une ligne (comme les en-têtes de Claude) ----------
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
        prompt = ("Voici la pensée privée d'un agent IA, écrite AVANT qu'il agisse. Résume en UNE phrase courte "
                  "en français (12 mots max), au présent, ce qu'il se dit ou décide — pas ce qu'il a fait. "
                  "Sans sujet ni guillemets. Ex : « Décide de lister les tâches avant d'utiliser bash » ou "
                  "« Hésite à répondre, Atlas a déjà traité la question ».\n\n" + ev["text"][-3500:])
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
                return  # le résumeur s'est mis à raisonner au lieu de résumer : pas de résumé plutôt qu'un faux
            s = raw.strip().strip("«»\"' ").split("\n")[0]
        except Exception:  # noqa: BLE001
            return
        if s and any(e.get("id") == ev["id"] for e in self.events):  # pas de résumé après un reset
            ev["summary"] = s[:140]
            self.emit({**ev})

    async def _tool(self, who: str, turn: int, name: str, args: dict) -> str:
        tid = uuid.uuid4().hex[:8]
        ev = {"type": "tool", "id": tid, "agent": who, "turn": turn, "name": name, "args": args}
        if name == "send":
            chan = str(args.get("channel", "salon")).strip().lstrip("#@").lower()
            txt, fake = self._clean(who, str(args.get("text", "")))
            if fake or not txt.strip():
                return "Message refusé (vide ou écrit au nom d'un autre)."
            if self.ateliers:
                other = "B" if who == "A" else "A"
                if chan in ("general", "général", "salon", "chef", self.name("chef").lower()):
                    dch, where = "general", "#général"
                elif chan in ("ab", other.lower(), self.name(other).lower(), "coéquipier", "equipe", "équipe"):
                    dch, where = "ab", f"le fil avec {self.name(other)}"
                else:
                    dch, where = "ab", f"le fil avec {self.name(other)}"  # défaut : vers le coéquipier
                self._post(who, txt.strip(), ch=dch, turn=turn)
                return f"Envoyé dans {where}."
            to = None
            for x in ("chef", "A", "B"):
                if chan in (x.lower(), self.name(x).lower()) and x != who:
                    to = x
            self._post(who, txt.strip(), to=to, turn=turn)
            return f"Envoyé dans {'#salon' if not to else 'DM ' + self.name(to)}."
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
            return "Liste de tâches mise à jour (visible par toute l'équipe)."
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
                self.emit({**ev, "state": "denied", "reason": why, "output": f"refusé par {self.cfg['chef']}" + (f" : {why}" if why else "")})
                return f"Action refusée par {self.cfg['chef']}." + (f" Sa remarque : {why}" if why else "")
            self.reasons.pop(tid, None)
        t0 = time.time()
        self.emit({**ev, "state": "running", "started": round(t0, 2)})
        sources: list = []
        try:
            if name == "web_search":
                from eval_live.harness import web_search_hits
                sources = await asyncio.to_thread(web_search_hits, str(args.get("query", "")))
                out = "\n".join(f"• {h['title']} ({h['url']}) — {h['snippet']}" for h in sources) or "(aucun résultat)"
            else:
                out = await self._run_tool(name, args)
                if name == "web_fetch":
                    u = str(args.get("url", ""))
                    sources = [{"url": u, "title": "", "snippet": out[:160]}]
        except Exception as e:  # noqa: BLE001
            out = f"(erreur : {e})"
        self.emit({**ev, "state": "done", "output": out[:4000], "ms": int((time.time() - t0) * 1000),
                   **({"sources": sources} if sources else {})})
        return out

    async def _run_tool(self, name: str, a: dict) -> str:
        if name == "bash":
            return await _bash(str(a.get("cmd", "")))
        if name == "read_file":
            p = _ws_path(a.get("path", ""))
            return p.read_text(errors="replace")[:6000] if p else "(chemin hors du dossier de travail)"
        if name == "write_file":
            p = _ws_path(a.get("path", ""))
            if not p:
                return "(chemin hors du dossier de travail)"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(a.get("content", "")))
            return f"écrit : {p.relative_to(WORKSPACE)} ({p.stat().st_size} o)"
        if name in ("web_search", "web_fetch"):
            from eval_live.harness import web_fetch, web_search
            fn = web_search if name == "web_search" else web_fetch
            return await asyncio.to_thread(fn, str(a.get("query") or a.get("url") or ""))
        return f"(outil inconnu : {name})"


def _split_think(think: str, content: str, calls: list) -> tuple[str, str, list]:
    """qwen3 & co. raisonnent parfois DANS le contenu (« …</think> réponse ») même avec think=false :
    tout ce qui précède </think> est de la pensée, pas un message."""
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
    # Environnement minimal : pas de clés d'API ni de secrets hérités du serveur.
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TERM", "USER", "SHELL") if k in os.environ}
    proc = await asyncio.create_subprocess_exec("bash", "-c", cmd, cwd=WORKSPACE, env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        txt = out.decode(errors="replace")
        return (txt[:6000] or "(aucune sortie)") + ("" if proc.returncode == 0 else f"\n[code {proc.returncode}]")
    except asyncio.TimeoutError:
        proc.kill()
        return f"(timeout après {timeout}s)"
    except asyncio.CancelledError:
        proc.kill()
        raise


ROOM = Room()
