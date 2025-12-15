# Game Store System (HW3)

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
