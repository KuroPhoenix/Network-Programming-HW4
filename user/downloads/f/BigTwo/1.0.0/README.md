# BigTwo — Python rewrite

This folder contains a self-contained Python implementation of BigTwo with full turn logic. It honors the platform placeholders (`{host}`, `{port}`, `{room_id}`, `{token}`, `{p1}`, `{p2}`, `{player_name}`) defined in the manifest, so the lobby can launch it directly.

## How it works
- `server.py`: room-local server. Args: `--port --room --token --p1 --p2`. Waits for the two named players with the token, deals 13 cards each, enforces BigTwo rules (lead must include 3C; plays of single/pair/5-card combos; must beat current combo unless leading; pass allowed after a lead), and ends when a player empties their hand.
- `client.py`: menu-driven CLI. Args: `--host --port --player --token`. Connects, handshakes, shows your hand and table state, prompts you to play card codes (`3C`, `10H`, `AS`, etc.) or pass when allowed.
- Protocol: newline-delimited JSON. Messages include `state`, `error`, `game_over`; client sends `play` or `pass`.

## Running manually
```bash
# Terminal 1 (server)
python3 server.py --port 9000 --room R1 --token SECRET --p1 Alice --p2 Bob

# Terminal 2 (Alice)
python3 client.py --host 127.0.0.1 --port 9000 --player Alice --token SECRET

# Terminal 3 (Bob)
python3 client.py --host 127.0.0.1 --port 9000 --player Bob --token SECRET
```

## Integration notes
- Manifest already points to these scripts with platform placeholders.
- No external dependencies beyond Python 3 stdlib.
- Keep this folder self-contained; all paths in manifest are relative.
