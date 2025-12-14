# Wordle Duel

Two players race to solve the same 5-letter Wordle. First to guess the target wins; if both run out of attempts, the best board (most greens, then yellows, then fewer guesses) wins. Spectators can watch progress.

## How to run locally
```bash
# Terminal 1 (server)
python3 server.py --port 9000 --room R1 --token SECRET --p1 Alice --p2 Bob

# Terminal 2 (Alice)
python3 client.py --host 127.0.0.1 --port 9000 --player Alice --token SECRET

# Terminal 3 (Bob)
python3 client.py --host 127.0.0.1 --port 9000 --player Bob --token SECRET

# Optional spectator
python3 client.py --host 127.0.0.1 --port 9000 --player Carol --token SECRET --spectator
```

## Protocol
- Transport: TCP, newline-delimited JSON.
- Handshake (all roles): `{"type":"hello","player":"Alice","token":"<token>","role":"player|spectator"}`.
- Player commands:
  - `{"type":"guess","word":"apple"}` (must be 5 letters and in the allowed list).
  - `{"type":"surrender"}` (or Ctrl+C, which sends surrender).
- Server messages:
  - `ok`: acknowledges handshake.
  - `state`: progress update. For players it includes your board, attempts left, and opponent summary; for spectators it lists player progress counts.
  - `error`: validation errors (bad word, unknown command, etc.).
  - `game_over`: winner/loser/reason.

## Integration notes
- Manifest commands include placeholders `{host}`, `{port}`, `{room_id}`, `{token}`, `{p1}`, `{p2}`, `{player_name}`, `{report_host}`, `{report_port}`, `{report_token}`.
- Server reports RUNNING heartbeats plus END/ERROR to `{report_host}:{report_port}` with `report_token`.
- If a player disconnects or surrenders, the other wins (`reason: disconnect|surrender`).
- On both players exhausting attempts without solving, the server picks a winner by board quality (greens > yellows > fewer guesses) for deterministic outcomes.
