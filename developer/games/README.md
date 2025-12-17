# Game integration guide (protocol v1)

This document defines the exact structure and protocol that every game must implement to run on this platform. The platform is a universal orchestrator: it launches a game server, launches local clients, and expects lifecycle reports back from the server. Your gameplay protocol can be anything, but the control-plane and handshake rules below are mandatory so the orchestrator can be deterministic and robust.

If you follow this guide, your game will behave consistently across multi-client runs, network jitter, and restarts. If you diverge from it, you will reintroduce the same flakiness that the platform has already been hardened to avoid.

## What the platform guarantees (and what it expects)

When a room host starts a match, the platform generates a new `match_id` and two secrets: `client_token` and `report_token`. These are created before the game server process is spawned so there is no race when the server reports `STARTED`. The platform then launches the server in a `STARTING` state, waits for readiness, and only then flips the room to `IN_GAME` and launches clients. This matters because the client launch is strictly gated: clients must not connect until the platform marks the room `IN_GAME`.

Your server must therefore send `STARTED` only when it is actually ready to accept the handshake and process game messages. The platform treats `STARTED` as the sole readiness signal. A port bind alone is not enough.

## Directory layout and packaging

Put each game under `developer/games/<GameName>/` with a `manifest.json` at the root. Keep all code and assets inside that folder. Paths in the manifest must be relative so the platform can package and deploy the game cleanly.

Example layout:
```text
developer/games/MyGame/
  manifest.json
  server.py
  client.py
  assets/
    board.png
```

## Manifest v1 (required fields and meaning)

The manifest is how the platform knows how to launch your game. It is not just a list of commands: it is a contract that defines which placeholders the platform can safely inject.

A complete example (this is a real template you can start from):
```json
{
  "game_name": "MyGame",
  "version": "1.0.0",
  "type": "CLI",
  "description": "Two-player demo game.",
  "max_players": 2,
  "server": {
    "command": "python3 server.py --port {port} --room {room_id} --p1 {p1} --p2 {p2} --report_host {report_host} --report_port {report_port}",
    "working_dir": ".",
    "env": {
      "ROOM_ID": "{room_id}",
      "PORT": "{port}",
      "MATCH_ID": "{match_id}",
      "CLIENT_TOKEN": "{client_token}",
      "REPORT_TOKEN": "{report_token}",
      "CLIENT_TOKEN_PATH": "{client_token_path}",
      "REPORT_TOKEN_PATH": "{report_token_path}",
      "BIND_HOST": "{bind_host}"
    }
  },
  "client": {
    "command": "python3 client.py --host {host} --port {port} --player {player_name}",
    "working_dir": ".",
    "env": {
      "ROOM_ID": "{room_id}",
      "MATCH_ID": "{match_id}",
      "CLIENT_TOKEN": "{client_token}",
      "CLIENT_TOKEN_PATH": "{client_token_path}",
      "CLIENT_PROTOCOL_VERSION": "1"
    }
  },
  "healthcheck": {
    "tcp_port": "{port}",
    "timeout_sec": 5
  }
}
```

Important details in practice:
- `bind_host` is where the server must bind (default `0.0.0.0`). This is different from `host`, which is the advertised address clients connect to.
- Tokens are secrets. They must be passed via env or token files, never as CLI args.
- `healthcheck` exists for diagnostics only. Readiness is driven by `STARTED`.

## Placeholder rules (what the platform injects)

Placeholders are substituted at launch time. Only the placeholders listed below are supported. If you add custom placeholders, they will not be expanded.

The most commonly used placeholders are:
- `{host}` for the address clients should connect to.
- `{bind_host}` for the interface the server should bind to.
- `{port}` for the game server port.
- `{room_id}` and `{match_id}` for identity and correlation.
- `{player_name}`, `{p1}`, `{p2}`, `{p3}` for player display names.
- `{players_json}` / `{players_csv}` and `{players_json_path}` for full player lists.

Example of reading the JSON player list inside your server:
```python
import json
import os
from pathlib import Path

players = []
players_path = os.getenv("PLAYERS_JSON_PATH") or os.getenv("players_json_path")
if players_path:
    players = json.loads(Path(players_path).read_text(encoding="utf-8"))
```

## Tokens and identity (client_token, report_token, match_id)

The platform issues two secrets per match:
- `client_token` authorizes a player client to join the game server.
- `report_token` authorizes the game server to report to the platform.

`match_id` is not secret; it is a correlation ID that ties all reports and logs to one specific match. You should log the `match_id` freely, but never log the full tokens.

Recommended token access pattern (env or file):
```python
from pathlib import Path
import os

def read_secret(env_name: str, path_env_name: str) -> str:
    val = os.getenv(env_name)
    if val:
        return val
    path = os.getenv(path_env_name)
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return ""
```

## Client handshake v1 (mandatory)

The handshake is the first message sent by the client after connecting. The server must validate it before accepting any game messages. This is what makes `STARTED` testable and deterministic.

Example handshake (client to server):
```json
{"room_id":1,"match_id":"6f3e...","player_name":"Alice","client_token":"...","client_protocol_version":1}
```

Example response (server to client):
```json
{"ok":true,"assigned_player_index":0,"game_protocol_version":1}
```

If the handshake is invalid, respond with a clear failure so the client can surface a helpful error:
```json
{"ok":false,"reason":"invalid client token"}
```

## Control-plane reporting (server -> platform)

The game server must report lifecycle status to the platform over a TCP connection to `{report_host}:{report_port}` using newline-delimited JSON.

Required statuses:
- `STARTED`: the server is bound, initialized, and ready to accept the handshake.
- `HEARTBEAT`: sent every few seconds while the match is running.
- `END`: normal termination with `results` payload.
- `ERROR`: fatal error with an error message.

Example `STARTED` payload:
```json
{"type":"GAME.REPORT","status":"STARTED","room_id":1,"match_id":"6f3e...","report_token":"...","timestamp":1690000000.0,"port":9000}
```

Example `END` payload with results:
```json
{
  "type":"GAME.REPORT",
  "status":"END",
  "room_id":1,
  "match_id":"6f3e...",
  "report_token":"...",
  "timestamp":1690000500.0,
  "results":[
    {"player":"Alice","outcome":"WIN","rank":1,"score":12},
    {"player":"Bob","outcome":"LOSE","rank":2,"score":8}
  ]
}
```

The platform rejects any report whose `report_token` or `match_id` does not match the current match in that room. This prevents stale reports from old processes from corrupting new matches.

## Results schema (mandatory)

The `results` list must be included in `END` messages so multi-player games are supported consistently. Use this minimal shape:

```json
{"results":[{"player":"Alice","outcome":"WIN","rank":1,"score":12}]}
```

Rules:
- `player` must match exactly one entry in the room's player list.
- `outcome` must be one of `WIN`, `LOSE`, `DRAW`, `QUIT`, `ERROR`.
- `rank` and `score` may be `null` when not applicable.

For a 4-player game, you can do:
```json
{"results":[
  {"player":"A","outcome":"WIN","rank":1,"score":42},
  {"player":"B","outcome":"LOSE","rank":2,"score":30},
  {"player":"C","outcome":"LOSE","rank":3,"score":15},
  {"player":"D","outcome":"QUIT","rank":null,"score":null}
]}
```

## Logging requirement (logs/ directory)

All game logs must be written under the repo's `logs/` directory so a single demo run has a complete record. This includes both server and client logs.

A robust way to ensure this is to locate the repository root by searching for `requirements.txt`, then emit logs into `logs/` from there. Example setup code:

```python
import logging
from pathlib import Path

def configure_logging(log_name: str) -> None:
    root = None
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / "requirements.txt").is_file():
            root = parent
            break
    if root is None:
        root = here.parent
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / log_name
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
```

Use a stable log name such as `game_mygame_server.log` or `game_mygame_client.log`.

## Error handling and network resilience

Your server and clients must treat the network as unreliable. Use try/except around `sendall`, around recv loops, and around JSON decoding so a single bad packet does not crash the process. When you discard a malformed message, log the event and continue. This is critical for keeping the platform stable during demos.

A minimal pattern:
```python
def recv_json(conn):
    buf = b""
    try:
        while True:
            chunk = conn.recv(1)
            if not chunk:
                return None
            if chunk == b"\n":
                break
            buf += chunk
    except Exception as exc:
        logger.warning("recv_json failed: %s", exc)
        return None
    try:
        return json.loads(buf.decode("utf-8"))
    except Exception as exc:
        logger.warning("recv_json parse failed: %s", exc)
        return None
```

## Readiness and lifecycle rules

The server must send `STARTED` only after it is fully ready: socket bound, state initialized, authentication checks ready, and handshake handler active. The platform will then set the room to `IN_GAME` and launch clients. Clients should never attempt to connect earlier; the platform enforces this to prevent half-ready launches.

Heartbeats should be sent every 2-5 seconds. If heartbeats stop for too long, the platform will terminate the match and reset the room. This is by design: it makes failures predictable instead of silent.

## Integration steps (end-to-end)

1) Create the folder and manifest as shown above. The manifest is the platform's source of truth for how to launch your game.

2) Implement the server handshake v1, and verify the `client_token` and `match_id` before accepting a player. If you accept a client without validating tokens, you reintroduce spoofing and stale-match bugs.

3) Implement control-plane reporting. At minimum, send `STARTED`, periodic `HEARTBEAT`, and `END` with a valid results list. Report `ERROR` on fatal exceptions.

4) Add robust logging and error handling so your process can survive malformed input. Ensure logs land in `logs/`.

5) Validate the package:
```
python tools/validate_game_package.py developer/games/<GameName>
```

6) Optional smoke test:
```
python tools/validate_game_package.py --smoke developer/games/<GameName>
```

## Common mistakes and how to avoid them

- Sending `STARTED` before the handshake is ready. This causes clients to connect too early and fail.
- Passing tokens via CLI args. They will leak into process listings and logs.
- Omitting `results` in `END`. This breaks multi-player consistency.
- Logging secrets. Always redact tokens.

If you align your game to this guide, it will integrate cleanly and predictably with the platform and will behave consistently across demos.
