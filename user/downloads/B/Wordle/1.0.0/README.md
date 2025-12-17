# Wordle Duel

Two players race to solve the same 5-letter Wordle. First to guess the target wins; if both run out of attempts, the best board (most greens, then yellows, then fewer guesses) wins. Spectators can watch progress.

## How to run locally
```bash
# Terminal 1 (server)
MATCH_ID=demo123 CLIENT_TOKEN=secret REPORT_TOKEN=reportsecret \
python3 server.py --port 9000 --room 1 --p1 Alice --p2 Bob --report_host 127.0.0.1 --report_port 16534

# Terminal 2 (Alice)
ROOM_ID=1 MATCH_ID=demo123 CLIENT_TOKEN=secret \
python3 client.py --host 127.0.0.1 --port 9000 --player Alice

# Terminal 3 (Bob)
ROOM_ID=1 MATCH_ID=demo123 CLIENT_TOKEN=secret \
python3 client.py --host 127.0.0.1 --port 9000 --player Bob

# Optional spectator
ROOM_ID=1 MATCH_ID=demo123 CLIENT_TOKEN=secret \
python3 client.py --host 127.0.0.1 --port 9000 --player Carol --spectator
```

## Protocol
- Transport: TCP, newline-delimited JSON.
- Handshake (all roles): `{"room_id":1,"match_id":"...","player_name":"Alice","client_token":"...","client_protocol_version":1,"role":"player|spectator"}`.
- Player commands:
  - `{"type":"guess","word":"apple"}` (must be 5 letters and in the allowed list).
  - `{"type":"surrender"}` (or Ctrl+C, which sends surrender).
- Server messages:
- `ok` field in handshake response acknowledges connection.
  - `state`: progress update. For players it includes your board, attempts left, and opponent summary; for spectators it lists player progress counts.
- `error`: validation errors (bad word, unknown command, etc.).
- `game_over`: winner/loser/reason.

## Word list
- The server tries to load a larger 5-letter dictionary from `assets/words.txt` (one word per line). If absent, it falls back to system dictionaries (`/usr/share/dict/...`) and finally the bundled default list. All loaded words become both target choices and allowed guesses.

## Integration notes
- Manifest commands include placeholders `{host}`, `{port}`, `{room_id}`, `{match_id}`, `{client_token}`, `{report_token}`, `{p1}`, `{p2}`, `{player_name}`, `{report_host}`, `{report_port}` (tokens are passed via env or token files).
- Server reports STARTED/HEARTBEAT plus END/ERROR to `{report_host}:{report_port}` with `report_token` and `match_id`.
- If a player disconnects or surrenders, the other wins (`reason: disconnect|surrender`).
- On both players exhausting attempts without solving, the server picks a winner by board quality (greens > yellows > fewer guesses) for deterministic outcomes.
