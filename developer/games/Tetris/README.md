# Tetris — Python rewrite

This folder contains a self-contained head-to-head Tetris in Python. It honors the platform placeholders (`{host}`, `{port}`, `{room_id}`, `{token}`, `{p1}`, `{p2}`, `{player_name}`) defined in the manifest, so the lobby can launch it directly.

## How it works
- `server.py`: room-local server. Args: `--port --room --token --p1 --p2 [--tick_ms 500]`. Waits for the two named players with the token, then runs a synchronous Tetris loop (10x20 board, 7-bag pieces). It processes player commands (left/right/rotate/down/drop), applies gravity each tick, clears lines, tracks score/lines, and declares a winner when both are dead or one tops out.
- `client.py`: text UI. Args: `--host --port --player --token`. Shows your board in ASCII and sends commands. Controls: `a` left, `d` right, `w` rotate, `s` soft drop, `space`/`drop` hard drop, `q` quit.
- Protocol: newline-delimited JSON. Client sends `cmd` messages; server sends `tick` updates and `game_over`.

## Running manually
```bash
# Terminal 1 (server)
python3 server.py --port 9001 --room R2 --token SECRET --p1 Alice --p2 Bob

# Terminal 2 (Alice)
python3 client.py --host 127.0.0.1 --port 9001 --player Alice --token SECRET

# Terminal 3 (Bob)
python3 client.py --host 127.0.0.1 --port 9001 --player Bob --token SECRET
```

## Integration notes
- Manifest already points to these scripts with platform placeholders.
- No external dependencies beyond Python 3 stdlib.
- Keep this folder self-contained; all paths in manifest are relative.
