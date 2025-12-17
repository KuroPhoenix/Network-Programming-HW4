# Rock-Paper-Scissors (CLI)

Up to three players can join. First valid round decides the winner (ties break deterministically). Surrender forfeits.

## How to run locally
```bash
# Terminal 1 (server)
MATCH_ID=demo123 CLIENT_TOKEN=secret REPORT_TOKEN=reportsecret \
python3 server.py --port 9001 --room 1 --p1 Alice --p2 Bob --report_host 127.0.0.1 --report_port 16534

# Terminal 2 (Alice)
ROOM_ID=1 MATCH_ID=demo123 CLIENT_TOKEN=secret \
python3 client.py --host 127.0.0.1 --port 9001 --player Alice

# Terminal 3 (Bob)
ROOM_ID=1 MATCH_ID=demo123 CLIENT_TOKEN=secret \
python3 client.py --host 127.0.0.1 --port 9001 --player Bob
```

## Protocol
- Transport: TCP, newline-delimited JSON.
- Handshake: `{"room_id":1,"match_id":"...","player_name":"Alice","client_token":"...","client_protocol_version":1}`.
- Player commands:
  - `{"type":"move","move":"rock|paper|scissors"}` (lowercase)
  - `{"type":"surrender"}` to forfeit
- Server messages:
- handshake response includes `ok: true`
  - `rules`: textual rules on game start
  - `state`: shows your move (or pending) and whether the opponent submitted
  - `error`: validation errors
  - `game_over`: winner/loser/reason

## Manifest
See `manifest.json`. Commands are:
- Server: `python3 server.py --port {port} --room {room_id} --p1 {p1} --p2 {p2} --report_host {report_host} --report_port {report_port}`
- Client: `python3 client.py --host {host} --port {port} --player {player_name}`

No assets are required for this game. The manifest includes an empty `assets` list and a basic TCP healthcheck.
