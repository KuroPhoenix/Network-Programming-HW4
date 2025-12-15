# HW4 Network Programming User Manual

Menu-driven platform with two roles: developers upload and manage games; players browse the store, download games, join rooms, play, and leave reviews. Two TCP servers power the system:
- Developer server: `127.0.0.1:16533`
- User/lobby server: `127.0.0.1:16534`

Data lives under `server/data/` (SQLite), game binaries/manifests under `server/cloudGames/`, player downloads under `user/downloads/`, and logs in `logs/`.

## File map (where things run)
- Server entrypoints: `server/dev_server.py`, `server/user_server.py`
- Client entrypoints: `developer/dev_cli.py`, `user/user_cli.py`
- Network protocol: `docs/protocol.md`
- Config (ports/hosts): `server/core/config.py`
- Game launcher/runtime: `server/core/game_launcher.py`, `server/core/room_genie.py`
- Player API wrapper: `user/api/user_api.py`; Developer API wrapper: `developer/api/dev_api.py`
- Store DBs: `server/data/auth.db`, `server/data/game.db`, `server/data/reviews.db`
- Built-in games: `server/cloudGames/<GameName>/<version>/`
- Player downloads/install cache: `user/downloads/<username>/<game>/<version>/`
- Convenience runner: `run.sh`

## Prerequisites
- Python 3.10+ and `pip`
- `tmux` (needed for the bundled `run.sh` convenience script)
- A shell that can run bash scripts

## Setup
From the repo root:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH="$(pwd)"
```

## Starting the servers
### Easiest (tmux)
```bash
./run.sh
```
This creates/activates `.venv`, installs `loguru`, and launches two tmux windows (`user_server` and `dev_server`). Detach with `Ctrl+B` `D`; reattach with `tmux attach -t hw3`. Kill with `tmux kill-session -t hw3`.

### Manual (separate terminals)
```bash
export PYTHONPATH="$(pwd)"
python -m server.user_server   # port 16534
python -m server.dev_server    # port 16533
```

## Player manual (`python -m user.user_cli`)
- Entry point: `user/user_cli.py`; networking in `user/api/user_api.py`.
- **Login/Register**: Use the menu (main menu in `shared/main_menu.py`). Sample player accounts in `server/data/auth.db`: `kuro/k`, `shiro/s`, `a/a`, `b/b`; you can register new ones.
- **Store** (`visit_store` flow in `user/user_cli.py`):
  - Lists games from `server/data/game.db` via `GAME.LIST` (`server/core/handlers/game_handler.py`).
  - View details (`GAME.GET_DETAILS`), download (`GAME.DOWNLOAD_*`) saves to `user/downloads/<username>/<game>/<version>/`.
  - Update/delete local copies using `user/utils/local_game_manager.py`.
  - View reviews via `REVIEW.SEARCH_GAME` (`server/core/review_manager.py`).
- **Play** (`visit_lobby` flow):
  1. Ensure the game is downloaded (Wordle 1.0.0 bundled in `server/cloudGames/Wordle/1.0.0`).
  2. Create room (`LOBBY.CREATE_ROOM`) or join (`LOBBY.JOIN_ROOM`) handled by `server/core/room_genie.py`.
  3. Ready (`ROOM.READY`) and host starts game (`GAME.START` → launches `server/core/game_launcher.py`).
  4. Local game client auto-starts from manifest commands in `user/utils/local_game_manager.py` and the downloaded `manifest.json`.
  5. When the game reports END/ERROR (`GAME.REPORT`), room state resets in `room_genie.py`.
- **Reviews**:
  - Eligibility tracked in `server/data/reviews.db` (`play_history` table).
  - Add/edit/delete via `REVIEW.ADD/EDIT/DELETE` handlers in `server/core/handlers/review_handler.py`.
- **Logout**: `ACCOUNT.LOGOUT_PLAYER` route in `server/core/handlers/auth_handler.py`.

## Developer manual (`python -m developer.dev_cli`)
- Entry point: `developer/dev_cli.py`; networking in `developer/api/dev_api.py`.
- **Login/Register**: Uses `ACCOUNT.REGISTER_DEVELOPER` / `ACCOUNT.LOGIN_DEVELOPER` (`server/core/handlers/auth_handler.py`).
- **Local workspace**: `developer/games/<GameName>/manifest.json` plus server/client code referenced by the manifest.
- **Create/Update manifest**: Menu action `create` uses `developer/util/local_game_manager.py` to scaffold defaults (commands/env for server/client).
- **Upload**:
  1. `dev_api._validate_game_dir` ensures manifest commands and working dirs exist.
  2. `uploadGame` tars `developer/games/<GameName>/` and streams with `GAME.UPLOAD_BEGIN/CHUNK/END` handlers in `server/core/handlers/game_handler.py`; stored under `server/cloudGames/<Game>/<version>/`.
  3. Latest version becomes visible to players via `GAME.LIST`/`GAME.GET_DETAILS`.
- **Manage store entries**: `GAME.DELETE_GAME` removes all versions (handler in `game_handler.py`; also prunes reviews via `review_manager.py`). `delete_local` removes your local folder.
- **Logout**: `ACCOUNT.LOGOUT_DEVELOPER`.

## Built-in sample game
- Wordle 1.0.0 (CLI, 2 players) lives at `server/cloudGames/Wordle/1.0.0/` with `manifest.json`, `server.py`, `client.py`, `README.md`. It is pre-published in `server/data/game.db` and ready for players to download/play.

## Logs and data
- Logs directory: `logs/` (`user_server.log`, `dev_server.log`, `game_launcher_errors.log`, `room_genie.log`, `auth_errors.log`, etc.). Server boot truncates the per-service log file.
- Databases: `server/data/auth.db` (accounts/sessions), `server/data/game.db` (store entries), `server/data/reviews.db` (reviews/play_history).
- Player downloads/install cache: `user/downloads/<username>/<game>/<version>/`.
- Game uploads: `server/cloudGames/<Game>/<version>/` plus manifests kept with the upload.

## Common issues
- **Ports busy**: Make sure 16533/16534 are free before starting servers.
- **tmux missing**: Install tmux or start servers manually as shown above.
- **Upload validation fails**: Check manifest `server/client` commands and working dirs point to real files in `developer/games/<GameName>/`.
- **Review rejected**: You must have played the specific game/version (play history enforced) before adding a review.

## Architecture overview
- **Servers (processes)**  
  - `server/user_server.py`: player auth, store, downloads, lobby/rooms, game start/report, reviews (port 16534). Dispatch table in this file routes to handlers below.  
  - `server/dev_server.py`: developer auth, game listing/upload/delete (port 16533).  
  - Both rely on `server/util/net.py` (listener/serve loop) and `server/core/config.py` (hosts/ports).

- **Core modules**  
  - Auth (`server/core/auth.py`): Validates tokens, stores sessions; handlers in `server/core/handlers/auth_handler.py` translate protocol names (`ACCOUNT.*`) to Auth methods.  
  - Game catalog/storage:  
    - `server/core/game_manager.py`: CRUD on `game.db`, listing games, fetching details, marking latest versions.  
    - `server/core/storage_manager.py`: Streamed upload/download verification, chunk ordering, checksum; writes uploads to `server/cloudGames/...` and serves download chunks.  
    - Handlers in `server/core/handlers/game_handler.py` convert protocol requests to manager calls, format payloads, and enforce flow (UPLOAD_BEGIN/CHUNK/END, DOWNLOAD_BEGIN/CHUNK/END, GAME.START, GAME.REPORT).  
  - Rooms/lobby:  
    - `server/core/room_genie.py`: In-memory room state, ready sets, host reassignment, game state reset, play history hooks.  
    - `server/core/handlers/lobby_handler.py`: Request adapters for `LOBBY.*` and `ROOM.READY/GET`.  
  - Game launcher: `server/core/game_launcher.py`: Loads manifest, renders command with `{host,port,room_id,token,p1,p2,...}`, allocates port, starts subprocess, tracks/cleans it; used by `room_genie.start_game`.  
  - Reviews/play history: `server/core/review_manager.py`: `reviews.db` (`reviews`, `play_history`), enforces eligibility; handlers in `server/core/handlers/review_handler.py`.  
  - Protocol constants: `server/core/protocol.py`; transport helpers `shared/net.py` (connect/send_request) marshal JSON envelopes with `status/code/payload`.

- **Clients**  
  - Player CLI: `user/user_cli.py` → `user/api/user_api.py`; local install management in `user/utils/local_game_manager.py`; download integrity in `user/utils/download_wizard.py`; menus under `user/ui` + `shared/main_menu.py`.  
  - Developer CLI: `developer/dev_cli.py` → `developer/api/dev_api.py`; local manifest mgmt in `developer/util/local_game_manager.py`; menus under `developer/ui`.  
  - Both CLIs use menu-driven flows (no extra shell args once launched).

- **Data/layout**  
  - DBs: `server/data/auth.db` (users/sessions), `server/data/game.db` (store entries), `server/data/reviews.db` (reviews/play_history).  
  - Uploaded games: `server/cloudGames/<Game>/<version>/manifest.json` + code/assets.  
  - Player installs: `user/downloads/<username>/<game>/<version>/` with copied manifest used for local launch.  
  - Logs: `logs/` (per-module files; truncated on server start).

- **Game lifecycle (Wordle example)**  
  1) Host creates room (`LOBBY.CREATE_ROOM` → `room_genie.create_room`).  
  2) Guests join/ready (`LOBBY.JOIN_ROOM` / `ROOM.READY`).  
  3) Host starts game (`GAME.START` → `room_genie.start_game` → `game_launcher.launch_room` spawns `server/cloudGames/Wordle/1.0.0/server.py`).  
  4) Clients auto-launch from downloaded manifest (commands in `manifest.json`).  
  5) Game reports status via `GAME.REPORT` to `user_server`; `room_genie` resets room and records play history for review eligibility.

- **Message/request flow**  
  - Transport: newline-delimited JSON; each frame is `{type, token, payload, ...}` (`shared/net.py`).  
  - Server dispatch: `user_server.py` / `dev_server.py` map `type` → handler; non-auth types enforce `require_token` (`server/util/validator.py`) then add `username/author/role` into payload.  
  - Store/download: `GAME.LIST/GET_DETAILS` → `game_manager`; `GAME.DOWNLOAD_BEGIN/CHUNK/END` → `storage_manager` (chunks read/written, chunk ordering enforced).  
  - Upload: `GAME.UPLOAD_*` (dev side) → `storage_manager` to validate chunk order/checksum, then `game_manager` to register new version; manifest and assets stored under `server/cloudGames/...`.  
  - Lobby/rooms: `LOBBY.*`, `ROOM.READY/GET` → `room_genie`; `ROOM.GET` returns full room snapshot.  
  - Game start: `GAME.START` (host only) → `room_genie.start_game` (validates ready players/version match) → `game_launcher.launch_room` returns `{host,port,token}` in payload for clients to launch.  
  - Game report: running game server sends `GAME.REPORT` (status RUNNING/END/ERROR) back to `user_server` → `room_genie` updates state, stops process, and writes play history for review eligibility.  
  - Reviews: `REVIEW.ADD/EDIT/DELETE/SEARCH_*` → `review_manager`; add/edit enforce play-history eligibility.  
  - Clients: `user_api.py` / `dev_api.py` wrap `send_request`, preserve session token, and orchestrate local side effects (downloads to disk, launching local game client via manifest).


# HW4 Architecture Explanation

```aiignore
kurophoenix@BlackLeopard:/mnt/c/Users/kurop/OneDrive/Desktop/University/Network Programming/HW3$ tree
.
├── LICENSE
├── README.md
├── __pycache__
│   └── loguru.cpython-312.pyc
├── developer
│   ├── __pycache__
│   │   └── dev_cli.cpython-312.pyc
│   ├── api
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   │   ├── __init__.cpython-312.pyc
│   │   │   └── dev_api.cpython-312.pyc
│   │   └── dev_api.py
│   ├── dev_cli.py
│   ├── games
│   │   ├── BigTwo
│   │   │   ├── README.md
│   │   │   ├── client.py
│   │   │   ├── config.h
│   │   │   ├── game.cpp
│   │   │   ├── game_engine.h
│   │   │   ├── lobby.cpp
│   │   │   ├── manifest.json
│   │   │   ├── playerA.cpp
│   │   │   ├── playerB.cpp
│   │   │   ├── server.py
│   │   │   └── tools.cpp
│   │   ├── README.md
│   │   ├── Tetris
│   │   │   ├── README.md
│   │   │   ├── client.cpp
│   │   │   ├── client.py
│   │   │   ├── common.cpp
│   │   │   ├── common.hpp
│   │   │   ├── db_server.cpp
│   │   │   ├── lobby_server.cpp
│   │   │   ├── lp_framing.hpp
│   │   │   ├── manifest.json
│   │   │   ├── server.py
│   │   │   ├── tetris.cpp
│   │   │   ├── tetris_game.hpp
│   │   │   ├── tetris_runtime.cpp
│   │   │   ├── tetris_runtime.hpp
│   │   │   └── tetris_server.cpp
│   │   ├── Wordle
│   │   │   ├── README.md
│   │   │   ├── client.py
│   │   │   ├── manifest.json
│   │   │   └── server.py
│   │   └── pp
│   │       └── manifest.json
│   ├── template
│   │   └── manifest_template.json
│   ├── ui
│   │   ├── __pycache__
│   │   │   └── dev_menu.cpython-312.pyc
│   │   └── dev_menu.py
│   └── util
│       ├── __pycache__
│       │   └── local_game_manager.cpython-312.pyc
│       └── local_game_manager.py
├── docs
│   ├── architecture.md
│   ├── current_problems.md
│   ├── file structure.md
│   ├── file_responsibilities.md
│   ├── logs.md
│   ├── plan.md
│   ├── protocol.md
│   └── specs.md
├── logs
│   ├── auth_errors.log
│   ├── dev_server.log
│   ├── game_manager_errors.log
│   ├── global.log
│   ├── review_manager_errors.log
│   ├── storage_manager.log
│   ├── storage_manager_errors.log
│   └── user_server.log
├── loguru.py
├── requirements.txt
├── run.sh
├── server
│   ├── __pycache__
│   │   ├── dev_server.cpython-312.pyc
│   │   └── user_server.cpython-312.pyc
│   ├── cloudGames
│   │   ├── BigTwo
│   │   │   └── 1.0.0
│   │   │       ├── README.md
│   │   │       ├── client.py
│   │   │       ├── config.h
│   │   │       ├── game.cpp
│   │   │       ├── game_engine.h
│   │   │       ├── lobby.cpp
│   │   │       ├── manifest.json
│   │   │       ├── playerA.cpp
│   │   │       ├── playerB.cpp
│   │   │       ├── server.py
│   │   │       └── tools.cpp
│   │   ├── Wordle
│   │   │   └── 1.0.0
│   │   │       ├── README.md
│   │   │       ├── __pycache__
│   │   │       │   └── server.cpython-312.pyc
│   │   │       ├── client.py
│   │   │       ├── manifest.json
│   │   │       └── server.py
│   │   └── tmp
│   ├── core
│   │   ├── __pycache__
│   │   │   ├── auth.cpython-312.pyc
│   │   │   ├── config.cpython-312.pyc
│   │   │   ├── game_launcher.cpython-312.pyc
│   │   │   ├── game_manager.cpython-312.pyc
│   │   │   ├── protocol.cpython-312.pyc
│   │   │   ├── review_manager.cpython-312.pyc
│   │   │   ├── room_genie.cpython-312.pyc
│   │   │   └── storage_manager.cpython-312.pyc
│   │   ├── auth.py
│   │   ├── config.py
│   │   ├── game_launcher.py
│   │   ├── game_manager.py
│   │   ├── handlers
│   │   │   ├── __pycache__
│   │   │   │   ├── auth_handler.cpython-312.pyc
│   │   │   │   ├── game_handler.cpython-312.pyc
│   │   │   │   ├── lobby_handler.cpython-312.pyc
│   │   │   │   └── review_handler.cpython-312.pyc
│   │   │   ├── auth_handler.py
│   │   │   ├── game_handler.py
│   │   │   ├── lobby_handler.py
│   │   │   └── review_handler.py
│   │   ├── protocol.py
│   │   ├── review_manager.py
│   │   ├── room_genie.py
│   │   └── storage_manager.py
│   ├── data
│   │   ├── auth.db
│   │   ├── game.db
│   │   └── reviews.db
│   ├── dev_server.py
│   ├── user_server.py
│   └── util
│       ├── __pycache__
│       │   ├── net.cpython-312.pyc
│       │   └── validator.cpython-312.pyc
│       ├── net.py
│       └── validator.py
├── shared
│   ├── __pycache__
│   │   ├── input_helpers.cpython-312.pyc
│   │   ├── logger.cpython-312.pyc
│   │   ├── main_menu.cpython-312.pyc
│   │   └── net.cpython-312.pyc
│   ├── input_helpers.py
│   ├── logger.py
│   ├── main_menu.py
│   └── net.py
└── user
    ├── __pycache__
    │   └── user_cli.cpython-312.pyc
    ├── api
    │   ├── __init__.py
    │   ├── __pycache__
    │   │   ├── __init__.cpython-312.pyc
    │   │   └── user_api.cpython-312.pyc
    │   └── user_api.py
    ├── downloads
    │   ├── kuro
    │   │   ├── Wordle
    │   │   │   └── 1.0.0
    │   │   │       ├── README.md
    │   │   │       ├── client.py
    │   │   │       ├── manifest.json
    │   │   │       └── server.py
    │   │   └── tmp
    │   └── shiro
    │       ├── Wordle
    │       │   └── 1.0.0
    │       │       ├── README.md
    │       │       ├── client.py
    │       │       ├── manifest.json
    │       │       └── server.py
    │       └── tmp
    ├── plugins
    ├── ui
    │   ├── __pycache__
    │   │   └── user_menu.cpython-312.pyc
    │   └── user_menu.py
    ├── user_cli.py
    └── utils
        ├── __pycache__
        │   ├── download_wizard.cpython-312.pyc
        │   └── local_game_manager.cpython-312.pyc
        ├── download_wizard.py
        └── local_game_manager.py

```
