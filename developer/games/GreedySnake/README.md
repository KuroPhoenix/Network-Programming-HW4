# GreedySnake (retro fire arena)

GreedySnake is a multi-player snake arena game with a 30-second time limit. Players compete to collect gold coins and can breathe fire to eliminate opponents. The last surviving snake wins, or, if time expires, the snake with the most coins wins.

## Controls
- Move: arrow keys or WASD.
- Breathe fire: spacebar.
- Quit (surrender): Esc.

## Rules
- Snakes spawn in a maze with fixed walls and randomized coins.
- Each coin increases your score and grows your snake.
- Fire travels in a straight line; any snake hit by fire is eliminated.
- Colliding with walls or any snake body results in death.
- The match ends when only one snake remains or time reaches 30 seconds.

## Protocol integration
This game follows the platform protocol v1 described in `developer/games/README.md`:
- Client handshake v1 with `client_token` + `match_id`.
- Server reports `STARTED`, periodic `HEARTBEAT`, and `END` with `results`.
- Logs are written under `logs/` (see `game_greedysnake_server.log` and `game_greedysnake_client.log`).

## Notes
- The server supports up to 4 players via `p1..p4`, and can also load the full player list from `PLAYERS_JSON_PATH` if provided.
- Fire has a short cooldown; use it strategically to eliminate opponents.
