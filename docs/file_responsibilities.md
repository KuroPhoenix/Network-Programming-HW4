Totally fair question. Let’s turn that tree into “this file exists because it does X, Y, Z” so you don’t end up with mystery modules.

I’ll keep it **conceptual** (what each piece is responsible for), not implementation code.

---

## Top level of the repo

```text
game-store/
├── README.md
├── Makefile
├── scripts/
├── server/
├── dev_client/
├── player_client/
└── docs/
```

### `README.md`

* For the TA (and you in 3 weeks).
* Explains:

  * How to start dev server / lobby server.
  * How to start dev client / player client.
  * Where to configure IP/port.
  * A very short walkthrough: “Dev uploads → player downloads → create room → play”.

### `Makefile`

* Quality-of-life:

  * `make dev_server`
  * `make lobby_server`
  * `make dev_client`
  * `make player_client`
* For compiled languages, runs your compiler.
* For Python, can just be wrappers for `python server/main_dev_server.py` etc.

### `scripts/`

* Tiny shell / batch files that wrap common commands.

  * `run_dev_server.sh`
  * `run_lobby_server.sh`
  * `run_dev_client.sh`
  * `run_player_client.sh`
* TA doesn’t need to memorize anything; just run your scripts.

### `docs/architecture.md`

* One-page explanation:

  * What servers exist.
  * What the main modules do.
  * Rough sequence for core flow (D1/D2/P2/P3).

### `docs/protocol.md`

* Human-readable description of:

  * Main request/response types.
  * Fields (without code).
* So in oral exam you can point to it instead of remembering everything.

---

## `server/` – everything that lives on系計 Linux

```text
server/
├── main_dev_server.py
├── main_lobby_server.py
├── config/
├── data/
├── uploaded_games/
├── core/
└── util/
```

### `main_dev_server.py`

* The **Developer Server** executable.
* Responsibilities:

  * Listen on a fixed port for dev clients.
  * For each incoming connection:

    * Read messages.
    * Use `core.protocol` to decode them.
    * Dispatch to `core.auth` / `core.games` / `core.versions` / `core.storage`.
    * Send back replies.
  * No business rules inside; it’s just glue:

    * `msg.type == "CREATE_GAME" → core.games.create_game(...)`.

### `main_lobby_server.py`

* The **Lobby/Store Server** executable (for players).
* Responsibilities:

  * Listen on another port for player clients.
  * Handle:

    * Player register/login.
    * Store browsing (list games, details).
    * Download requests (hand off to `core.storage`).
    * Lobby operations (list rooms, create/join/leave).
    * Reviews.
  * Also uses `core.protocol` to encode/decode messages.
  * May call `core.game_launcher` to spawn a game server when a room starts.

---

### `config/server_config.yaml`

* Central config for the server.
* Examples of contents:

  * Dev server IP/port.
  * Lobby server IP/port.
  * Path to `data/` folder and `uploaded_games/`.
  * Maybe max rooms, log level, etc.
* So you don’t hardcode path/port in code.

---

### `data/` (persistent state)

Contains whatever storage you choose (DB files, JSON, etc.):

* `users.*` – developer + player accounts, hashed passwords, maybe sessions.
* `games.*` – game metadata.
* `versions.*` – per-version info.
* `reviews.*` – ratings & comments.
* `rooms.*` (if you persist room history / play history).

The point:

> When the server restarts, the **Game Store and user accounts still exist.**

---

### `uploaded_games/`

* Physical game packages that devs have uploaded and players will download.
* Structure like:

```text
uploaded_games/
  <game_id_1>/
    v1.0/
      manifest.json
      ...game files...
    v1.1/
      manifest.json
      ...game files...
  <game_id_2>/
    ...
```

* Only the **server** writes here.
* Developer’s local `games/` never gets read directly by players.

---

### `core/` – server-side business logic

```text
core/
├── auth.py
├── games.py
├── versions.py
├── storage.py
├── lobby.py
├── reviews.py
├── game_launcher.py
└── protocol.py
```

#### `auth.py`

* Manages **accounts & sessions** for both dev and player.
* Responsibilities:

  * Register dev / player:

    * Check if username already exists (per type).
    * Hash password, store in `data/`.
  * Login dev / player:

    * Validate password.
    * Enforce “no duplicate login or override old session” rule.
  * Session tracking:

    * Generate session tokens / ids.
    * Map connection → session → user info.
* Everyone else (`games`, `lobby`, etc.) asks `auth`:

  * “Who is this session? Are they a dev or player?”

#### `games.py`

* **Game metadata layer** (not versions yet).
* Responsibilities:

  * Define what a `Game` record contains:

    * id, name, description, type (CLI/GUI, max players, etc.), author_id, status (online/offline).
  * Operations:

    * `create_game(dev_id, info)` – new game entry.
    * `update_game_metadata(dev_id, game_id, new_info)` – change description, etc.
    * `down_shelf_game(dev_id, game_id)` – mark as offline.
    * `list_games_for_dev(dev_id)` – for D1/D2/D3 UI.
    * `list_public_games()` – for P1 store view.
    * `get_game_detail(game_id)` – full info, including maybe average rating (pulling from `reviews.py`).
* Enforces **ownership**:

  * Only the dev who created the game can modify it.

#### `versions.py`

* Tracks **versions** of each game.
* Responsibilities:

  * Define `GameVersion`:

    * id, game_id, version string (“1.0.0”), storage path, status (`ACTIVE`, maybe `PENDING`), upload time, changelog.
  * Operations:

    * `add_version(dev_id, game_id, version_info, storage_path)`:

      * Called after `storage` finishes saving files.
      * Updates DB so this version exists.
      * Optionally set it as latest.
    * `get_latest_version(game_id)` – for player downloads and room creation.
    * `get_version_by_id` or `get_version(game_id, version_str)`.
    * Mark a version as active/inactive if you want.

This is where you ensure **atomic behavior** between metadata and files (working with `storage.py`).

#### `storage.py`

* All **filesystem** operations for uploaded games.
* Responsibilities:

  * Compute paths:

    * `get_temp_upload_path(game_id, version_id)`
    * `get_final_upload_path(game_id, version_id)`
  * Save file contents:

    * Write uploaded bytes to temp folder.
  * Atomic promotion:

    * Once upload completes, rename `temp → final`.
  * Deletion:

    * Remove a version’s folder if game/version is removed.
* It doesn’t “understand” games as concepts – it just reads/writes directories/files.

#### `lobby.py`

* Manages **online players & rooms**.
* Responsibilities:

  * Track online players:

    * Which player is in which room.
  * Room logic:

    * `create_room(player_id, game_id)`:

      * Check game is online.
      * Fetch latest version from `versions.py`.
      * Create room with `room.game_id`, `room.version_id`.
    * `join_room(player_id, room_id)`, `leave_room`, `destroy_room`.
    * Manage room status: `WAITING`, `PLAYING`, `FINISHED`.
  * Provide data:

    * `list_rooms()` – for lobby view.
    * `list_players()` – for lobby “player list”.

This is purely “lobby state”; it doesn’t launch game processes itself (that’s `game_launcher.py`).

#### `reviews.py`

* All rating & comment data (P4).
* Responsibilities:

  * Define `Review` records: game_id, player_id, score, text, timestamp.
  * Operations:

    * `add_review(player_id, game_id, score, comment)`.
    * `list_reviews(game_id)` – for game detail screen.
    * `get_average_score(game_id)`.
  * Optional:

    * Check that the player has actually played the game (via room history).

#### `game_launcher.py`

* Starts **game servers** for rooms (ties into your HW1/HW2 game).
* Responsibilities:

  * Given `(game_id, version_id, room_id)`:

    * Locate `uploaded_games/game_id/version_id/manifest`.
    * Read server command/path from manifest.
    * Choose a free port.
    * Spawn game server process with that port, maybe room_id.
  * Track mapping: `room_id → {process, port}`.
  * Provide info to lobby:

    * So lobby can tell players: “connect to IP X, port Y”.
  * Clean up:

    * Kill/clean processes on room end or timeout.

#### `protocol.py`

* Defines how clients and servers talk (so both sides “speak the same language”).
* Responsibilities:

  * Enumerate message types / opcodes:

    * e.g. `"REGISTER_DEV"`, `"LOGIN_PLAYER"`, `"LIST_GAMES"`, `"CREATE_ROOM"`, etc.
  * Provide helper functions:

    * Encode Python/struct → bytes/string.
    * Decode bytes/string → structured object.
  * Define error codes / status codes (success, invalid auth, etc.).

Clients should **import these constants** so they don’t mistype message names.

---

### `util/logger.py`

* Central logging helpers:

  * unify log format (`[time] [LEVEL] message`).
  * Maybe log to file `server.log`.
* So the whole server can do: `logger.info("New room created ...")`.

### `util/validators.py`

* Generic validation helpers:

  * “Is this username valid?”
  * “Is this version string format valid?”
  * “Is rating between 1 and 5?”
* Keeps these checks out of business logic modules so they stay clean.

---

## `dev_client/` – developer-side program

```text
dev_client/
├── main.py
├── config/
├── template/
├── games/
├── ui/
├── api/
├── packaging/
└── util/
```

### `main.py`

* Entry point when you run the developer client.
* Responsibilities:

  * Load config.
  * Connect to Dev Server (or connect on demand).
  * Run the main loop:

    * show login menu (from `ui.main_menu`),
    * after login, show dev menu (from `ui.dev_menu`).
  * Handle global errors (e.g. lost connection, clean exit).

### `config/dev_client_config.yaml`

* Holds:

  * Dev server IP/port.
  * Default path to `games/` and `template/` folders.
* TA can change it without touching code.

### `template/`

* Project skeletons for new games.
* Example subfolders:

  * `cli_2p_template/`
  * `gui_2p_template/`
  * `multi_template/`
* Each contains:

  * A starter `manifest.json`.
  * Minimal server/client stub code.
* The “create game project” feature copies one of these into `games/`.

### `games/`

* Dev’s local game projects (their working directory).
* Used only by **developer**, not players.
* Each game folder:

  * `manifest.json`.
  * Source code, assets, etc.
* When dev “uploads”, you read from here, package it, and send it to server.

---

### `ui/` – developer menus & interaction

#### `ui/main_menu.py`

* Shows the first screen:

  * Register dev account.
  * Login as dev.
  * Exit.
* Once logged in, routes to `dev_menu`.

#### `ui/dev_menu.py`

* Menu after login, like:

  * List my games.
  * Create a new game (metadata only).
  * Upload new version for a game.
  * Update game info.
  * Down-shelf (remove from store).
  * Logout.

* Each option:

  * Asks for user input.
  * Calls functions in `api/dev_api.py`.
  * Displays results in a user-friendly way (tables, numbered lists).

#### `ui/input_helpers.py`

* Small utilities for robust CLI input:

  * read integer in `[1, N]` with retry on invalid input.
  * yes/no confirmation.
  * maybe table formatting.

---

### `api/dev_api.py`

* Dev-client’s **network wrapper**.
* Responsibilities:

  * Open/close socket(s) to dev server.
  * Functions like:

    * `register_dev(username, password)`
    * `login_dev(username, password)`
    * `list_my_games()`
    * `create_game(info)`
    * `upload_version(game_id, version_info, file_stream or path)`
  * Internally:

    * Build requests using `server/core/protocol` definitions.
    * Send to server and decode responses.
  * UI code does **not** deal with raw sockets; it just calls these.

---

### `packaging/manifest.py`

* For reading & verifying **local** manifest in `dev_client/games/…`.
* Responsibilities:

  * Load `manifest.json` from a game folder.
  * Check required fields (name, version, commands, etc.).
  * Validate formats.
  * Provide a convenient object to the rest of the client.

### `packaging/packer.py`

* Converts a game folder into something uploadable.
* Responsibilities:

  * Decide which files to include (maybe use manifest or a simple rule).
  * Optionally compress into archive (zip/tar) or stream files.
  * Provide an interface like:

    * `prepare_upload(game_folder) → (version_str, file_handle/byte_stream)`

---

### `util/logger.py`

* Local logging for developer client.

  * E.g. log upload failures, protocol errors, etc.

---

## `player_client/` – player-side program

```text
player_client/
├── main.py
├── config/
├── downloads/
├── ui/
├── api/
├── downloads_mgr/
├── launcher/
└── plugins/
```

### `main.py`

* Entry point for the player client.
* Responsibilities:

  * Load config.
  * Connect to Lobby/Store server.
  * Show top main menu:

    * Login/Register.
    * Store.
    * Lobby.
    * Plugins (optional).
    * Logout/Quit.
  * Coordinate switching between `ui.main_menu`, `ui.store_menu`, `ui.lobby_menu`.

### `config/player_client_config.yaml`

* Holds:

  * Lobby server IP/port.
  * Base path for `downloads/`.
  * Maybe default player name for quick testing.

### `downloads/`

* Concrete representation of “Player downloaded games”.
* Structure:

```text
downloads/
  Player1/
    <game_name>/
      v1.0/
        manifest.json
        ...game files...
      v1.1/
  Player2/
    ...
```

* Each player has separate subfolder to simulate “different machines” as spec suggests.

---

### `ui/` – menus for store, lobby, reviews

#### `ui/main_menu.py`

* The top-level menu after client starts.
* Handles:

  * Login/Register (calls `api.lobby_api`).
  * After login:

    * “Store”.
    * “Lobby”.
    * “Plugins” (if implemented).
    * “Logout”.
* Delegates to more specific menus (`store_menu`, `lobby_menu`, etc.).

#### `ui/store_menu.py`

* Implements P1 & P2:

  * List all available games from server.
  * For a selected game:

    * Show details (name, author, type, description, rating).
    * Show whether it is installed + which local version.
    * Provide actions:

      * Download latest.
      * Update to latest (if local version is older).
* Interacts with:

  * `api.lobby_api` to get store info and download data.
  * `downloads_mgr` to actually save files.

#### `ui/lobby_menu.py`

* Implements P3:

  * View lobby state:

    * Who is online.
    * Existing rooms (game + host + players).
  * Actions:

    * Create room (choose game).
    * Join room.
    * Leave room.
    * Start game (for host).
* When starting game:

  * Calls `launcher.client_launcher` with selected `(game_id, version_id)` and server IP/port.

#### `ui/review_menu.py`

* Implements P4:

  * For a chosen game:

    * Show existing reviews and average score.
    * Allow the logged-in player to add/update their review:

      * Score (1–5).
      * Short text.
* Uses `api.lobby_api` to talk to review endpoints.

#### `ui/input_helpers.py`

* Same type of helpers as dev side:

  * safe integer input,
  * pretty printing lists,
  * basic validation messages.

---

### `api/lobby_api.py`

* Player-client’s network wrapper.
* Responsibilities:

  * Manage socket connection to Lobby/Store server.
  * Provide high-level functions:

    * Auth:

      * `register_player`, `login_player`.
    * Store:

      * `list_games`, `get_game_detail`, `get_latest_version(game_id)`.
    * Download:

      * initiate download, receive file bytes/chunks.
    * Lobby:

      * `list_rooms`, `create_room`, `join_room`, `leave_room`.
    * Reviews:

      * `add_review`, `get_reviews`, etc.
  * Hide raw protocol details from UI code.

---

### `downloads_mgr/` – local install/update logic

#### `downloads_mgr/versions.py`

* Records & checks which versions are installed locally.
* Responsibilities:

  * For a given player + game:

    * Determine installed version(s) by reading local manifests.
    * Compare installed version to server latest version.
  * Decide if “update required”, “up-to-date”, or “not installed”.

#### `downloads_mgr/files.py`

* Handles actual filesystem writes for downloads.
* Responsibilities:

  * Create player/game/version folders.
  * Write incoming bytes to a temporary path.
  * Only after download completes, rename temp → final.
  * Clean up partial downloads on failure.

#### `downloads_mgr/manifest.py`

* Reads manifest from **downloaded** game folders.
* Responsibilities:

  * Validate manifest is sane (e.g., correct type, executable paths).
  * Provide information to:

    * `launcher.client_launcher` (client command),
    * `ui.store_menu` (local info).

---

### `launcher/client_launcher.py`

* Starts **game client** process for the player.
* Responsibilities:

  * Given:

    * Player name,
    * Path to downloaded game,
    * Game server IP/port,
    * Possibly room id/token.
  * Read manifest from `downloads/.../manifest`.
  * Spawn the client process (CLI or GUI) with appropriate args.
  * Wait for it to finish or detect exit.
  * On exit, return to lobby menu gracefully.

This is the “bridge” between your game store system and the HW1/HW2 game programs.

---

### `plugins/` (optional for bonus)

#### `plugins/registry.py`

* Keeps a list of **known plugins**:

  * Name, description, plugin id, current version.
* Could be static or loaded from server.

#### `plugins/loader.py`

* Manages:

  * Installing plugin files (into `plugins/installed/`).
  * Loading them dynamically at runtime (if your language supports it).
  * Tracking which plugins are enabled for this player.
* Provides hooks for UI:

  * E.g. room chat plugin: `if plugin_installed("room_chat"): show chat panel`.

#### `plugins/installed/`

* Each subfolder is one installed plugin, e.g.:

  * `room_chat/`
  * `custom_theme/`
* Contains plugin-specific config/manifests/code.

---

That’s the intent of every file/directory in the layout I suggested.

If you tell me **which stage you’re about to implement first** (auth, game metadata, or something else), I can zoom in on just the relevant files and sketch what kinds of **functions and data** they should expose to other modules, so you have a very clear interface to code against.
