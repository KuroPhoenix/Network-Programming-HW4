# ConnectFour

Two-player Connect Four built with Pygame. Runs under the platform game launcher with JSON-over-TCP networking, lobby lifecycle reporting, and a GUI client.

## How it works
- Server accepts exactly two players (p1/p2 from the room) after a handshake with `{room_id, match_id, player_name, client_token}`.
- Gameplay is turn-based; moves are `{ "type": "move", "col": <int> }`.
- Server broadcasts `state` updates and finishes with `game_over`.
- On disconnect or surrender, the remaining player wins and the lobby is notified via `GAME.REPORT`.

## Local run (manual)
```bash
cd developer/games/ConnectFour
pip install -r requirements.txt
# Terminal 1
MATCH_ID=demo123 CLIENT_TOKEN=secret REPORT_TOKEN=reportsecret \
python3 server.py --port 9000 --room 1 --p1 alice --p2 bob --report_host 127.0.0.1 --report_port 16534
# Terminal 2
ROOM_ID=1 MATCH_ID=demo123 CLIENT_TOKEN=secret \
python3 client.py --host 127.0.0.1 --port 9000 --player alice
# Terminal 3
ROOM_ID=1 MATCH_ID=demo123 CLIENT_TOKEN=secret \
python3 client.py --host 127.0.0.1 --port 9000 --player bob
```

## Controls
- Click a column to drop your piece on your turn.
- Close the window to surrender.

## Files
- `manifest.json`: platform launch config (server/client commands, placeholders).
- `server.py`: room-bound game server with report callbacks.
- `client.py`: Pygame GUI client.
- `board.py`: core game logic.
- `requirements.txt`: pygame + numpy.
