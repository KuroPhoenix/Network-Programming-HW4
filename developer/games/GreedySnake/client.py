import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import pygame


def _configure_logging(log_name: str) -> None:
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
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_dir / log_name, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )


_configure_logging("game_greedysnake_client.log")
logger = logging.getLogger(__name__)

TILE = 20
HUD_HEIGHT = 120
BACKGROUND = (10, 10, 12)
WALL = (40, 40, 40)
COIN = (242, 196, 76)
FIRE = (255, 80, 60)
TEXT = (220, 220, 220)

PALETTE = [
    (76, 201, 240),
    (247, 37, 133),
    (255, 202, 58),
    (138, 201, 38),
    (255, 125, 0),
    (114, 9, 183),
]


def send_json(conn: socket.socket, obj: dict) -> bool:
    try:
        conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")
        return True
    except Exception as exc:
        logger.warning("send_json failed: %s", exc)
        return False


def recv_json(conn: socket.socket) -> Optional[dict]:
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


def _read_secret(env_name: str, path_env_name: str) -> str:
    val = os.getenv(env_name)
    if val:
        return val
    path = os.getenv(path_env_name)
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


class ClientState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.grid = {"w": 32, "h": 24}
        self.walls = []
        self.players = []
        self.time_limit = 30
        self.state: Dict = {}
        self.status = "WAITING"
        self.you = ""
        self.game_over: Optional[Dict] = None
        self.connected = True

    def update_config(self, payload: dict) -> None:
        with self.lock:
            self.grid = payload.get("grid", self.grid)
            self.walls = payload.get("walls", self.walls)
            self.players = payload.get("players", self.players)
            self.time_limit = payload.get("time_limit", self.time_limit)

    def update_state(self, payload: dict) -> None:
        with self.lock:
            self.state = payload
            self.status = payload.get("status", self.status)
            self.you = payload.get("you", self.you)

    def set_game_over(self, payload: dict) -> None:
        with self.lock:
            self.game_over = payload


class NetworkThread(threading.Thread):
    def __init__(self, conn: socket.socket, state: ClientState):
        super().__init__(daemon=True)
        self.conn = conn
        self.state = state

    def run(self) -> None:
        while True:
            msg = recv_json(self.conn)
            if not msg:
                self.state.connected = False
                return
            mtype = msg.get("type")
            if mtype == "config":
                self.state.update_config(msg)
            elif mtype == "state":
                self.state.update_state(msg)
            elif mtype == "game_over":
                self.state.set_game_over(msg)


def draw_grid(screen, state: ClientState, font, small_font) -> None:
    with state.lock:
        grid = state.grid
        walls = state.walls
        payload = state.state
        status = state.status
        you = state.you
        game_over = state.game_over

    w, h = grid.get("w", 32), grid.get("h", 24)
    screen.fill(BACKGROUND)

    for x, y in walls:
        pygame.draw.rect(screen, WALL, (x * TILE, y * TILE, TILE, TILE))

    for x, y in payload.get("coins", []):
        pygame.draw.rect(screen, COIN, (x * TILE + 6, y * TILE + 6, TILE - 12, TILE - 12))

    for fire in payload.get("fires", []):
        fx, fy = fire.get("x"), fire.get("y")
        pygame.draw.rect(screen, FIRE, (fx * TILE + 4, fy * TILE + 4, TILE - 8, TILE - 8))

    players = payload.get("snakes", [])
    for idx, snake in enumerate(players):
        name = snake.get("name")
        color = PALETTE[idx % len(PALETTE)]
        body = snake.get("body", [])
        alive = snake.get("alive", True)
        shade = color if alive else tuple(max(30, c // 3) for c in color)
        for i, (x, y) in enumerate(body):
            rect = (x * TILE + 2, y * TILE + 2, TILE - 4, TILE - 4)
            if i == 0:
                pygame.draw.rect(screen, shade, rect)
                pygame.draw.rect(screen, (255, 255, 255), rect, 1)
            else:
                pygame.draw.rect(screen, shade, rect)

    hud_top = h * TILE
    pygame.draw.rect(screen, (18, 18, 24), (0, hud_top, w * TILE, HUD_HEIGHT))
    title = font.render("GREEDY SNAKE", True, TEXT)
    screen.blit(title, (12, hud_top + 10))

    timer = payload.get("time_left", 0)
    timer_text = font.render(f"Time: {timer:0.1f}s", True, TEXT)
    screen.blit(timer_text, (w * TILE - 170, hud_top + 10))

    status_text = small_font.render(f"Status: {status}", True, TEXT)
    screen.blit(status_text, (12, hud_top + 40))

    if you:
        you_text = small_font.render(f"You: {you}", True, TEXT)
        screen.blit(you_text, (12, hud_top + 60))

    scores_x = 240
    for idx, snake in enumerate(players):
        name = snake.get("name")
        coins = snake.get("coins")
        alive = snake.get("alive", True)
        label = f"{name} | coins {coins} | {'alive' if alive else 'dead'}"
        score_text = small_font.render(label, True, PALETTE[idx % len(PALETTE)])
        screen.blit(score_text, (scores_x, hud_top + 40 + idx * 18))

    controls = small_font.render("Move: WASD/Arrows  Fire: Space  Quit: Esc", True, TEXT)
    screen.blit(controls, (12, hud_top + 90))

    if game_over:
        winners = ", ".join(game_over.get("winners", [])) or "None"
        over_text = font.render(f"WINNER: {winners}", True, COIN)
        screen.blit(over_text, (12, hud_top - 40))


def main() -> None:
    parser = argparse.ArgumentParser(description="GreedySnake client.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--room_id", type=int, default=int(os.getenv("ROOM_ID", "0") or 0))
    parser.add_argument("--match_id", default=os.getenv("MATCH_ID", ""))
    parser.add_argument("--client_token", default=os.getenv("CLIENT_TOKEN", ""))
    parser.add_argument("--client_protocol_version", type=int, default=int(os.getenv("CLIENT_PROTOCOL_VERSION", "1") or 1))
    args = parser.parse_args()

    client_token = args.client_token or _read_secret("CLIENT_TOKEN", "CLIENT_TOKEN_PATH")
    match_id = args.match_id or os.getenv("MATCH_ID", "")
    room_id = args.room_id or int(os.getenv("ROOM_ID", "0") or 0)
    if not client_token or not match_id or not room_id:
        print("Missing client_token/match_id/room_id; check environment or args.")
        sys.exit(2)

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        conn.connect((args.host, args.port))
    except Exception as exc:
        logger.error("failed to connect to %s:%s: %s", args.host, args.port, exc)
        return

    hello = {
        "room_id": room_id,
        "match_id": match_id,
        "player_name": args.player,
        "client_token": client_token,
        "client_protocol_version": args.client_protocol_version,
        "role": "player",
    }
    if not send_json(conn, hello):
        print("Failed to send handshake.")
        return
    resp = recv_json(conn)
    if not resp or not resp.get("ok"):
        print(f"Handshake rejected: {resp.get('reason') if resp else 'no response'}")
        return

    state = ClientState()
    net_thread = NetworkThread(conn, state)
    net_thread.start()

    pygame.init()
    grid_w, grid_h = state.grid.get("w", 32), state.grid.get("h", 24)
    screen = pygame.display.set_mode((grid_w * TILE, grid_h * TILE + HUD_HEIGHT))
    pygame.display.set_caption("GreedySnake")
    font = pygame.font.SysFont("Courier", 24, bold=True)
    small_font = pygame.font.SysFont("Courier", 16)

    clock = pygame.time.Clock()
    running = True
    while running:
        if not state.connected:
            break
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                send_json(conn, {"type": "surrender"})
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE,):
                    send_json(conn, {"type": "surrender"})
                    running = False
                elif event.key in (pygame.K_UP, pygame.K_w):
                    send_json(conn, {"type": "input", "dir": "UP"})
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    send_json(conn, {"type": "input", "dir": "DOWN"})
                elif event.key in (pygame.K_LEFT, pygame.K_a):
                    send_json(conn, {"type": "input", "dir": "LEFT"})
                elif event.key in (pygame.K_RIGHT, pygame.K_d):
                    send_json(conn, {"type": "input", "dir": "RIGHT"})
                elif event.key in (pygame.K_SPACE,):
                    send_json(conn, {"type": "fire"})

        draw_grid(screen, state, font, small_font)
        pygame.display.flip()
        clock.tick(30)

        with state.lock:
            if state.game_over:
                time.sleep(2.0)
                running = False

    pygame.quit()
    try:
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
