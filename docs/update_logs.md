# Update Logs

## Phase 0 - Immediate stability fixes
- Added startup/cleanup metadata and match-scoped stopping in `server/core/room_genie.py`.
- Added diagnostic TCP healthcheck, extended launch context, and process-group stop in `server/core/game_launcher.py`.
- Introduced env-configurable bind host and protocol version in `server/core/config.py`.
- Hardened NDJSON parsing with size/rate limits and sustained-abuse disconnect in `server/util/net.py`.
- Updated lobby room reads to use snapshots in `server/core/handlers/lobby_handler.py`.

## Phase 1 - Control-plane protocol hardening
- Enforced STARTED/HEARTBEAT/END/ERROR handling and match_id/report_token validation in `server/core/handlers/game_handler.py`.
- Added STARTED-driven readiness and heartbeat timeouts in `server/core/room_genie.py`.
- Updated user launch flow to wait for IN_GAME and pass room_id to clients in `user/api/user_api.py` and `user/user_cli.py`.

## Phase 2 - Universal manifest context + game updates
- Expanded launch context (players_json/path, player_count, bind_host, protocol version) in `server/core/game_launcher.py`.
- Updated game servers/clients to handshake v1 and token env/file transport:
  - `server/cloudGames/Wordle/1.0.0/server.py`
  - `server/cloudGames/Wordle/1.0.0/client.py`
  - `server/cloudGames/BigTwo/1.0.0/server.py`
  - `server/cloudGames/BigTwo/1.0.0/client.py`
  - `developer/games/ConnectFour/server.py`
  - `developer/games/ConnectFour/client.py`
  - `developer/games/RockPaperScissors/server.py`
  - `developer/games/RockPaperScissors/client.py`
  - `developer/games/Tetris/server.py`
  - `developer/games/Tetris/client.py`
- Updated manifests to remove token args and add match_id/client_token/report_token + bind_host:
  - `server/cloudGames/Wordle/1.0.0/manifest.json`
  - `server/cloudGames/BigTwo/1.0.0/manifest.json`
  - `developer/games/Wordle/manifest.json`
  - `developer/games/BigTwo/manifest.json`
  - `developer/games/ConnectFour/manifest.json`
  - `developer/games/RockPaperScissors/manifest.json`
  - `developer/games/Tetris/manifest.json`
- Synced updated game packages into local downloads:
  - `user/downloads/*/Wordle/1.0.0/*`
  - `user/downloads/*/BigTwo/1.0.0/*`
  - `user/downloads/*/Tetris/1.0.0/*`
- Updated game READMEs to the new protocol and placeholders:
  - `developer/games/README.md`
  - `developer/games/Wordle/README.md`
  - `developer/games/BigTwo/README.md`
  - `developer/games/Tetris/README.md`
  - `developer/games/RockPaperScissors/README.md`
  - `developer/games/ConnectFour/README.md`
  - `server/cloudGames/Wordle/1.0.0/README.md`
  - `server/cloudGames/BigTwo/1.0.0/README.md`
  - `user/downloads/*/*/README.md`

## Phase 3 - Conformance tooling
- Added `tools/validate_game_package.py` for manifest validation with optional smoke test.
