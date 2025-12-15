import argparse
import json
import socket
import sys
import threading
import time
from typing import Dict, Optional

from board import ConnectFourBoard


def send_json(conn: socket.socket, obj: dict) -> bool:
    try:
        conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")
        return True
    except Exception:
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
    except Exception:
        return None
    try:
        return json.loads(buf.decode("utf-8"))
    except Exception:
        return None


class ConnectFourServer:
    def __init__(self, port: int, room: str, token: str, p1: str, p2: str, report_host: str, report_port: int, report_token: str):
        self.port = port
        self.room = room
        self.token = token
        self.report_host = report_host
        self.report_port = report_port
        self.report_token = report_token or token
        self.expected_players = [p1, p2]
        self.board = ConnectFourBoard()
        self.connections: Dict[str, socket.socket] = {}
        self.running = True
        self.winner: Optional[str] = None
        self.reason: Optional[str] = None
        self.lock = threading.Lock()
        self.listener: Optional[socket.socket] = None

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self.port))
        listener.listen(2)
        listener.settimeout(1.0)
        self.listener = listener
        print(f"[server] ConnectFour listening on 0.0.0.0:{self.port} room={self.room}")
        try:
            while self.running and len(self.connections) < 2:
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle_handshake, args=(conn, addr), daemon=True).start()

            # Wait for both players
            while self.running and len(self.connections) < 2:
                time.sleep(0.1)

            if len(self.connections) < 2:
                return

            self._report_status("RUNNING")
            self._broadcast_state()

            # Start player loops
            for player in list(self.connections.keys()):
                threading.Thread(target=self._player_loop, args=(player,), daemon=True).start()

            while self.running:
                time.sleep(0.2)
        except KeyboardInterrupt:
            self._end_game(winner=None, reason="server_interrupt")
        except Exception as exc:
            print(f"[server] fatal error: {exc}")
            self._end_game(winner=None, reason=str(exc))
            self._report_status("ERROR", err_msg=str(exc))
        finally:
            self.running = False
            try:
                listener.close()
            except Exception:
                pass
            for conn in list(self.connections.values()):
                try:
                    conn.close()
                except Exception:
                    pass

    def _handle_handshake(self, conn: socket.socket, addr):
        try:
            conn.settimeout(120)
        except Exception:
            pass
        hello = recv_json(conn)
        if not hello or hello.get("token") != self.token:
            conn.close()
            return
        player = hello.get("player")
        if player not in self.expected_players:
            send_json(conn, {"type": "error", "message": "player not allowed in this room"})
            conn.close()
            return
        with self.lock:
            if player in self.connections:
                send_json(conn, {"type": "error", "message": "duplicate player"})
                conn.close()
                return
            self.connections[player] = conn
        try:
            conn.settimeout(None)
        except Exception:
            pass
        send_json(conn, {"type": "ok", "room": self.room, "you": player})
        print(f"[server] player {player} connected from {addr}")

    def _player_loop(self, player: str):
        conn = self.connections.get(player)
        if not conn:
            return
        try:
            while self.running:
                msg = recv_json(conn)
                if msg is None:
                    self._handle_disconnect(player, reason="disconnect")
                    break
                mtype = msg.get("type")
                if mtype == "move":
                    try:
                        col = int(msg.get("col"))
                    except Exception:
                        send_json(conn, {"type": "error", "message": "invalid column"})
                        continue
                    self._handle_move(player, col)
                elif mtype == "surrender":
                    self._end_game(winner=self._opponent(player), reason="surrender")
                else:
                    send_json(conn, {"type": "error", "message": "unknown command"})
        except Exception as exc:
            self._handle_disconnect(player, reason=str(exc))

    def _handle_move(self, player: str, col: int):
        with self.lock:
            if not self.running or self.winner:
                return
            conn = self.connections.get(player)
            if not conn:
                return
            current_player = self.expected_players[(self.board.turn - 1)]
            if player != current_player:
                send_json(conn, {"type": "error", "message": "not your turn"})
                return
            mark = 1 if player == self.expected_players[0] else 2
            result = self.board.drop(col, mark)
            if not result.valid:
                send_json(conn, {"type": "error", "message": "invalid move"})
                return
            if result.winner is not None:
                self._end_game(winner=player, reason="connect_four")
            elif result.draw:
                self._end_game(winner=None, reason="draw")
            else:
                self._broadcast_state()

    def _handle_disconnect(self, player: str, reason: str):
        with self.lock:
            if player in self.connections:
                try:
                    self.connections[player].close()
                except Exception:
                    pass
                self.connections.pop(player, None)
            if self.running and not self.winner:
                self._end_game(winner=self._opponent(player), reason=reason)

    def _broadcast_state(self):
        state = {
            "type": "state",
            "room": self.room,
            "board": self.board.to_state(),
            "players": self.expected_players,
            "turn_player": self.expected_players[(self.board.turn - 1)],
            "winner": None,
            "reason": None,
        }
        for p, conn in list(self.connections.items()):
            if not send_json(conn, state):
                self._handle_disconnect(p, reason="send_failed")

    def _end_game(self, winner: Optional[str], reason: str):
        if not self.running:
            return
        self.running = False
        self.winner = winner
        self.reason = reason
        payload = {
            "type": "game_over",
            "winner": winner,
            "reason": reason,
            "board": self.board.to_state(),
        }
        for p, conn in list(self.connections.items()):
            send_json(conn, payload)
        status = "END" if winner or reason == "draw" else "ERROR"
        self._report_status(status, winner=winner, err_msg=reason)
        print(f"[server] game ended winner={winner} reason={reason}")

    def _report_status(self, status: str, winner: Optional[str] = None, err_msg: Optional[str] = None):
        if not self.report_host or not self.report_port:
            return
        payload = {
            "type": "GAME.REPORT",
            "status": status,
            "room_id": self.room,
            "report_token": self.report_token,
        }
        if winner:
            payload["winner"] = winner
            payload["loser"] = self._opponent(winner)
        if err_msg:
            payload["err_msg"] = err_msg
            payload["reason"] = err_msg
        try:
            with socket.create_connection((self.report_host, int(self.report_port)), timeout=3) as s:
                send_json(s, payload)
        except Exception:
            print("[server] failed to report status to lobby")

    def _opponent(self, player: str) -> Optional[str]:
        if player == self.expected_players[0]:
            return self.expected_players[1]
        if player == self.expected_players[1]:
            return self.expected_players[0]
        return None


def parse_args():
    parser = argparse.ArgumentParser(description="ConnectFour game server")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--p1", required=True)
    parser.add_argument("--p2", required=True)
    parser.add_argument("--report_host", required=True)
    parser.add_argument("--report_port", type=int, required=True)
    parser.add_argument("--report_token", default="")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        server = ConnectFourServer(
            port=args.port,
            room=str(args.room),
            token=args.token,
            p1=args.p1,
            p2=args.p2,
            report_host=args.report_host,
            report_port=args.report_port,
            report_token=args.report_token,
        )
        server.start()
    except Exception as exc:
        print(f"[server] exiting due to error: {exc}")
        sys.exit(1)
