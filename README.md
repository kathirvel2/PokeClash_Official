# PokeClash

**PokeClash** is a Telegram Pokémon battle bot with a companion web mini-app (a
"dex"). It runs competitive and random-battle PvP through a **local Pokémon
Showdown** simulator, while keeping an older custom "Clash" battle system in
place for legacy commands and assets.

A single Python process runs two things at once:

- the **Telegram bot** (long-polling via `pyTelegramBotAPI`), and
- a **FastAPI + Uvicorn** web server that exposes a REST API and serves the
  `website/` dex/team-editor mini-app.

Battles are simulated by a bundled copy of the **Pokémon Showdown** engine
(`server/pokemon-showdown/`), driven through a small Node worker that the Python
side talks to over stdin/stdout.

> ⚠️ **Security note first:** this repository previously committed real
> credentials (`.env.production`, `ca.pem`). If you cloned an old copy, or you
> are the maintainer, read [Security & credentials](#security--credentials)
> before doing anything else — those secrets must be rotated.

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Project layout](#project-layout)
- [Tech stack](#tech-stack)
- [Third-party projects & attribution](#third-party-projects--attribution)
- [Local deployment](#local-deployment)
- [Configuration](#configuration)
- [Running](#running)
- [Bot commands](#bot-commands)
- [Security & credentials](#security--credentials)
- [License](#license)

---

## Features

**Battle system (Pokémon Showdown bridge)**
- `/challenge` reply flow in Telegram groups, with accept / decline / cancel /
  expiry handling.
- Challenge settings: battle mode, filters, visuals, and random-battle
  generation selection.
- Owned-team **singles, doubles, and free-for-all** challenges.
- Random-battle **singles, doubles, and free-for-all** across generations 1–9.
- Team preview, move choice, switch choice, target selection, undo, and forfeit.
- Gimmick buttons for **Tera, Mega, Mega X, Mega Y, Dynamax, Z-Move, and Ultra
  Burst**.
- Showdown protocol parsing for battle recap, public state, move history, and
  end-of-battle rewards.
- `/battle_stats` and `/viewteam` for active Showdown battles, plus rendered
  battle visuals (Pillow).

**Collection / progression**
- Pokémon collection, teams, bag/items, shiny & legendary passes, redeem codes,
  coins, Elo ranking, and leaderboards.
- Trainer cards and rendered rank images.

**Web mini-app (`website/`)**
- Pokédex, move / ability / item browsers, team & Pokémon editors, collection
  and profile views, and an admin panel — served by the same FastAPI app and
  usable as a Telegram WebApp.

**Legacy "Clash" system**
- The original custom battle engine (`bot/battle/`) and assets remain for legacy
  commands. A user can only hold **one** active PvP session at a time across the
  Showdown `/challenge` flow and the legacy Clash flow.

---

## Architecture

```
Telegram  ──polling──►  bot/ (pyTelegramBotAPI handlers)
                              │
                              ├── bot/showdown_battle/  ──►  bot/bridge/showdown_bridge.py
                              │                                    │  (spawns Node)
                              │                                    ▼
                              │                         bot/bridge/showdown_worker.js
                              │                                    │  (imports)
                              │                                    ▼
                              │                    server/pokemon-showdown/dist/sim  (Showdown engine)
                              │
                              ├── bot/battle/           legacy "Clash" engine
                              ├── bot/mechanics/db.py   PostgreSQL
                              └── bot/services/pokeapi.py  ──►  https://pokeapi.co (art/stats)

FastAPI app (same process, Uvicorn on :8080)
   ├── REST API for the web mini-app
   └── StaticFiles mount → website/   (dex, editors, profile, admin)
```

- `main.py` loads environment variables **first** (choosing `.env` vs
  `.env.production` based on `ENV_MODE`), then imports and runs `bot.main.main`.
- `bot/main.py` registers all handlers and runs the Telegram polling loop and the
  Uvicorn server concurrently with `asyncio.gather`.
- The Showdown bridge lazily builds `server/pokemon-showdown/dist/sim/index.js`
  (via `node build`) on first use if it is missing.

---

## Project layout

| Path | Purpose |
| --- | --- |
| `main.py` | Entry point; loads env, starts the app. |
| `bot/main.py` | Handler registration, FastAPI app, run loop. |
| `bot/handlers/` | Telegram command & callback handlers. |
| `bot/showdown_battle/` | Showdown-backed challenge/battle flow. |
| `bot/bridge/` | Python↔Node bridge, worker, team packer. |
| `bot/battle/` | Legacy "Clash" battle engine, modes, effects. |
| `bot/randombattle/` | Per-generation random-battle sets (gen1–gen8). |
| `bot/mechanics/` | DB access, team model, moves/items/ranking data. |
| `bot/services/pokeapi.py` | PokeAPI client for artwork & stats. |
| `bot/image_generation/` | Trainer cards, team/battle image rendering. |
| `bot/assets/` | Sprites (gen-5 style), effect art, templates. |
| `bot/data_*.json` | Bundled species/moves/abilities/learnsets data. |
| `server/pokemon-showdown/` | Bundled Pokémon Showdown simulator (MIT). |
| `server/bridge.py` | Auxiliary bridge helper. |
| `website/` | Static web mini-app (dex, editors, admin). |
| `Setup_files/` | Local deployment / systemd notes. |
| `New_mega/` | Custom mega-evolution artwork. |
| `reset_database.py` | Destructive helper to reset user progress. |
| `requirements.txt` | Python dependencies. |

---

## Tech stack

- **Python 3.10+** — `pyTelegramBotAPI`, `FastAPI`, `Uvicorn`, `psycopg2`,
  `Pillow`, `aiohttp`, `python-dotenv` (see `requirements.txt`).
- **Node.js** — required to build and run the bundled Pokémon Showdown simulator.
- **PostgreSQL** — user, team, and collection storage.

---

## Third-party projects & attribution

PokeClash stands on several external projects. Please respect their licenses and
terms.

### Pokémon Showdown (battle engine) — Smogon

The battle simulation is powered by **[Pokémon Showdown][ps]**, the open-source
simulator maintained by **Smogon** and contributors. A copy is bundled under
[`server/pokemon-showdown/`](server/pokemon-showdown/) and is used through the
local worker in `bot/bridge/showdown_worker.js`, which imports the compiled
simulator at `server/pokemon-showdown/dist/sim/index.js`.

- Upstream: <https://github.com/smogon/pokemon-showdown>
- License: MIT — see `server/pokemon-showdown/LICENSE`.
- The bundled copy is what supplies formats such as `gen9randombattle`,
  `gen1randombattle` … `gen8randombattle`, and the custom
  `gen9pokeclashcompetitive` format (see `bot/showdown_config.py`).

> **Tip:** the bundled `server/pokemon-showdown/node_modules/` is currently
> committed to this repo (thousands of files). For a leaner clone you may prefer
> to remove it from tracking and run `npm install` inside
> `server/pokemon-showdown/` yourself. This is optional and left as a
> maintenance note.

### PokéAPI & PokeAPI/sprites (artwork and stats)

Pokémon artwork, sprites, and some stats are fetched at runtime from
**[PokéAPI](https://pokeapi.co)**:

- `bot/services/pokeapi.py` calls `https://pokeapi.co/api/v2/...` for official
  artwork and base stats.
- The web mini-app fetches sprites directly from the
  **[PokeAPI/sprites](https://github.com/PokeAPI/sprites)** repository, e.g.
  `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/<num>.png`.
- Locally bundled gen-5-style sprites live under `bot/assets/sprite/`.

Please review [PokéAPI's fair-use policy](https://pokeapi.co/docs/v2) before
running at scale; consider caching responses.

### Pokémon intellectual property

Pokémon and all related names are trademarks of **Nintendo**, **Game Freak**,
and **The Pokémon Company**. PokeClash is a **non-commercial, fan-made project**
and is not affiliated with, sponsored by, or endorsed by any of them.

[ps]: https://github.com/smogon/pokemon-showdown

---

## Local deployment

This project is primarily intended for **local / self-hosted** deployment.

### Prerequisites

- Python 3.10+ and `pip`
- Node.js 18+ and `npm` (to build Pokémon Showdown)
- PostgreSQL 13+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/kathirvel2/PokeClash.git
cd PokeClash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Build the Pokémon Showdown simulator

```bash
cd server/pokemon-showdown
npm install        # only if node_modules is missing / you removed it
node build         # produces dist/sim/index.js
cd ../..
```

(The bridge will also attempt `node build` automatically on first battle if
`dist/sim/index.js` is missing.)

### 3. Set up PostgreSQL (local)

```bash
sudo -u postgres psql
```
```sql
CREATE DATABASE pokemon_db;
CREATE USER myuser WITH PASSWORD 'mypassword';
GRANT ALL PRIVILEGES ON DATABASE pokemon_db TO myuser;
```

The bot creates and migrates its own tables on startup (see
`bot/mechanics/db.py`). For a **local** database, use `DB_SSLMODE=disable` — no
CA certificate is needed.

### 4. Configure environment

```bash
cp .env.example .env
# edit .env and fill in BOT_TOKEN, DB_* etc.
```

See [Configuration](#configuration) below.

---

## Configuration

All configuration is via environment variables, loaded by `main.py`:

- `ENV_MODE=production` → loads `.env.production`
- otherwise (unset/`development`) → loads `.env`

Start from [`.env.example`](.env.example). Key variables:

| Variable | Description |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token from BotFather. **Secret.** |
| `BOT_USERNAME` | Bot's @username (without `@`). |
| `DB_HOST` / `DB_PORT` | PostgreSQL host / port. |
| `DB_NAME` / `DB_USER` / `DB_PASS` | Database name / user / password. **Secret.** |
| `DB_SSLMODE` | `disable` for local, `require` for managed cloud DBs. |
| `DB_SSLCERT` | Path to a CA cert (only when `DB_SSLMODE=require`). |
| `WEB_APP_HOST_URL` | Public URL of the web mini-app (CORS + WebApp links). |
| `WEB_APP_LINK_NAME` | Display name for the WebApp link. |
| `RANKED_GROUP_IDS` | Comma-separated group IDs where ranked play is allowed. |
| `COMMUNITY_CHAT_ID` / `COMMUNITY_CHAT_LINK` | Community group wiring. |
| `ADMIN_USER_IDS` | Comma-separated admin Telegram user IDs. |
| `BACKUP_CHAT_ID` | Chat the bot sends DB backups to. |
| `PORT` | Web server port (default `8080`). |
| `SHOWDOWN_DIR` | Override the Showdown install path (optional). |
| `SHOWDOWN_OWNED_FORMAT` | Owned-team battle format (optional). |

---

## Running

From the repo root, with the virtual environment active and `.env` filled in:

```bash
python main.py
```

This starts both the Telegram polling loop and the web server
(`http://localhost:8080` by default). Then, in Telegram:

1. Add the bot to a group.
2. Reply to another user's message with `/challenge`.
3. Adjust challenge settings (mode/filter/visuals/random-battle generation).
4. Start the battle and use move/target selection, then check `/battle_stats`.

### Run 24/7 (optional)

`Setup_files/` contains **systemd** unit templates (`Pokeclash.service` and an
optional `cloudflared.service` for exposing the web app via a Cloudflare quick
tunnel). See that folder for step-by-step notes tuned for a local Postgres
setup.

### Reset user progress (destructive)

```bash
python reset_database.py
```

Truncates `teams`/`collections` and resets user stats. It asks for `YES`
confirmation. **Irreversible.**

---

## Bot commands

Player: `/start`, `/challenge` (reply in group), `/clash`, `/dex`, `/import`,
`/cancelimport`, `/add`, `/main`, `/view`, `/display`, `/mycollection`,
`/myteams`, `/viewteam`, `/battle_stats`, `/settings`, `/leaderboard` (`/rank`),
`/trainercard`, `/card`, `/bag`, `/buy`, `/shinypass`, `/legendarypass`,
`/redeem`, `/setfavorite`, `/implemented`.

Admin: `/admin`, `/adminstats`, `/adminfind`, `/adminuser`, `/adminset`,
`/adminreset`, `/redeemcreate`, `/broadcast`.

---

## Author's Note

Pokeclash is made out of pure interest ,If anyone finds issue or work as inappropriate contact me via Telegram https://t.me/nicedddd

## License

PokeClash is released under the **MIT License** — see [`LICENSE`](LICENSE).

Bundled Pokémon Showdown retains its own MIT license
(`server/pokemon-showdown/LICENSE`). PokéAPI content is subject to PokéAPI's
terms. Pokémon is © Nintendo / Game Freak / The Pokémon Company; this is a
non-commercial fan project.
