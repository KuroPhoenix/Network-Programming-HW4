# Game integration guide

This folder holds store-ready games that can be uploaded and run by the platform. Follow these rules so a new game fits the project without extra glue.

## Directory layout
- Each game lives in `developer/games/<GameName>/`.
- Must contain `manifest.json` describing how to launch server/client.
- Include all code/assets needed to run; do not reach outside the game folder at runtime.

## Manifest requirements
See `developer/template/manifest_template.json` for shape. Required fields:
- `game_name`, `version`, `type` (`CLI|GUI|2P|Multi`), `description`, `max_players`.
- `server.command` and `client.command`: use placeholders `{host}`, `{port}`, `{room_id}`, `{token}`, `{player_name}`, `{p1}`, `{p2}`, `{report_host}`, `{report_port}`, `{report_token}`. GameLauncher fills these.
- `server.working_dir` / `client.working_dir`: relative to the game root.
- `assets` list and optional `healthcheck`.
- Optional `env` maps for server/client are allowed; values can also use placeholders.
The server stores the manifest with each uploaded version; keep it accurate.

### Example command placeholders
- Server: `python server/main.py --port {port} --room {room_id} --token {token} --p1 {p1} --p2 {p2} --report_host {report_host} --report_port {report_port} --report_token {report_token}`
- Client: `python client/main.py --host {host} --port {port} --player {player_name} --token {token}`

## Server runtime contract
- Your game server is launched by GameLauncher with args and env from the manifest. It must:
  - Listen on the provided `{port}` and trust `{token}` for auth/room binding.
  - Accept at least two players; if more players are needed, use the placeholders (`{p1}`, `{p2}` etc.) or the hello payload to map connections.
  - Speak newline-delimited JSON; see helper `send_json`/`recv_json` in existing games.
  - Report lifecycle to the lobby: POST a `GAME.REPORT` message (JSON line) to `{report_host}:{report_port}` with fields `{"type":"GAME.REPORT","status":"RUNNING|END|ERROR","room_id":..., "report_token":...}` plus winner/loser/err_msg/reason as appropriate. See `developer/games/Tetris/server.py` for a reference.
  - On graceful shutdown or KeyboardInterrupt, send an `ERROR` report so the lobby can free the room.
  - Handle disconnects: if a player drops, pick a winner/loser and report with reason `disconnect`.
  - Clean up: close sockets, stop threads, and exit without hanging the parent server.

## Client runtime contract
- The platform launches your client with `{host}`, `{port}`, `{token}`, and `{player_name}`.
- On Ctrl-C or user quit, send a quit/surrender message to the game server before exiting so the server can finish cleanly.
- Tolerate server `error` messages and closed sockets without crashing.
- Use the token in your hello so the server can reject stray connections.

## Error handling
- Wrap network JSON parse/send in try/except; log and continue or exit cleanly.
- Clean up sockets with shutdown/close in `finally`.
- Avoid uncaught exceptions escaping threads; log them and end the match with a report.
- On bad client input, send `{ "type": "error", "message": "<reason>" }` and keep the game running.

## Communication pattern
- Transport: TCP, one JSON object per line (UTF-8).
- Handshake: send a hello line that includes `{token}` and the player name so the server can validate and place the connection. Example: `{"type":"hello","player":"Alice","role":"player","token":"<token>"}`.
- State updates: broadcast JSON lines (`tick`/`state`) to all players.
- Commands: accept simple JSON commands from clients (`cmd`, `play`, `surrender`, etc.) and validate per-room token/identity.

## Checklist for a new game
- [ ] `manifest.json` filled with correct commands/placeholders and working dirs.
- [ ] Server accepts hello with token and rejects mismatches.
- [ ] Server reports `RUNNING`, `END`, and `ERROR` to `{report_host}:{report_port}` with `report_token`.
- [ ] Client quits gracefully (sends surrender/quit) on Ctrl-C.
- [ ] No external paths; all assets bundled under the game folder.
- [ ] Uses newline-delimited JSON; tolerant of disconnects and malformed input.
- [ ] Sends a final `END`/`ERROR` report on any termination path (win, surrender, disconnect, KeyboardInterrupt).
- [ ] README/inline comments explain any game-specific commands beyond the common ones.

Use `developer/games/Tetris` or `developer/games/BigTwo` as concrete examples.***
