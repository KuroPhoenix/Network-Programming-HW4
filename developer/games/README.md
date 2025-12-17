# Game integration guide

This folder holds store-ready games that can be uploaded and run by the platform. Follow these rules so a new game fits the project without extra glue.

## Directory layout
- Each game lives in `developer/games/<GameName>/`.
- Must contain `manifest.json` describing how to launch server/client.
- Include all code/assets needed to run; do not reach outside the game folder at runtime.
- Package optional assets (art, dictionaries, maps, sounds) under the game folder, ideally under `assets/`, and reference them via the manifest `assets` glob so uploads include them.

## Manifest requirements
See `developer/template/manifest_template.json` for shape. Required fields:
- `game_name`, `version`, `type` (`CLI|GUI|2P|Multi`), `description`, `max_players`.
- `server.command` and `client.command`: use placeholders like `{host}`, `{port}`, `{room_id}`, `{match_id}`, `{player_name}`, `{p1}`, `{p2}`, `{player_count}`, `{players_json_path}`, `{report_host}`, `{report_port}`, `{bind_host}`. GameLauncher fills these. Do not place `{client_token}` or `{report_token}` in command args; pass them via env or token files.
- `server.working_dir` / `client.working_dir`: relative to the game root.
- `assets` list (globs) and optional `healthcheck`. Any file matching `assets` is shipped with the upload and later downloaded to players. Put bulky data (e.g., dictionaries, sprites, sounds) under `assets/`.
- Optional `env` maps for server/client are allowed; values can also use placeholders.
The server stores the manifest with each uploaded version; keep it accurate.

### Example command placeholders
- Server: `python server/main.py --port {port} --room {room_id} --p1 {p1} --p2 {p2} --report_host {report_host} --report_port {report_port}`
- Client: `python client/main.py --host {host} --port {port} --player {player_name}`

## Server runtime contract
- Your game server is launched by GameLauncher with args and env from the manifest. It must:
  - Bind to `{bind_host}` and listen on `{port}`.
  - Validate `client_token` and `match_id` during the client handshake.
  - Accept at least two players; for more players, use `{p1}`, `{p2}`, `{player_count}`, or `{players_json_path}` to map connections.
  - Speak newline-delimited JSON; see helper `send_json`/`recv_json` in existing games.
  - Report lifecycle to the lobby: send `GAME.REPORT` (JSON line) to `{report_host}:{report_port}` with fields `{"type":"GAME.REPORT","status":"STARTED|HEARTBEAT|END|ERROR","room_id":..., "match_id":..., "report_token":...}` plus winner/loser/results/err_msg/reason as appropriate.
  - Send `STARTED` only after the server can accept the client handshake, and `HEARTBEAT` periodically.
  - On graceful shutdown or KeyboardInterrupt, send an `ERROR` report so the lobby can free the room.
  - Handle disconnects: if a player drops, pick a winner/loser and report with reason `disconnect`.
  - Clean up: close sockets, stop threads, and exit without hanging the parent server.

## Client runtime contract
- The platform launches your client with `{host}`, `{port}`, `{room_id}`, `{match_id}`, `{client_token}`, and `{player_name}`.
- On Ctrl-C or user quit, send a quit/surrender message to the game server before exiting so the server can finish cleanly.
- Tolerate server `error` messages and closed sockets without crashing.
- Use `client_token` and `match_id` in your handshake so the server can reject stray connections.

## Error handling
- Wrap network JSON parse/send in try/except; log and continue or exit cleanly.
- Clean up sockets with shutdown/close in `finally`.
- Avoid uncaught exceptions escaping threads; log them and end the match with a report.
- On bad client input, send `{ "type": "error", "message": "<reason>" }` and keep the game running.

## Communication pattern
- Transport: TCP, one JSON object per line (UTF-8).
- Handshake: first message must include `{room_id}`, `{match_id}`, `{player_name}`, `{client_token}`, and `{client_protocol_version}`. Example: `{"room_id":1,"match_id":"...","player_name":"Alice","client_token":"...","client_protocol_version":1}`.
- State updates: broadcast JSON lines (`tick`/`state`) to all players.
- Commands: accept simple JSON commands from clients (`cmd`, `play`, `surrender`, etc.) and validate per-room token/identity.

## Checklist for a new game
- [ ] `manifest.json` filled with correct commands/placeholders and working dirs.
- [ ] Server accepts handshake with `client_token` + `match_id` and rejects mismatches.
- [ ] Server reports `STARTED`, `HEARTBEAT`, `END`, and `ERROR` to `{report_host}:{report_port}` with `report_token` and `match_id`.
- [ ] Client quits gracefully (sends surrender/quit) on Ctrl-C.
- [ ] No external paths; all assets bundled under the game folder.
- [ ] Uses newline-delimited JSON; tolerant of disconnects and malformed input.
- [ ] Sends a final `END`/`ERROR` report on any termination path (win, surrender, disconnect, KeyboardInterrupt).
- [ ] README/inline comments explain any game-specific commands beyond the common ones.

## Practical integration guidelines (lessons learned)
- Don’t hard-allowlist guesses/input unless you ship the full list in `assets/`; prefer length/shape validation so remote deployments don’t reject valid input (Wordle: accept any alphabetic word of correct length).
- Ensure surrender/quit paths actually terminate the server loop and exit the process so the lobby can reset room state (BigTwo: return out of the loop on surrender).
- On game start, broadcast a short “rules” message to all players so they know win conditions and controls without guessing.
- Always include assets in the uploaded package (e.g., dictionaries, sprites) and reference them via `assets` globs; never rely on host-specific absolute paths.
- Keep network tolerance high: handle disconnects gracefully, send clear errors, and continue the match when possible.

Use `developer/games/Tetris` or `developer/games/BigTwo` as concrete examples.***
