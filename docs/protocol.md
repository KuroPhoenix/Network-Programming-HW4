# Protocol

Transport and envelopes used by both `dev_server.py` and `user_server.py`. Keep clients and servers strictly aligned with these names/fields.

## Transport
- TCP, persistent connection per client.
- Messages are UTF-8 JSON, newline-delimited (one JSON object per line). No extra framing.
- Binary file data is base64 in `data_b64` fields.

## Envelope
- Request:  
  ```json
  { "type": "REGISTER_DEV", "token": "optional-session-token", "payload": { ... } }
  ```
- Response:  
  ```json
  { "status": "ok" | "error", "code": 0 | int, "message": "human text", "payload": { ... } }
  ```
- `token` is required for any action after login. Servers invalidate old tokens when a newer login for the same account succeeds.

## Status codes
- 0 OK
- 100 INVALID_REQUEST (missing/extra fields, JSON parse error)
- 101 UNAUTHORIZED (no/invalid token)
- 102 FORBIDDEN (wrong role/ownership)
- 103 NOT_FOUND (game/version/room)
- 104 CONFLICT (duplicate username, duplicate version string, upload already exists)
- 105 BAD_STATE (wrong order: e.g., upload chunk without BEGIN, room full, game offline)
- 120 CHUNK_OUT_OF_ORDER
- 121 CHECKSUM_MISMATCH
- 199 SERVER_ERROR

## Common field conventions
- `game_id`: server-generated string/uuid when created.
- `version`: semver-like string from developer.
- `status`: `"ONLINE"` | `"OFFLINE"`.
- `game_type`: `"cli"` | `"gui"` | `"multi"` (extend as needed).
- `session_token`: returned on login; the same value is placed in request `token`.
- `chunk_size`: suggested bytes for base64-decoded chunk payload (default 4096).

## Developer server commands (`dev_server.py`)
- `REGISTER_DEV` — payload `{ "username": str, "password": str }`  
  - ok payload: `{ "session_token": str }`
- `LOGIN_DEV` — payload `{ "username": str, "password": str }`  
  - ok payload: `{ "session_token": str }`
- `CREATE_GAME` — payload `{ "name": str, "description": str, "game_type": str, "max_players": int }`  
  - ok payload: `{ "game_id": str }`
- `LIST_MY_GAMES` — payload `{}`  
  - ok payload: `{ "games": [ { "game_id", "name", "description", "status", "latest_version" } ] }`
- `UPDATE_GAME_META` — payload `{ "game_id": str, "description": str?, "max_players": int?, "game_type": str? }`
- `SET_GAME_STATUS` — payload `{ "game_id": str, "status": "ONLINE" | "OFFLINE" }`
- `LIST_VERSIONS` — payload `{ "game_id": str }`  
  - ok payload: `{ "versions": [ { "version", "uploaded_at", "is_latest" } ] }`

### Upload flow (dev client → dev server)
1) `UPLOAD_BEGIN` — payload `{ "game_id": str, "version": str, "size_bytes": int, "checksum": str? }`  
   - ok payload: `{ "upload_id": str, "chunk_size": int }`
2) Repeated `UPLOAD_CHUNK` — payload `{ "upload_id": str, "seq": int, "data_b64": str }`  
   - seq starts at 0; server replies `ok` per chunk or `error` with 120/121.
3) `UPLOAD_END` — payload `{ "upload_id": str }`  
   - ok payload: `{ "version": str, "is_latest": bool }`
4) Optional `CANCEL_UPLOAD` — payload `{ "upload_id": str }`

Server stores chunks to temp, verifies optional checksum, then moves to `uploadedGame/<game_id>/<version>/` with manifest inside.

## Lobby/Store server commands (`user_server.py`)
- `REGISTER_PLAYER` — payload `{ "username": str, "password": str }` → `{ "session_token": str }`
- `LOGIN_PLAYER` — payload `{ "username": str, "password": str }` → `{ "session_token": str }`
- `LIST_GAMES` — payload `{}` → `{ "games": [ { "game_id", "name", "status", "latest_version", "avg_score" } ] }`
- `GET_GAME_DETAIL` — payload `{ "game_id": str }` → `{ "game_id", "name", "description", "game_type", "max_players", "status", "latest_version", "avg_score", "reviews_sample": [ { "player", "score", "comment" } ] }`
- `LATEST_VERSION` — payload `{ "game_id": str }` → `{ "version": str, "size_bytes": int, "checksum": str? }`
- `LIST_REVIEWS` — payload `{ "game_id": str }` → `{ "reviews": [ { "player", "score", "comment", "created_at" } ] }`
- `ADD_REVIEW` — payload `{ "game_id": str, "score": int (1-5), "comment": str }`
- `LIST_PLAYERS` — payload `{}` → `{ "online_players": [str] }`
- `LIST_ROOMS` — payload `{}` → `{ "rooms": [ { "room_id", "game_id", "version", "host", "players": [str], "status" } ] }`
- `CREATE_ROOM` — payload `{ "game_id": str }`  
  - ok payload: `{ "room_id": str, "version": str }` (version chosen = latest unless game offline)
- `JOIN_ROOM` — payload `{ "room_id": str }` → `{ "room_id": str, "version": str }`
- `LEAVE_ROOM` — payload `{ "room_id": str }`
- `START_ROOM` — payload `{ "room_id": str }` (host only)  
  - ok payload: `{ "room_id": str, "game_host": str, "game_port": int, "version": str }`

### Download flow (lobby server → player client)
1) `DOWNLOAD_BEGIN` — payload `{ "game_id": str, "version": str? }` (if version missing, server uses latest).  
   - ok payload: `{ "download_id": str, "version": str, "size_bytes": int, "chunk_size": int }`
2) Server sends a stream of messages on the same connection:  
   - `DOWNLOAD_CHUNK` — `{ "download_id": str, "seq": int, "data_b64": str }`  
   - When complete: `DOWNLOAD_END` — `{ "download_id": str, "version": str, "checksum": str? }`
3) On error: `DOWNLOAD_ERROR` — `{ "download_id": str, "code": int, "message": str }`

Client writes to temp path `user/downloads/<Player>/<Game>/<version>.part` and renames to final folder after `DOWNLOAD_END`.

### Lobby state updates
- Polling: clients can call `LIST_GAMES`, `LIST_ROOMS`, `LIST_PLAYERS` periodically.
- Optional notify: server may push `ROOM_UPDATED` (`{ "room": {...} }`) and `PLAYER_PRESENCE` (`{ "online": [...], "offline": [...] }`) messages; clients must tolerate receiving them at any time and redraw menus accordingly.

## Error handling rules
- Any unexpected message type → `error` with code 100.
- Missing/invalid token where required → `error` 101; client should force relogin.
- For duplicate login, previous tokens receive `error` 105 on next request.
- Upload/download chunks with wrong seq → 120; client should retry from correct seq or restart transfer.
