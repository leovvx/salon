# Salon · Ateliers

Un **salon de discussion local** où tu travailles avec **deux agents IA** (Abe et Guy)
qui tournent sur tes propres modèles [Ollama](https://ollama.com). Ils ont de vrais
outils — shell (bash), lecture/écriture de fichiers, recherche et lecture de pages web —
et collaborent entre eux pour accomplir ce que tu leur demandes.

Tout est **100 % local** : la seule chose qui sort de ta machine, ce sont les appels à
ton serveur Ollama (que tu héberges toi-même).

![Salon](web/src/assets/hero.png)

---

## Deux modes

- **Ateliers** (par défaut) — chaque agent a son propre canal privé avec toi, plus un
  « fil » commun entre les deux agents. Tu lances un objectif dans **#général**, les deux
  agents se répartissent le travail et s'échangent leurs infos dans le fil. Tu peux entrer
  dans l'atelier de Guy ou d'Abe pour voir ce que chacun fait et réfléchit, ou leur écrire
  individuellement.
- **Salon** — un seul canal commun vu par vous trois, comme un salon Discord.

On change de mode dans les réglages (l'engrenage, en haut à droite).

---

## Prérequis

1. **[Ollama](https://ollama.com/download)** installé et lancé, avec au moins un modèle.
   Un modèle qui gère le raisonnement et les outils marche le mieux, par exemple :
   ```bash
   ollama pull qwen3:4b
   ```
   (Sur une grosse machine : `qwen3:30b-a3b`, plus intelligent.)
2. **[Python 3.10+](https://www.python.org/downloads/)**.

Node.js n'est **pas** nécessaire : l'interface est déjà compilée dans `web/dist/`.

---

## Démarrage rapide

```bash
git clone https://github.com/leovvx/salon.git
cd salon
pip install -r requirements.txt
python run.py
```

Le navigateur s'ouvre sur **http://localhost:8765**. Choisis ton modèle dans les réglages,
écris un objectif dans **#général**, et c'est parti.

> Sous Windows, les commandes sont les mêmes dans **PowerShell** ou l'invite de commandes.

---

## Connecter l'app à tes modèles Windows

### Cas 1 — tout sur le même PC Windows
Ollama et l'app tournent sur la même machine : rien à configurer, `python run.py` suffit.
Le modèle par défaut se choisit dans les réglages (menu déroulant alimenté par Ollama).

### Cas 2 — l'app sur une machine, Ollama sur un autre PC (LAN)
Par exemple l'app sur le Mac, les modèles sur le PC Windows.

**Sur le PC Windows** (celui qui a Ollama), expose Ollama sur le réseau local en réglant
la variable d'environnement puis en relançant Ollama :

- PowerShell (temporaire) :
  ```powershell
  $env:OLLAMA_HOST = "0.0.0.0:11434"
  ollama serve
  ```
- Ou de façon permanente : *Paramètres Windows → Variables d'environnement →*
  nouvelle variable `OLLAMA_HOST` = `0.0.0.0:11434`, puis redémarrer Ollama.

Trouve l'IP locale du PC Windows avec `ipconfig` (ligne « Adresse IPv4 », ex. `192.168.1.42`).

**Sur la machine qui lance l'app**, pointe vers ce PC :
```bash
OLLAMA_HOST=http://192.168.1.42:11434 python run.py
```
ou copie `.env.example` en `.env` et mets-y l'adresse (voir ci-dessous).

> Pense à autoriser le port **11434** dans le pare-feu Windows si la connexion est bloquée.

---

## Configuration (facultatif)

Copie `.env.example` en `.env` et adapte :

| Variable       | Rôle                                        | Défaut                   |
|----------------|---------------------------------------------|--------------------------|
| `OLLAMA_HOST`  | Adresse du serveur Ollama                   | `http://localhost:11434` |
| `OLLAMA_MODEL` | Modèle par défaut des agents                | `qwen3:4b`               |
| `PORT`         | Port de l'interface web                     | `8765`                   |

Le modèle reste modifiable à tout moment dans les réglages de l'interface.

---

## Ce que tu peux régler dans l'interface

- **Modèle** de chaque agent (Abe / Guy).
- **Mode** Ateliers / Salon.
- **Validation des actions** : bash et écriture de fichiers peuvent demander ton accord.
- **Tours automatiques** : combien d'échanges les agents enchaînent sans toi.
- **Mémoire** (`num_ctx`) : la discussion se **compacte automatiquement** quand elle
  approche de la limite (le modèle en fait un résumé pour ne pas perdre le fil).
- Les sessions sont **sauvegardées** et rechargeables.

Les fichiers créés par les agents vivent dans `logs/room/workspace/` (ignoré par git).

---

## Développer l'interface

Pour modifier le front (React + Vite + Tailwind) :

```bash
cd web
pnpm install
pnpm dev     # serveur de dev sur http://localhost:5173, proxy /api vers :8765
pnpm build   # régénère web/dist/ servi par le backend
```

---

## Architecture

```
run.py            lanceur (charge .env, démarre uvicorn, ouvre le navigateur)
server/
  app.py          API FastAPI : /api/room/*, /api/chat, /api/models + sert web/dist
  room.py         le moteur du salon (agents, outils, tours, compaction)
web/              interface React (source) + web/dist (compilée, versionnée)
```

Le moteur n'a besoin que de la bibliothèque standard Python + `httpx`.
