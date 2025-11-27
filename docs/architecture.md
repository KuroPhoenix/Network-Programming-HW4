# Architecture

This describes how the three codebases in this repo talk to each other and where data/files live. Names below match the actual folders and entrypoints in the repo.

## Runtime components
- `server/dev_server.py` — Developer server; handles dev auth, game metadata, version registration, and receiving uploads into `server/uploadedGame/`.
- `server/user_server.py` — Lobby/Store server; handles player auth, store browsing, downloads, lobby/rooms, reviews, and launches game servers.
- `developer/dev.py` — Developer client; menu-driven UI that calls `developer/api/*` to talk to `dev_server.py`.
- `user/main.py` — Player client; menu-driven UI that calls `user/api/*` to talk to `user_server.py`.
- Game processes — Spawned by lobby server and player clients using manifests stored with each uploaded version.

## Shared server core
- `server/core/auth.py` — Accounts + sessions for developers and players (duplicate login policy defined in protocol).
- `server/core/games.py` — Game metadata (id, name, description, type, status ONLINE/OFFLINE, owner).
- `server/core/versions.py` — Per-version records (game_id, version string, path, upload time, latest flag).
- `server/core/storage.py` — File IO for uploads/downloads; temp-to-final atomic moves in `server/uploadedGame/`.
- `server/core/lobby.py` — Online players, rooms, room lifecycle, and routing to `game_launcher`.
- `server/core/reviews.py` — Ratings/comments with optional played-check.
- `server/core/game_launcher.py` — Spawns game server process for a room based on manifest; tracks port/pid and cleanup.
- `server/core/protocol.py` — Message type constants and helpers shared by both servers.

## Data and file layout
- Persistent data: `server/data/` (user accounts, games, versions, reviews, rooms). Must survive server restart.
- Uploaded games: `server/uploadedGame/<game_id>/<version>/...` with `manifest.json` inside each version folder. Only servers write here.
- Developer local workspace: `developer/games/` and `developer/template/` (not used by players directly).
- Player installs: `user/downloads/<PlayerName>/<GameName>/<version>/...` created only through downloads, never edited manually.

## Manifest (server-stored with each version)
Minimal required fields:
```json
{
  "game_name": "tictactoe",
  "version": "1.0.0",
  "type": "cli" | "gui",
  "max_players": 2,
  "server_command": "python server/main.py --port {port} --room {room_id}",
  "client_command": "python client/main.py --host {host} --port {port} --player {player_name}"
}
```
Placeholders in braces are filled by lobby/player client at runtime. Add more fields as needed (assets, description, etc.).

## Key flows (align with HW Use Cases)
- D1 (Upload new game):
  1) Dev registers/logs in (developer → dev_server auth).  
  2) Dev creates game metadata (CREATE_GAME).  
  3) Dev uploads a version (UPLOAD_BEGIN/CHUNK/END) → files land in `server/uploadedGame/...`; `versions.py` marks latest.
- D2 (Update existing game):
  - Same as D1 but game already exists; upload registers new version and toggles latest. Optional status change to OFFLINE to block new rooms.
- D3 (Down-shelf):
  - Dev sets game status OFFLINE; lobby server excludes it from new downloads/rooms while keeping history.
- P1 (Browse store):
  - Player logs in → LIST_GAMES/GET_GAME_DETAIL from lobby server, which reads `games.py` + `reviews.py`.
- P2 (Download/update):
  - Player asks LATEST_VERSION; compares with local; DOWNLOAD_BEGIN/CHUNK/END writes to `user/downloads/...` via temp + rename. Versions remain side-by-side.
- P3 (Rooms + play):
  - Player creates room → lobby selects latest version id and registers room in `lobby.py`.  
  - Host starts room → `game_launcher` reads manifest for that version, finds a free port, spawns game server, and stores `room_id → {pid, port}`.  
  - Lobby replies with host/port; each player’s client uses local manifest to spawn the game client process pointing to that host/port.  
  - On room end or crash, launcher kills process and `lobby.py` cleans up room state.
- P4 (Reviews):
  - Player posts review after playing; stored in `reviews.py`; GET_GAME_DETAIL includes average + samples.

## Concurrency and lifetime
- Each server handles one TCP connection per client; requests are per-message.  
- Sessions are tied to tokens returned on login; old tokens are invalidated when a new login succeeds for the same account.  
- File uploads/downloads are chunked; state is tracked per upload_id/download_id to allow resume/fail-fast.  
- Game server processes are children of lobby server; lobby must reap/kill them on room end, timeout, or server shutdown.

## Logging (see docs/logs.md)
- Standard log fields: timestamp, level, component, session/user, action, result.  
- Critical transitions to log: auth (success/fail), game create/update, upload start/end, download start/end, room create/join/leave/start, launcher spawn/exit, review add.
