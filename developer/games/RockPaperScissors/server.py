import argparse
import json
import socket
import sys
import threading
import time
from typing import Dict, Optional


def send_json(conn: socket.socket, obj: dict):
    conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")


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


CHOICES = {"rock", "paper", "scissors"}


class RPSServer:
    def __init__(
        self,
        port: int,
        room: str,
        token: str,
        p1: str,
        p2: str,
        report_host: Optional[str] = None,
        report_port: Optional[int] = None,
        report_token: str = "",
    ):
        self.port = port
        self.room = room
        self.token = token
        self.players = [p1, p2]
        self.connections: Dict[str, socket.socket] = {}
        self.moves: Dict[str, str] = {}
        self.running = True
        self.report_host = report_host
        self.report_port = report_port
        self.report_token = report_token or token
        self.listener: Optional[socket.socket] = None
        self.lock = threading.Lock()

    def _rules_payload(self) -> dict:
        return {
            "type": "rules",
            "text": "Submit one of: rock, paper, scissors. First valid round decides winner; surrender forfeits.",
        }

    def broadcast_rules(self):
        payload = self._rules_payload()
        for conn in list(self.connections.values()):
            send_json(conn, payload)

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self.port))
        listener.listen(2)
        self.listener = listener
        print(f"[server] RPS listening on 0.0.0.0:{self.port} room={self.room}")

        try:
            listener.settimeout(1.0)
            while len(self.connections) < 2 and self.running:
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                self.handle_handshake(conn, addr)

            if not self.running:
                return

            threading.Thread(target=self._heartbeat, daemon=True).start()
            for pname in self.players:
                threading.Thread(target=self.player_thread, args=(pname,), daemon=True).start()

            self.broadcast_rules()
            self.broadcast_state()

            while self.running:
                with self.lock:
                    if len(self.moves) == 2:
                        winner, loser, reason = self.decide_winner()
                        self.finish_game(winner, loser, reason)
                        return
                time.sleep(0.1)
        except Exception as exc:
            self.running = False
            self._report_status("ERROR", err_msg=str(exc))
            raise
        finally:
            self.running = False
            try:
                listener.close()
            except Exception:
                pass

    def handle_handshake(self, conn: socket.socket, addr):
        hello = recv_json(conn)
        if not hello or hello.get("token") != self.token:
            conn.close()
            return
        pname = hello.get("player")
        if pname not in self.players or pname in self.connections:
            send_json(conn, {"type": "error", "message": "bad player"})
            conn.close()
            return
        self.connections[pname] = conn
        send_json(conn, {"type": "ok", "role": "player", "room": self.room, "you": pname})
        print(f"[server] player {pname} connected from {addr}")

    def player_thread(self, pname: str):
        conn = self.connections.get(pname)
        if not conn:
            return
        try:
            while self.running:
                msg = recv_json(conn)
                if not msg:
                    print(f"[server] {pname} disconnected")
                    self.finish_game(self.other_player(pname), pname, reason="disconnect")
                    return
                mtype = msg.get("type")
                if mtype == "move":
                    move = str(msg.get("move", "")).lower().strip()
                    if move not in CHOICES:
                        send_json(conn, {"type": "error", "message": "move must be rock, paper, or scissors"})
                        continue
                    with self.lock:
                        self.moves[pname] = move
                    self.broadcast_state()
                elif mtype == "surrender":
                    self.finish_game(self.other_player(pname), pname, reason="surrender")
                    return
                else:
                    send_json(conn, {"type": "error", "message": "unknown command"})
        except Exception as exc:
            print(f"[server] error in player thread {pname}: {exc}")
            self.finish_game(self.other_player(pname), pname, reason="error")

    def broadcast_state(self):
        with self.lock:
            moves_copy = dict(self.moves)
        for pname, conn in list(self.connections.items()):
            opp = self.other_player(pname)
            send_json(
                conn,
                {
                    "type": "state",
                    "room": self.room,
                    "you": pname,
                    "your_move": moves_copy.get(pname),
                    "opponent": {"name": opp, "submitted": opp in moves_copy},
                },
            )

    def decide_winner(self):
        p1, p2 = self.players
        m1, m2 = self.moves.get(p1), self.moves.get(p2)
        beats = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
        if m1 == m2:
            # deterministic tie-breaker: player1 wins
            return p1, p2, "tie_break"
        if (m1, m2) in beats:
            return p1, p2, "normal"
        return p2, p1, "normal"

    def finish_game(self, winner: Optional[str], loser: Optional[str], reason: str = "normal"):
        if not self.running:
            return
        self.running = False
        for conn in list(self.connections.values()):
            send_json(conn, {"type": "game_over", "winner": winner, "loser": loser, "reason": reason})
        print(f"[server] game over winner={winner} loser={loser} reason={reason}")
        self._report_status("END", winner=winner, loser=loser, reason=reason)
        try:
            if self.listener:
                self.listener.close()
        except Exception:
            pass

    def _report_status(
        self,
        status: str,
        winner: Optional[str] = None,
        loser: Optional[str] = None,
        err_msg: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        if not self.report_host or not self.report_port:
            return
        payload = {
            "type": "GAME.REPORT",
            "status": status,
            "game": "RockPaperScissors",
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
        try:
            with socket.create_connection((self.report_host, self.report_port), timeout=3) as conn:
                send_json(conn, payload)
        except Exception as exc:
            print(f"[server] failed to report result: {exc}")

    def _heartbeat(self):
        while self.running:
            self._report_status("RUNNING", reason="heartbeat")
            time.sleep(10)

    def other_player(self, pname: str) -> Optional[str]:
        for p in self.players:
            if p != pname:
                return p
        return None


def main():
    parser = argparse.ArgumentParser(description="Rock-Paper-Scissors room-local server.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--p1", required=True)
    parser.add_argument("--p2", required=True)
    parser.add_argument("--report_host", help="optional host to report game results to")
    parser.add_argument("--report_port", type=int, help="optional port to report game results to")
    parser.add_argument("--report_token", help="token to authenticate reports", default="")
    args = parser.parse_args()

    srv = RPSServer(
        port=args.port,
        room=args.room,
        token=args.token,
        p1=args.p1,
        p2=args.p2,
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
        sys.exit(0)


if __name__ == "__main__":
    main()
