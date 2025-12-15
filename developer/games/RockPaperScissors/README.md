# Rock-Paper-Scissors (CLI)

Two-player Rock-Paper-Scissors launched via the lobby. First valid round decides the winner (tie breaks to player 1). Surrender forfeits.

## How to run locally
```bash
# Terminal 1 (server)
python3 server.py --port 9001 --room R1 --token SECRET --p1 Alice --p2 Bob

# Terminal 2 (Alice)
python3 client.py --host 127.0.0.1 --port 9001 --player Alice --token SECRET

# Terminal 3 (Bob)
python3 client.py --host 127.0.0.1 --port 9001 --player Bob --token SECRET
```

## Protocol
- Transport: TCP, newline-delimited JSON.
- Handshake: `{"type":"hello","player":"Alice","token":"<token>","role":"player"}`.
- Player commands:
  - `{"type":"move","move":"rock|paper|scissors"}` (lowercase)
  - `{"type":"surrender"}` to forfeit
- Server messages:
  - `ok`: handshake ack
  - `rules`: textual rules on game start
  - `state`: shows your move (or pending) and whether the opponent submitted
  - `error`: validation errors
  - `game_over`: winner/loser/reason

## Manifest
See `manifest.json`. Commands are:
- Server: `python3 server.py --port {port} --room {room_id} --token {token} --p1 {p1} --p2 {p2} --report_host {report_host} --report_port {report_port} --report_token {report_token}`
- Client: `python3 client.py --host {host} --port {port} --player {player_name} --token {token}`

No assets are required for this game. The manifest includes an empty `assets` list and a basic TCP healthcheck.
