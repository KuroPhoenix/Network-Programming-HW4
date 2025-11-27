
## High-level strategy

* Always aim for:
  **“One small feature that goes from client → server → storage (or back)”**
  instead of “build all the server, then all the client”.
* Keep two main executables:

  * `dev_client` + `dev_server`
  * `player_client` + `lobby_server`
* Reuse core modules under the hood, but from your POV, you progress via “stages” below.

### Cross-cutting milestones
- **Protocol/schema freeze:** After Stage 2, lock message names/fields and DB file schema (users/games/versions) before heavy upload/download work.
- **Observability:** Shared logger format, log auth, metadata changes, upload/download start/end, room lifecycle, launcher spawn/exit. Add simple start/stop scripts.
- **Concurrency & cleanup:** Decide per-connection thread vs. async for servers; define temp-dir cleanup and process reaping policy (launcher).
- **Integrity:** Upload/download use chunking with temp-to-final rename, checksum optional, rollback on failure.
- **Port allocator:** Single allocator + registry for launched game servers; free on room end/crash.
- **Smoke tests:** After Stage 5 and Stage 7, run scripted smoke to catch regressions (upload→download→room→launch).

I’ll give you, for each stage:

* What you implement
* What you can run to verify
* Which homework Use Cases it nudges toward

---

## Stage 0 – Core models & local game manifest (no networking)

**Goal:** Have a clear notion of “a game” & “a version” and be able to launch one locally.

### Implement

* Data structures in a `core/` folder:

  * `User`, `Game`, `GameVersion`, `Room` (just classes/structs).
* Decide the **game manifest** format for uploaded games:

  * E.g. a JSON/YAML file:

    * `game_id` (or name)
    * `version`
    * `type` (CLI/GUI, 2P/multi)
    * `server_command`, `client_command`
* Write a tiny **local launcher script**:

  * Reads a manifest from a game folder.
  * Runs the `server_command` in one terminal / process.
  * Runs the `client_command` in another (or sequentially) just to make sure HW1/HW2 game still works.

### Verify

* Run: `python local_launcher.py` (or whatever):

  * It finds e.g. `games/tictactoe/manifest.json`.
  * Starts your HW1/HW2 game process.
* If this works, you know:

  * Your **manifest format is sane**.
  * Your **game process launching is basically working**.

**Definition of done**

* Manifest has required fields (name, version, type, max_players, server_command, client_command).
* Local launcher successfully starts both game server and client from a manifest folder.
* Commands and working directories are documented.

No server. No clients. Just local logic.

---

## Stage 1 – Minimal Auth Server + Test Client

**Goal:** Have a running server process that accepts register/login for dev **and** player.

### Implement

On the **server** side:

* `auth.py` with:

  * In-memory maps or simple file/DB:

    * `developers[username] -> password hash`
    * `players[username] -> password hash`
  * Functions: `register_developer`, `login_developer`, `register_player`, `login_player`.
  * Session tracking (very simple: `session_id → user_id`).
* `dev_server`:

  * Listens on a port.
  * Supports messages:

    * `REGISTER_DEV`
    * `LOGIN_DEV`
* `lobby_server`:

  * Same idea but for:

    * `REGISTER_PLAYER`
    * `LOGIN_PLAYER`
  * (either same binary with a mode flag or two entrypoints that import the same `auth.py`)

On the **client** side (very minimal):

* For developer:

  * `dev_client` with a **tiny menu**:

    * 1. Register
    * 2. Login
    * 3. Exit
* For player:

  * `player_client` with same tiny menu for players.

### Verify

* Run `dev_server`.
* Run `dev_client`:

  * Register new dev.
  * Try logging in with correct/incorrect passwords.
* Run `lobby_server`.
* Run `player_client`:

  * Same tests.
* Confirm:

  * Duplicate registration rejected.
  * Wrong password shows error, not crash.
  * Session tracking works (e.g. same user logging in twice behaves as you decided).

**Definition of done**

* REGISTER/LOGIN for dev and player both work with clear error messages.
* Session tokens returned; old token invalidated on new login.
* Basic logs for auth success/fail.
* Manual smoke: register + bad password + good login on both servers.

You’ve now got a **real running client+server pair** you can extend.

---

## Stage 2 – Dev: Manage game metadata (no files yet)

**Goal:** Dev can log in and create/list games on the server. No upload yet; just metadata.

### Implement

Server:

* `games.py`:

  * Structures: `Game`.
  * Functions:

    * `create_game(dev_id, name, description, type)`
    * `list_games_for_dev(dev_id)`
    * `list_all_games()` (for future player store).
* Dev server’s protocol adds:

  * `CREATE_GAME`
  * `LIST_MY_GAMES`

Dev client:

* Extend menu after login:

  ```text
  === Developer Menu ===
  1. List my games
  2. Create new game
  3. Logout
  ```

* `Create new game` prompts:

  * Name
  * Description
  * Game type (CLI/GUI, max players, etc.)

### Verify

* Start `dev_server`.
* Start `dev_client`.
* Login as dev.
* Create 1–2 games.
* List them.
* Restart server (if you already have some simple persistence) and confirm games persist, or at least behave correctly in memory for now.

You now satisfy the **“part of D1”**: managing game entries (minus version/files).

**Definition of done**

* CREATE_GAME and LIST_MY_GAMES implemented; ownership enforced.
* Game metadata persisted (file/DB) across restart.
* Protocol fields for auth + game metadata frozen for later stages.
* Logs for metadata changes.

--- 

## Stage 3 – Player: View game list (store browsing, still no files)

**Goal:** Player can see the game catalog created by developers.

### Implement

Server (reuse `games.py`):

* Make sure **Lobby/Store server** can call:

  * `list_all_games()`
  * `get_game_detail(game_id)`.

Add protocol commands to lobby/store server:

* `LIST_GAMES`
* `GET_GAME_DETAIL`

Player client:

* Add main menu entry for “商城 / 遊戲列表”:

  ```text
  === Main Menu ===
  1. Store
  2. (other items later)
  3. Logout
  ```

* Store submenu:

  ```text
  === Store ===
  1. List games
  2. View game detail
  3. Back
  ```

### Verify

* Dev side:

  * Create some game entries with `dev_client`.
* Player side:

  * Login with `player_client`.
  * Enter Store → list games.
  * View details of a game (name, description, type, maybe placeholder rating).

Now you’ve basically implemented **P1** (minus reviews).

**Definition of done**

* LIST_GAMES and GET_GAME_DETAIL implemented in lobby server; empty lists handled gracefully.
* Client shows list/detail without crashing on missing fields.
* Protocol response shape for games frozen.

--- 

## Stage 4 – Dev: Upload version files (local simulation first)

**Goal:** Actually move game directories from your dev machine’s `games/` into a server storage area, but maybe **start with local “copy”** before network file transfer.

### Phase 4A – Local copy simulation

Implement `storage.py`:

* Functions like:

  * `store_new_version(game_id, version_str, source_folder)`:

    * Copy from `dev_client/games/<game_name>` into something like `server/uploaded_games/<game_id>/<version_str>/`.
* Update `versions.py`:

  * `add_version(dev_id, game_id, version_str, path)` – registers new version.
  * Keep mapping `Game.current_version_id`.

Then write a **local test script** that:

1. Picks an example game folder.
2. Calls `store_new_version(...)`.
3. Verifies the files appear in `server/uploaded_games/...`.
4. Confirms `versions` metadata updated.

No network yet. Just pure filesystem + functions.

### Phase 4B – Integrate with Dev server/client

* Dev server:

  * New command: `UPLOAD_VERSION`.
  * On receive:

    * For now, maybe accept a **path string** relative to dev machine and (during early dev) still do a local copy to simulate.
    * Or start implementing file streaming if you’re ready.
* Dev client:

  * After login, menu for “Upload new version” under “My games”.
  * Prompts:

    * Which game (by index / id).
    * Version string.
    * Local folder path (for now).

### Verify

* Use your HW1/HW2 game folder as a test.
* Upload a version.
* Check that on the server side:

  * Files appear in the right path.
  * `GameVersion` entry is created.
  * `Game.current_version` is updated.

You now have “D1 with real files” in a basic form.

Later you can improve upload from local path → actual streamed bytes.

**Definition of done**

* UPLOAD_BEGIN/CHUNK/END implemented with temp directory and final rename; cleanup on failure/cancel.
* Optional checksum accepted/verified; bad checksum aborts and cleans temp.
* Duplicate version string rejected with clear error.
* Logs record upload start/end + bytes.
* Manual script: upload sample game, verify files under `server/uploadedGame/<game>/<version>/`.

--- 

## Stage 5 – Player: Download/update version (P2, in a basic form)

**Goal:** Player can download the latest version from server to `downloads/PlayerX/...` and see version info.

### Implement

Server:

* Extend `versions.py` with:

  * `get_latest_version(game_id)` → returns version metadata + path.
* Lobby/Store server protocol:

  * `GET_LATEST_VERSION(game_id)`
  * `DOWNLOAD_VERSION(game_id, version_id)` (or similar).

Player side:

* `downloads.py`:

  * Manage folder `downloads/<PlayerName>/<GameName>/<version>/...`
  * Functions:

    * `get_local_version(game_id)` (if any).
    * `needs_update(local_version, server_version)`.
    * `download_version(...)` – for first iteration, you can simulate as a copy from some shared folder if dev & player are on same machine; later, send bytes over TCP.
* Store menu:

  * For a chosen game, add options:

    * “Download / Update to latest version”
    * Show current local version vs latest server version.

### Verify

* Dev:

  * Have at least 2 versions uploaded for some game (v1.0, v1.1).
* Player:

  * Login.
  * Store → choose game.
  * If no local version: download.
  * Verify files appear under `downloads/<PlayerName>/...`.
* Later, have server say “current version is v1.1” and client decide to update.

At this point you’ve got a *runnable P2 prototype* (even if file transfer is still simplified).

**Definition of done**

* DOWNLOAD_BEGIN/CHUNK/END implemented with temp path (`.part`) and final rename.
* Optional checksum verified; on mismatch delete temp and surface error.
* Client compares local vs latest and prompts to update; handles “no local version”.
* Manual smoke: upload v1.0 and v1.1, download both, ensure folder structure in `user/downloads/<Player>/<Game>/<version>/`.

--- 

## Stage 6 – Lobby & rooms (P3 logic, but with fake game)

**Goal:** Players can see lobby, create rooms, join rooms, even if actual game processes aren’t invoked yet.

### Implement

Server (`lobby.py`):

* Keep:

  * List of online players.
  * Rooms: `Room(id, game_id, version_id, host_player_id, player_ids, status)`.
* Operations:

  * `create_room(player_id, game_id)` → attaches latest version id.
  * `join_room(player_id, room_id)`
  * `leave_room(player_id, room_id)`
  * `list_rooms()`, `list_players()`.

Lobby server protocol:

* `LIST_ROOMS`
* `CREATE_ROOM`
* `JOIN_ROOM`
* `LEAVE_ROOM`

Player client:

* Add “Lobby” menu:

  ```text
  === Lobby ===
  1. List rooms
  2. Create room
  3. Join room
  4. Back
  ```

* For now, “create room”:

  * Asks which game (from store list).
  * Ensures you have a local version (maybe auto-download/update if missing).
  * Sends `CREATE_ROOM`.

### Verify

* Run two `player_client` processes.
* Both login with different users.
* Player A: creates room for game G.
* Player B: lists rooms, sees it, joins it.
* Check server logs to see players join/leave.

You have **lobby behavior** tested independently of actual game execution.

**Definition of done**

* LIST_ROOMS/CREATE_ROOM/JOIN_ROOM/LEAVE_ROOM implemented with consistent room state.
* Concurrency model chosen (thread-per-connection vs. async) and documented; lobby data access is thread-safe.
* Logging for room create/join/leave.
* Manual smoke with two players joining/leaving.

--- 

## Stage 7 – Wire in real game processes (full P3)

**Goal:** Now tie room creation / start into launching HW1/HW2 game server/client processes with the manifest.

### Implement

Server side:

* `game_launcher.py` (or in `lobby.py` as a helper):

  * For a room referencing `(game_id, version_id)`:

    * Find `uploaded_games/game_id/version_id/manifest`.
    * Spawn the **game server process** with appropriate port, room id, etc.
  * Store `room_id → game_server_process, port`.
* When a player “starts game” / “ready”:

  * Lobby server responds with:

    * `game_server_ip + port`
    * Some identifier for the room.

Player side:

* When you choose “Start game” (or auto when room is ready):

  * `downloads.py` finds local path for `(game_id, version_id)`.
  * Reads manifest.
  * Spawns **game client** process with server IP/port from lobby.

### Verify

* Full run:

  * Dev uploads game.
  * Player downloads it.
  * Player creates room, others join.
  * Host starts game → server spawns game server process.
  * Each player’s client spawns game client and connects.
  * When game exits, you return to Lobby menu.

This completes the **core of P3** (with your HW1/HW2 game integrated).

**Definition of done**

* Port allocator hands out free ports; registry freed on room end/crash.
* Launcher spawns game server, tracks pid, reaps on finish/timeout; start failure returns error and room rolls back to WAITING/closed.
* START_ROOM returns host/port to players; clients launch game client with manifest placeholders filled.
* Smoke script: upload → download → create room → start → players connect → return to lobby.

--- 

## Stage 8 – Reviews (P4)

**Goal:** After playing, players can rate games and view ratings in the store.

### Implement

Server (`reviews.py`):

* `add_review(player_id, game_id, score, comment)`
* `list_reviews(game_id)`
* `get_average_score(game_id)`

Optionally:

* Store “play history” somewhere (rooms that finished), so you can enforce “only players who played can review.”

Lobby/Store protocol:

* `ADD_REVIEW`
* `LIST_REVIEWS`
* `GET_AVG_SCORE`

Player client:

* On game detail page:

  * Show current average score and some comments.
  * Provide option: “Add/Update my review” → input score + text.
* After game ends:

  * Optionally prompt: “Do you want to review this game now?”

### Verify

* Play a game at least once.
* Add a review.
* Re-open game detail → see updated average and comments.

P4 covered.

**Definition of done**

* ADD_REVIEW/LIST_REVIEWS implemented; score validation (1–5); optional played-check enforced if history exists.
* Game detail shows average and handles “no reviews” gracefully.
* Reviews persisted.

--- 

## Stage 9 – Optional plugins (if time)

At this point, core HW is functionally there. Plugin system is a separate vertical slice; you can:

* Add plugin registry module.
* Add plugin install/remove UI.
* Add a chat plugin for rooms (if you want).

But don’t even think about this until Stages 0–8 are reasonably stable.

---

## TL;DR timeline

If you like short checklists:

1. **Stage 0** – Manifest + local launcher.
2. **Stage 1** – Auth server + two login clients.
3. **Stage 2** – Dev: create/list games (metadata only).
4. **Stage 3** – Player: view store (list + details).
5. **Stage 4** – Dev: upload real versions (local copy → then over network).
6. **Stage 5** – Player: download/update versions.
7. **Stage 6** – Lobby + rooms (no real game).
8. **Stage 7** – Hook rooms to real game servers/clients.
9. **Stage 8** – Reviews.

At any point you have **something runnable you can show**:

* After Stage 1: login demo
* After Stage 3: “Dev creates game → Player sees game”
* After Stage 5: “Dev uploads → Player downloads”
* After Stage 7: full “upload → download → create room → play game”

If you tell me which stage you’re at right now (or want to start from), I can help you plan that stage in more detail (e.g., what messages you need between client/server, what to log, what to stub out) without drifting into code-writing.
