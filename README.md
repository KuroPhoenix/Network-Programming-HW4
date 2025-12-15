# HW4 Network Programming User Manual



## Prerequisites
- Python 3.10+ and `pip`
- `tmux` (needed for the bundled `run.sh` convenience script)
- A shell that can run bash scripts

## Setup
For the user client setup, from root:
```bash
cd ../../mnt/c/Users/kurop/OneDrive/Desktop/University/Network\ Programming/HW3
source .venv/bin/activate
python -m user.user_cli
```
Open another page in terminal. From root, do
```bash
cd ../../mnt/c/Users/kurop/OneDrive/Desktop/University/Network\ Programming/HW3
source .venv/bin/activate
python -m developer.dev_cli
```
## Starting the servers (Done already)

### Manual (separate terminals)

#### Dev Server
From Linux remote root:
```bash
bash
rm -rf Network-Programming-HW4/
git clone https://github.com/KuroPhoenix/Network-Programming-HW4.git
source .venv/bin/activate
cd Network-Programming-HW4/ && python -m server.dev_server
```

#### User Server
From Linux remote root (If Project is not installed):
```bash
bash
rm -rf Network-Programming-HW4/
git clone https://github.com/KuroPhoenix/Network-Programming-HW4.git
cd Network-Programming-HW4/
source .venv/bin/activate
cd Network-Programming-HW4/ && python -m server.user_server
```
From Linux remote root (If Project is installed):
```bash
bash
cd Network-Programming-HW4/
source .venv/bin/activate
cd Network-Programming-HW4/ && python -m server.user_server
```


## Player manual (`python -m user.user_cli`)
Use the numbers shown in each menu. Every goal below is a path of choices (menus → options).

- **Log in / Register**
  - Main Menu: `1 Register` → enter username/password, or `2 Login` → enter username/password.

- **Download a game**
  - Main Menu: `1 Visit Store` → choose a game → `3 Download game`.

- **Update a game to latest**
  - Path A: Main Menu: `1 Visit Store` → choose a game → `4 Update to latest version`.
  - Path B: Main Menu: `4 View my downloaded games` → pick game → `3 Update to latest version`.

- **Delete local copy**
  - Path A: Main Menu: `1 Visit Store` → choose a game → `5 Delete local copy`.
  - Path B: Main Menu: `4 View my downloaded games` → pick game → `4 Delete game`.

- **View game details / reviews**
  - Main Menu: `1 Visit Store` → choose a game → `1 View game details` or `2 View game reviews`.
  - Local copy route: Main Menu: `4 View my downloaded games` → pick game → `1 View game details` or `2 View game reviews`.

- **Create a room (host)**
  - Main Menu: `2 Visit Lobby` → `4 Create room` → pick a downloaded game → name the room.

- **Join a room**
  - Main Menu: `2 Visit Lobby` → `5 Join room` → enter room id.

- **Ready up (guest)**
  - After joining room: Room Menu shows `Ready up` → pick `1 Ready up`.

- **Start game (host)**
  - After players are ready: Room Menu shows `Start game` → pick `1 Start game`.

- **Launch started game (if you rejoin mid-game)**
  - Room Menu when status is IN_GAME: choose `Launch started game`.

- **Leave room**
  - Room Menu: choose `Leave room`.

- **Give a review (after you played)**
  - Main Menu: `1 Visit Store` → choose a game → `6 Give this game a review` (only works if play history exists).

- **Edit/Delete your review**
  - Main Menu: `3 View my reviews` → pick a review → `Edit this review` or `Delete this review`.

- **View installed games**
  - Main Menu: `4 View my downloaded games` → pick a game.

- **Logout**
  - Main Menu: `5 Logout`.


## Developer manual (`python -m developer.dev_cli`)
Choice paths for common tasks:

- **Log in / Register (developer)**
  - Main Menu: `1 Register` → enter username/password, or `2 Login` → enter username/password.

- **Create or update a manifest locally**
  - Main Menu: `create` → follow prompts (creates/updates `developer/games/<GameName>/manifest.json`).

- **Inspect local manifests**
  - Main Menu: `list` → browse local manifests; select to view JSON.

- **Upload a game/version to the store**
  - Main Menu: `list` → select a local manifest → confirm upload (tars `developer/games/<GameName>/` and streams to dev server).

- **List games on the server**
  - Main Menu: `list` (after local view, it also shows server-side entries).

- **Delete a game from the store**
  - Main Menu: `delete` → pick a game → confirm delete (removes all versions server-side).

- **Delete local game folder**
  - Main Menu: `delete_local` → pick a local game → confirm.

- **List online developers**
  - Main Menu: `list_developers`.

- **Logout**
  - Main Menu: `logout`.

## Built-in sample game
dev sample accounts (username, password):

(bob, peter)

(stan, s)
- Wordle 1.0.0 (CLI, 2 players) author: bob
- BigTwo (CLI, 2 players) author: bob
- Tetris (GUI, 2 players) author: bob
- RockPaperScissors (CLI, 2 players) author: stan

## Tip: AI prompt for game generation:
1. Ensure your manifest is created via "Create manifest".
2. Open AI, and type in the following prompt and replace <game_name> and <username> as one see fit.:

```aiignore
design a <game_name> game under developer/games/<username> while following the game spec design md file allied with the given manifest. Implement the game based on these two files, and you may not modify these two files in any way, you may only design your program based on the two files. 
```

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



# HW4 Architecture
Menu-driven platform with two roles: developers upload and manage games; players browse the store, download games, join rooms, play, and leave reviews. Two TCP servers power the system:
- Developer server: `140.113.17.11:16533`
- User/lobby server: `140.113.17.11:16534`

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
│   │   │   ├── tetris_server.cpp
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

```
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

