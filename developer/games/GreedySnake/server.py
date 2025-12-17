import argparse
import json
import logging
import os
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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


_configure_logging("game_greedysnake_server.log")
logger = logging.getLogger(__name__)

GRID_W = 32
GRID_H = 24
TICK_RATE = 10
TIME_LIMIT_SEC = 30
START_DELAY_SEC = 5.0
COIN_COUNT = 30
SNAKE_START_LEN = 3
FIRE_TTL = 8
FIRE_COOLDOWN = 1.0

DIRS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}


@dataclass
class Snake:
    name: str
    body: List[Tuple[int, int]]
    direction: Tuple[int, int]
    pending_dir: Tuple[int, int]
    alive: bool = True
    coins: int = 0
    last_fire: float = 0.0
    fire_request: bool = False
    quit_flag: bool = False


@dataclass
class Fire:
    owner: str
    x: int
    y: int
    direction: Tuple[int, int]
    ttl: int = FIRE_TTL


class GreedySnakeServer:
    def __init__(
        self,
        port: int,
        room_id: str,
        client_token: str,
        match_id: str,
        players: List[str],
        bind_host: str,
        report_host: Optional[str],
        report_port: Optional[int],
        report_token: str,
    ):
        self.port = port
        self.room_id = int(room_id)
        self.client_token = client_token
        self.match_id = match_id
        self.bind_host = bind_host
        self.report_host = report_host
        self.report_port = report_port
        self.report_token = report_token
        self.expected_players = [p for p in players if p]
        self.listener: Optional[socket.socket] = None
        self.connections: Dict[str, socket.socket] = {}
        self.spectators: Dict[str, socket.socket] = {}
        self.running = True
        self.lock = threading.Lock()
        self.rng = random.Random(match_id)
        self.walls = self._build_maze(GRID_W, GRID_H)
        self.snakes: Dict[str, Snake] = {}
        self.coins: set[Tuple[int, int]] = set()
        self.fires: List[Fire] = []
        self.match_started = False
        self.start_time: Optional[float] = None
        self.start_deadline = time.time() + START_DELAY_SEC
        self._spawn_snakes()
        self._seed_coins()

    def _build_maze(self, w: int, h: int) -> set[Tuple[int, int]]:
        walls = set()
        for x in range(w):
            walls.add((x, 0))
            walls.add((x, h - 1))
        for y in range(h):
            walls.add((0, y))
            walls.add((w - 1, y))
        for x in range(4, w - 4, 6):
            for y in range(2, h - 2):
                if y % 6 in (0, 1):
                    continue
                walls.add((x, y))
        for y in range(4, h - 4, 6):
            for x in range(2, w - 2):
                if x % 7 in (0, 1):
                    continue
                walls.add((x, y))
        return walls

    def _spawn_snakes(self) -> None:
        spawn_points = [
            (2, 2),
            (GRID_W - 3, 2),
            (2, GRID_H - 3),
            (GRID_W - 3, GRID_H - 3),
            (GRID_W // 2, 2),
            (GRID_W // 2, GRID_H - 3),
            (2, GRID_H // 2),
            (GRID_W - 3, GRID_H // 2),
        ]
        used = set()
        for idx, name in enumerate(self.expected_players):
            if idx < len(spawn_points):
                head = spawn_points[idx]
            else:
                head = self._find_open_cell(used)
            direction = self._direction_toward_center(head)
            body = self._build_body(head, direction)
            used.update(body)
            self.snakes[name] = Snake(name=name, body=body, direction=direction, pending_dir=direction)

    def _build_body(self, head: Tuple[int, int], direction: Tuple[int, int]) -> List[Tuple[int, int]]:
        dx, dy = direction
        body = [head]
        for i in range(1, SNAKE_START_LEN):
            body.append((head[0] - dx * i, head[1] - dy * i))
        for cell in body:
            if cell in self.walls:
                return [head]
        return body

    def _direction_toward_center(self, head: Tuple[int, int]) -> Tuple[int, int]:
        cx, cy = GRID_W // 2, GRID_H // 2
        dx = cx - head[0]
        dy = cy - head[1]
        if abs(dx) >= abs(dy):
            return (1, 0) if dx > 0 else (-1, 0)
        return (0, 1) if dy > 0 else (0, -1)

    def _find_open_cell(self, used: set[Tuple[int, int]]) -> Tuple[int, int]:
        for y in range(2, GRID_H - 2):
            for x in range(2, GRID_W - 2):
                if (x, y) not in self.walls and (x, y) not in used:
                    return (x, y)
        return (2, 2)

    def _seed_coins(self) -> None:
        attempts = 0
        while len(self.coins) < COIN_COUNT and attempts < COIN_COUNT * 20:
            attempts += 1
            x = self.rng.randint(1, GRID_W - 2)
            y = self.rng.randint(1, GRID_H - 2)
            pos = (x, y)
            if pos in self.walls:
                continue
            if pos in self.coins:
                continue
            if any(pos in snake.body for snake in self.snakes.values()):
                continue
            self.coins.add(pos)

    def _spawn_coin(self) -> None:
        for _ in range(50):
            x = self.rng.randint(1, GRID_W - 2)
            y = self.rng.randint(1, GRID_H - 2)
            pos = (x, y)
            if pos in self.walls or pos in self.coins:
                continue
            if any(pos in snake.body for snake in self.snakes.values()):
                continue
            self.coins.add(pos)
            return

    def _report_status(self, status: str, results: Optional[List[Dict]] = None, err_msg: Optional[str] = None, reason: Optional[str] = None):
        if not self.report_host or not self.report_port:
            return
        payload = {
            "type": "GAME.REPORT",
            "status": status,
            "game": "GreedySnake",
            "room_id": self.room_id,
            "match_id": self.match_id,
            "report_token": self.report_token,
            "timestamp": time.time(),
        }
        if status == "STARTED":
            payload["port"] = self.port
        if results is not None:
            payload["results"] = results
        if err_msg:
            payload["err_msg"] = err_msg
        if reason:
            payload["reason"] = reason
        try:
            with socket.create_connection((self.report_host, self.report_port), timeout=3) as conn:
                send_json(conn, payload)
        except Exception as exc:
            logger.warning("failed to report status: %s", exc)

    def _heartbeat(self) -> None:
        while self.running:
            self._report_status("HEARTBEAT", reason="heartbeat")
            time.sleep(2.0)

    def start(self) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((self.bind_host, self.port))
        self.listener.listen(8)
        self.listener.settimeout(0.5)
        logger.warning("GreedySnake listening on %s:%s room=%s", self.bind_host, self.port, self.room_id)
        self._report_status("STARTED")

        threading.Thread(target=self._heartbeat, daemon=True).start()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self._game_loop()

    def _accept_loop(self) -> None:
        while self.running:
            try:
                conn, addr = self.listener.accept()
            except socket.timeout:
                continue
            except Exception as exc:
                logger.warning("accept failed: %s", exc)
                continue
            threading.Thread(target=self._handshake_and_handle, args=(conn, addr), daemon=True).start()

    def _handshake_and_handle(self, conn: socket.socket, addr) -> None:
        try:
            hello = recv_json(conn)
            if not hello:
                return
            player_name = str(hello.get("player_name") or "")
            room_id = int(hello.get("room_id") or 0)
            match_id = str(hello.get("match_id") or "")
            token = str(hello.get("client_token") or "")
            role = str(hello.get("role") or "player")
            if token != self.client_token:
                send_json(conn, {"ok": False, "reason": "invalid client token"})
                return
            if match_id != self.match_id:
                send_json(conn, {"ok": False, "reason": "invalid match_id"})
                return
            if room_id != self.room_id:
                send_json(conn, {"ok": False, "reason": "invalid room_id"})
                return
            if role == "spectator":
                sid = f"spectator-{addr[0]}:{addr[1]}"
                with self.lock:
                    self.spectators[sid] = conn
                send_json(conn, {"ok": True, "game_protocol_version": 1})
                send_json(conn, self._config_payload())
                logger.warning("spectator connected from %s", addr)
                self._spectator_loop(conn, sid)
                return
            if not player_name:
                send_json(conn, {"ok": False, "reason": "player_name required"})
                return
            if player_name not in self.snakes:
                send_json(conn, {"ok": False, "reason": "unknown player"})
                return
            with self.lock:
                if player_name in self.connections:
                    send_json(conn, {"ok": False, "reason": "player already connected"})
                    return
                self.connections[player_name] = conn
            send_json(conn, {"ok": True, "assigned_player_index": self.expected_players.index(player_name), "game_protocol_version": 1})
            send_json(conn, self._config_payload())
            logger.warning("player %s connected from %s", player_name, addr)
            self._player_loop(conn, player_name)
        except Exception as exc:
            logger.warning("handshake failed: %s", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _spectator_loop(self, conn: socket.socket, sid: str) -> None:
        while self.running:
            msg = recv_json(conn)
            if not msg:
                break
        with self.lock:
            self.spectators.pop(sid, None)

    def _player_loop(self, conn: socket.socket, player_name: str) -> None:
        while self.running:
            msg = recv_json(conn)
            if not msg:
                break
            mtype = msg.get("type")
            if mtype == "input":
                direction = str(msg.get("dir") or "").upper()
                if direction in DIRS:
                    with self.lock:
                        snake = self.snakes.get(player_name)
                        if snake and snake.alive:
                            snake.pending_dir = DIRS[direction]
            elif mtype == "fire":
                with self.lock:
                    snake = self.snakes.get(player_name)
                    if snake and snake.alive:
                        snake.fire_request = True
            elif mtype == "surrender":
                with self.lock:
                    snake = self.snakes.get(player_name)
                    if snake and snake.alive:
                        snake.alive = False
                        snake.quit_flag = True
        with self.lock:
            self.connections.pop(player_name, None)
            snake = self.snakes.get(player_name)
            if snake and snake.alive:
                snake.alive = False
                snake.quit_flag = True

    def _config_payload(self) -> dict:
        return {
            "type": "config",
            "grid": {"w": GRID_W, "h": GRID_H},
            "walls": [[x, y] for (x, y) in sorted(self.walls)],
            "time_limit": TIME_LIMIT_SEC,
            "players": list(self.expected_players),
        }

    def _game_loop(self) -> None:
        tick = 1.0 / TICK_RATE
        try:
            while self.running:
                start_tick = time.time()
                with self.lock:
                    self._maybe_start_match()
                    if self.match_started:
                        self._advance_fires()
                        self._move_snakes()
                self._broadcast_state()
                if self._check_game_end():
                    break
                elapsed = time.time() - start_tick
                if elapsed < tick:
                    time.sleep(tick - elapsed)
        except Exception as exc:
            logger.exception("game loop failed: %s", exc)
            self._report_status("ERROR", err_msg=str(exc))
        finally:
            self.running = False
            self._close_all()

    def _maybe_start_match(self) -> None:
        if self.match_started:
            return
        connected = len(self.connections)
        if connected >= min(2, len(self.expected_players)) or time.time() >= self.start_deadline:
            self.match_started = True
            self.start_time = time.time()

    def _advance_fires(self) -> None:
        new_fires: List[Fire] = []
        for fire in self.fires:
            if fire.ttl <= 0:
                continue
            nx = fire.x + fire.direction[0]
            ny = fire.y + fire.direction[1]
            if (nx, ny) in self.walls:
                continue
            hit = self._snake_at(nx, ny)
            if hit and hit.alive:
                hit.alive = False
                continue
            fire.x = nx
            fire.y = ny
            fire.ttl -= 1
            new_fires.append(fire)
        self.fires = new_fires

    def _snake_at(self, x: int, y: int) -> Optional[Snake]:
        for snake in self.snakes.values():
            if not snake.alive:
                continue
            if (x, y) in snake.body:
                return snake
        return None

    def _move_snakes(self) -> None:
        proposed: Dict[str, Tuple[int, int]] = {}
        for name, snake in self.snakes.items():
            if not snake.alive:
                continue
            if self._is_reverse(snake.direction, snake.pending_dir):
                snake.pending_dir = snake.direction
            snake.direction = snake.pending_dir
            head_x, head_y = snake.body[0]
            dx, dy = snake.direction
            proposed[name] = (head_x + dx, head_y + dy)

        occupied = {pos for snake in self.snakes.values() if snake.alive for pos in snake.body}
        head_counts: Dict[Tuple[int, int], int] = {}
        for pos in proposed.values():
            head_counts[pos] = head_counts.get(pos, 0) + 1

        for name, pos in proposed.items():
            snake = self.snakes[name]
            if pos in self.walls or pos[0] <= 0 or pos[0] >= GRID_W - 1 or pos[1] <= 0 or pos[1] >= GRID_H - 1:
                snake.alive = False
                continue
            if head_counts.get(pos, 0) > 1:
                snake.alive = False
                continue
            if pos in occupied:
                tail = snake.body[-1]
                will_grow = pos in self.coins
                if not will_grow and pos == tail:
                    pass
                else:
                    snake.alive = False

        for name, pos in proposed.items():
            snake = self.snakes[name]
            if not snake.alive:
                continue
            if snake.fire_request:
                self._spawn_fire(snake)
                snake.fire_request = False
            snake.body.insert(0, pos)
            if pos in self.coins:
                snake.coins += 1
                self.coins.discard(pos)
                self._spawn_coin()
            else:
                snake.body.pop()

    def _spawn_fire(self, snake: Snake) -> None:
        now = time.time()
        if now - snake.last_fire < FIRE_COOLDOWN:
            return
        dx, dy = snake.direction
        hx, hy = snake.body[0]
        fx, fy = hx + dx, hy + dy
        if (fx, fy) in self.walls:
            return
        snake.last_fire = now
        self.fires.append(Fire(owner=snake.name, x=fx, y=fy, direction=(dx, dy)))

    def _is_reverse(self, current: Tuple[int, int], new: Tuple[int, int]) -> bool:
        return current[0] == -new[0] and current[1] == -new[1]

    def _broadcast_state(self) -> None:
        state = self._state_payload()
        for name, conn in list(self.connections.items()):
            payload = dict(state)
            payload["you"] = name
            send_json(conn, payload)
        for conn in list(self.spectators.values()):
            send_json(conn, state)

    def _state_payload(self) -> dict:
        if self.match_started and self.start_time:
            time_left = max(0.0, TIME_LIMIT_SEC - (time.time() - self.start_time))
        else:
            time_left = TIME_LIMIT_SEC
        snakes_data = []
        for name, snake in self.snakes.items():
            snakes_data.append(
                {
                    "name": name,
                    "body": [[x, y] for (x, y) in snake.body],
                    "alive": snake.alive,
                    "coins": snake.coins,
                }
            )
        fires = [{"x": f.x, "y": f.y, "dx": f.direction[0], "dy": f.direction[1]} for f in self.fires]
        return {
            "type": "state",
            "status": "RUNNING" if self.match_started else "WAITING",
            "time_left": round(time_left, 1),
            "coins": [[x, y] for (x, y) in sorted(self.coins)],
            "snakes": snakes_data,
            "fires": fires,
        }

    def _check_game_end(self) -> bool:
        if not self.match_started:
            return False
        alive = [s for s in self.snakes.values() if s.alive]
        if len(alive) <= 1:
            reason = "last_snake" if alive else "all_dead"
            self._finish_game(reason)
            return True
        if self.start_time and time.time() - self.start_time >= TIME_LIMIT_SEC:
            self._finish_game("time_limit")
            return True
        return False

    def _finish_game(self, reason: str) -> None:
        winners = []
        alive = [s for s in self.snakes.values() if s.alive]
        if len(alive) == 1:
            winners = [alive[0].name]
        else:
            max_coins = max((s.coins for s in self.snakes.values()), default=0)
            winners = [s.name for s in self.snakes.values() if s.coins == max_coins]
        results = []
        for name, snake in self.snakes.items():
            outcome = "LOSE"
            if snake.quit_flag:
                outcome = "QUIT"
            elif name in winners and len(winners) == 1:
                outcome = "WIN"
            elif name in winners:
                outcome = "DRAW"
            results.append({"player": name, "outcome": outcome, "rank": None, "score": snake.coins})
        self._report_status("END", results=results, reason=reason)
        payload = {
            "type": "game_over",
            "reason": reason,
            "winners": winners,
            "results": results,
        }
        for conn in list(self.connections.values()):
            send_json(conn, payload)
        for conn in list(self.spectators.values()):
            send_json(conn, payload)

    def _close_all(self) -> None:
        try:
            if self.listener:
                self.listener.close()
        except Exception:
            pass
        for conn in list(self.connections.values()):
            try:
                conn.close()
            except Exception:
                pass
        for conn in list(self.spectators.values()):
            try:
                conn.close()
            except Exception:
                pass


def send_json(conn: socket.socket, obj: Dict) -> bool:
    try:
        conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")
        return True
    except Exception as exc:
        logger.warning("send_json failed: %s", exc)
        return False


def recv_json(conn: socket.socket) -> Optional[Dict]:
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


def _load_players(args: argparse.Namespace) -> List[str]:
    players: List[str] = []
    players_path = os.getenv("PLAYERS_JSON_PATH", "")
    if players_path:
        try:
            players = json.loads(Path(players_path).read_text(encoding="utf-8"))
        except Exception:
            players = []
    if not players:
        players = [args.p1, args.p2, args.p3, args.p4]
    return [p for p in players if p]


def main() -> None:
    parser = argparse.ArgumentParser(description="GreedySnake room-local server.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--p1", default="")
    parser.add_argument("--p2", default="")
    parser.add_argument("--p3", default="")
    parser.add_argument("--p4", default="")
    parser.add_argument("--bind_host", default=os.getenv("BIND_HOST", "0.0.0.0"))
    parser.add_argument("--match_id", default=os.getenv("MATCH_ID", ""))
    parser.add_argument("--client_token", default="")
    parser.add_argument("--report_token", default="")
    parser.add_argument("--client_token_path", default="")
    parser.add_argument("--report_token_path", default="")
    parser.add_argument("--report_host", help="optional host to report game results to")
    parser.add_argument("--report_port", type=int, help="optional port to report game results to")
    args = parser.parse_args()

    def resolve_secret(explicit: str, explicit_path: str, env_name: str, path_env: str) -> str:
        if explicit:
            return explicit
        if explicit_path:
            try:
                return Path(explicit_path).read_text(encoding="utf-8").strip()
            except Exception:
                return ""
        return _read_secret(env_name, path_env)

    client_token = resolve_secret(args.client_token, args.client_token_path, "CLIENT_TOKEN", "CLIENT_TOKEN_PATH")
    report_token = resolve_secret(args.report_token, args.report_token_path, "REPORT_TOKEN", "REPORT_TOKEN_PATH")
    match_id = args.match_id or os.getenv("MATCH_ID", "")
    if not client_token or not report_token or not match_id:
        logger.error("missing required client_token/report_token/match_id; aborting")
        return

    players = _load_players(args)
    if len(players) < 2:
        logger.error("need at least 2 players, got %s", len(players))
        return

    server = GreedySnakeServer(
        port=args.port,
        room_id=args.room,
        client_token=client_token,
        match_id=match_id,
        players=players,
        bind_host=args.bind_host,
        report_host=args.report_host,
        report_port=args.report_port,
        report_token=report_token,
    )
    try:
        server.start()
    except KeyboardInterrupt:
        server.running = False
        server._report_status("ERROR", err_msg="interrupted")
        logger.warning("interrupted")


if __name__ == "__main__":
    main()
