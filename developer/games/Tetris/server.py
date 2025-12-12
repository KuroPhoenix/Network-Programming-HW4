import argparse
import json
import random
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

WIDTH = 10
HEIGHT = 20

SHAPES = {
    "I": [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
    ],
    "O": [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
    ],
    "T": [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "S": [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
    ],
    "Z": [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
    ],
    "J": [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    "L": [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}


def send_json(conn: socket.socket, obj: Dict):
    conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")


def recv_json(conn: socket.socket):
    buf = b""
    try:
        while True:
            chunk = conn.recv(1)
            if not chunk:
                return None
            if chunk == b"\n":
                break
            buf += chunk
    except Exception:
        return None
    try:
        return json.loads(buf.decode("utf-8"))
    except Exception:
        return None


@dataclass
class Piece:
    kind: str
    rotation: int
    x: int
    y: int

    def cells(self) -> List[Tuple[int, int]]:
        coords = SHAPES[self.kind][self.rotation % len(SHAPES[self.kind])]
        return [(self.x + cx, self.y + cy) for cx, cy in coords]


@dataclass
class PlayerState:
    name: str
    board: List[List[str]] = field(default_factory=lambda: [["." for _ in range(WIDTH)] for _ in range(HEIGHT)])
    queue: deque = field(default_factory=deque)
    piece: Optional[Piece] = None
    next_pieces: deque = field(default_factory=deque)
    hold: Optional[str] = None
    hold_used: bool = False
    score: int = 0
    lines: int = 0
    alive: bool = True


class TetrisServer:
    def __init__(
        self,
        port: int,
        room: str,
        token: str,
        p1: str,
        p2: str,
        tick_ms: int = 500,
        report_host: Optional[str] = None,
        report_port: Optional[int] = None,
        report_token: str = "",
    ):
        self.port = port
        self.room = room
        self.token = token
        self.players_order = [p1, p2]
        self.states: Dict[str, PlayerState] = {
            p1: PlayerState(p1),
            p2: PlayerState(p2),
        }
        self.connections: Dict[str, socket.socket] = {}
        self.spectators: Dict[str, socket.socket] = {}
        self.tick_ms = tick_ms
        self.running = True
        self.report_host = report_host
        self.report_port = report_port
        self.report_token = report_token or token

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self.port))
        listener.listen(2)
        print(f"[server] Tetris listening on 0.0.0.0:{self.port} room={self.room}")

        try:
            listener.settimeout(1.0)
            while len(self.connections) < 2:
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                self.handle_handshake(conn, addr, allow_players=True)

            # Start reader threads
            for pname in self.players_order:
                threading.Thread(target=self.reader_thread, args=(pname,), daemon=True).start()

            # Keep accepting spectators during the match
            threading.Thread(target=self.accept_spectators, args=(listener,), daemon=True).start()

            # Heartbeat reporting
            threading.Thread(target=self._heartbeat, daemon=True).start()

            # Initialize bags and first pieces
            bag = self.new_bag()
            for pname in self.players_order:
                state = self.states[pname]
                state.next_pieces.extend(bag.copy())
                self.spawn_piece(state)

            # Main game loop
            while self.running:
                start = time.time()
                for pname in self.players_order:
                    state = self.states[pname]
                    if not state.alive:
                        continue
                    self.process_commands(state)
                    self.gravity(state)
                self.broadcast_state()
                if all(not s.alive for s in self.states.values()):
                    winner = self.compute_winner()
                    loser = [p for p in self.players_order if p != winner][0]
                    for conn in self.connections.values():
                        send_json(conn, {"type": "game_over", "winner": winner})
                    for conn in self.spectators.values():
                        send_json(conn, {"type": "game_over", "winner": winner})
                    self._report_status("END", winner=winner, loser=loser, reason="normal")
                    self.running = False
                    break
                elapsed = (time.time() - start) * 1000
                sleep_ms = max(0, self.tick_ms - elapsed)
                time.sleep(sleep_ms / 1000.0)
        except Exception as exc:
            self.running = False
            self._report_status("ERROR", err_msg=str(exc))
            raise

    def handle_handshake(self, conn: socket.socket, addr, allow_players: bool):
        hello = recv_json(conn)
        if not hello or hello.get("token") != self.token:
            conn.close()
            return
        role = hello.get("role", "player").lower()
        pname = hello.get("player")
        if role == "spectator":
            name = pname or f"spec-{addr[0]}:{addr[1]}"
            if name in self.spectators:
                conn.close()
                return
            self.spectators[name] = conn
            send_json(conn, {"type": "ok", "message": "connected", "room": self.room, "you": name, "role": "spectator"})
            print(f"[server] spectator {name} connected from {addr}")
            return
        if not allow_players:
            send_json(conn, {"type": "error", "message": "spectators only"})
            conn.close()
            return
        if pname not in self.players_order or pname in self.connections:
            send_json(conn, {"type": "error", "message": "bad player"})
            conn.close()
            return
        self.connections[pname] = conn
        send_json(conn, {"type": "ok", "message": "connected", "room": self.room, "you": pname, "role": "player"})
        print(f"[server] {pname} connected from {addr}")

    def accept_spectators(self, listener: socket.socket):
        while self.running:
            try:
                conn, addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle_handshake(conn, addr, allow_players=False)

    def reader_thread(self, pname: str):
        conn = self.connections[pname]
        conn.settimeout(0.1)
        while self.running:
            try:
                msg = recv_json(conn)
            except Exception:
                msg = None
            if not msg:
                time.sleep(0.05)
                continue
            if msg.get("type") == "cmd":
                cmd = msg.get("cmd", "").upper()
                self.states[pname].queue.append(cmd)
            elif msg.get("type") == "quit":
                self.states[pname].alive = False
                return

    def new_bag(self) -> List[str]:
        bag = list(SHAPES.keys())
        random.shuffle(bag)
        return bag

    def spawn_piece(self, state: PlayerState):
        if len(state.next_pieces) < 3:
            state.next_pieces.extend(self.new_bag())
        kind = state.next_pieces.popleft()
        state.piece = Piece(kind=kind, rotation=0, x=3, y=0)
        state.hold_used = False
        if not self.valid_position(state, state.piece):
            state.alive = False

    def hold_piece(self, state: PlayerState):
        if not state.piece or state.hold_used or not state.alive:
            return
        current_kind = state.piece.kind
        if state.hold is None:
            state.hold = current_kind
            self.spawn_piece(state)
        else:
            swap_kind = state.hold
            state.hold = current_kind
            new_piece = Piece(kind=swap_kind, rotation=0, x=3, y=0)
            if self.valid_position(state, new_piece):
                state.piece = new_piece
            else:
                state.alive = False
        state.hold_used = True

    def process_commands(self, state: PlayerState):
        while state.queue:
            cmd = state.queue.popleft()
            if cmd == "LEFT":
                self.try_move(state, dx=-1, dy=0)
            elif cmd == "RIGHT":
                self.try_move(state, dx=1, dy=0)
            elif cmd == "DOWN":
                moved = self.try_move(state, dx=0, dy=1)
                if not moved:
                    self.lock_piece(state)
            elif cmd == "ROTATE":
                self.try_rotate(state)
            elif cmd == "DROP":
                while self.try_move(state, dx=0, dy=1):
                    state.score += 1
                self.lock_piece(state)
            elif cmd == "HOLD":
                self.hold_piece(state)
            elif cmd == "QUIT":
                state.alive = False

    def try_move(self, state: PlayerState, dx: int, dy: int) -> bool:
        if not state.piece:
            return False
        new_piece = Piece(state.piece.kind, state.piece.rotation, state.piece.x + dx, state.piece.y + dy)
        if self.valid_position(state, new_piece):
            state.piece = new_piece
            return True
        return False

    def try_rotate(self, state: PlayerState) -> bool:
        if not state.piece:
            return False
        new_piece = Piece(state.piece.kind, state.piece.rotation + 1, state.piece.x, state.piece.y)
        if self.valid_position(state, new_piece):
            state.piece = new_piece
            return True
        return False

    def valid_position(self, state: PlayerState, piece: Piece) -> bool:
        for x, y in piece.cells():
            if x < 0 or x >= WIDTH or y < 0 or y >= HEIGHT:
                return False
            if state.board[y][x] != ".":
                return False
        return True

    def gravity(self, state: PlayerState):
        if not state.piece or not state.alive:
            return
        if not self.try_move(state, dx=0, dy=1):
            self.lock_piece(state)

    def lock_piece(self, state: PlayerState):
        if not state.piece:
            return
        for x, y in state.piece.cells():
            if 0 <= y < HEIGHT and 0 <= x < WIDTH:
                state.board[y][x] = state.piece.kind
            else:
                state.alive = False
        state.piece = None
        cleared = self.clear_lines(state)
        state.lines += cleared
        state.score += 100 + cleared * 100
        if state.alive:
            self.spawn_piece(state)

    def clear_lines(self, state: PlayerState) -> int:
        new_board = [row for row in state.board if any(cell == "." for cell in row)]
        cleared = HEIGHT - len(new_board)
        for _ in range(cleared):
            new_board.insert(0, ["." for _ in range(WIDTH)])
        state.board = new_board
        return cleared

    def board_as_strings(self, state: PlayerState) -> List[str]:
        temp = [row.copy() for row in state.board]
        if state.piece:
            for x, y in state.piece.cells():
                if 0 <= y < HEIGHT and 0 <= x < WIDTH:
                    temp[y][x] = state.piece.kind.lower()
        return ["".join(row) for row in temp]

    def broadcast_state(self):
        for pname, conn in list(self.connections.items()):
            state = self.states[pname]
            opp = [p for p in self.players_order if p != pname][0]
            opp_state = self.states[opp]
            payload = {
                "type": "tick",
                "you": pname,
                "board": self.board_as_strings(state),
                "next": list(state.next_pieces)[:3],
                "hold": state.hold,
                "score": state.score,
                "lines": state.lines,
                "alive": state.alive,
                "opponent": {
                    "name": opp_state.name,
                    "alive": opp_state.alive,
                    "lines": opp_state.lines,
                    "score": opp_state.score,
                    "hold": opp_state.hold,
                },
            }
            send_json(conn, payload)

        if self.spectators:
            snapshot = {}
            for pname in self.players_order:
                s = self.states[pname]
                snapshot[pname] = {
                    "board": self.board_as_strings(s),
                    "next": list(s.next_pieces)[:3],
                    "hold": s.hold,
                    "score": s.score,
                    "lines": s.lines,
                    "alive": s.alive,
                }
            payload = {"type": "tick", "room": self.room, "players": snapshot}
            for conn in list(self.spectators.values()):
                send_json(conn, payload)

    def compute_winner(self) -> str:
        p1, p2 = self.players_order
        s1, s2 = self.states[p1], self.states[p2]
        if s1.alive and not s2.alive:
            return p1
        if s2.alive and not s1.alive:
            return p2
        if s1.score != s2.score:
            return p1 if s1.score > s2.score else p2
        return p1 if s1.lines >= s2.lines else p2

    def _report_status(self, status: str, winner: Optional[str] = None, loser: Optional[str] = None,
                       err_msg: Optional[str] = None, reason: Optional[str] = None):
        if not self.report_host or not self.report_port:
            return
        payload = {
            "type": "GAME.REPORT",
            "status": status,
            "game": "Tetris",
            "room_id": self.room,
        }
        if self.report_token:
            payload["report_token"] = self.report_token
        if winner:
            payload["winner"] = winner
        if loser:
            payload["loser"] = loser
        if err_msg:
            payload["err_msg"] = err_msg
        if reason:
            payload["reason"] = reason
        payload["scores"] = {p: self.states[p].score for p in self.players_order}
        payload["lines"] = {p: self.states[p].lines for p in self.players_order}
        try:
            with socket.create_connection((self.report_host, self.report_port), timeout=3) as conn:
                send_json(conn, payload)
        except Exception as exc:
            print(f"[server] failed to report result: {exc}")

    def _heartbeat(self):
        while self.running:
            self._report_status("RUNNING", reason="heartbeat")
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description="Tetris room-local server (Python rewrite).")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--p1", required=True)
    parser.add_argument("--p2", required=True)
    parser.add_argument("--tick_ms", type=int, default=500, help="gravity tick in ms")
    parser.add_argument("--report_host", help="optional host to report game results to")
    parser.add_argument("--report_port", type=int, help="optional port to report game results to")
    parser.add_argument("--report_token", help="token to authenticate reports", default="")
    args = parser.parse_args()

    srv = TetrisServer(
        args.port,
        args.room,
        args.token,
        args.p1,
        args.p2,
        tick_ms=args.tick_ms,
        report_host=args.report_host,
        report_port=args.report_port,
        report_token=args.report_token or args.token,
    )
    try:
        srv.start()
    except KeyboardInterrupt:
        srv.running = False
        srv._report_status("ERROR", err_msg="interrupted")
        print("\n[server] interrupted")


if __name__ == "__main__":
    main()
