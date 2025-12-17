import argparse
import json
import socket
import sys
import threading
import time
import os
import logging
from pathlib import Path
from typing import Dict, Optional

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


_configure_logging("game_rps_server.log")
logger = logging.getLogger(__name__)


def send_json(conn: socket.socket, obj: dict):
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
            return open(path, "r", encoding="utf-8").read().strip()
        except Exception:
            return ""
    return ""


CHOICES = {"rock", "paper", "scissors"}


class RPSServer:
    def __init__(
        self,
        port: int,
        room_id: str,
        client_token: str,
        match_id: str,
        p1: str,
        p2: str,
        p3: str = "",
        bind_host: str = "0.0.0.0",
        report_host: Optional[str] = None,
        report_port: Optional[int] = None,
        report_token: str = "",
    ):
        self.port = port
        self.room_id = int(room_id)
        self.room = str(room_id)
        self.client_token = client_token
        self.match_id = match_id
        self.bind_host = bind_host
        # Seed allowed players; empty seeds will be filled by dynamic joins
        self.players = [p for p in [p1, p2, p3] if p]
        self.max_players = 3
        self.connections: Dict[str, socket.socket] = {}
        self.moves: Dict[str, str] = {}
        self.running = True
        self.report_host = report_host
        self.report_port = report_port
        self.report_token = report_token
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
        listener.bind((self.bind_host, self.port))
        listener.listen(2)
        self.listener = listener
        print(f"[server] RPS listening on {self.bind_host}:{self.port} room={self.room}")
        self._report_status("STARTED")

        try:
            listener.settimeout(1.0)
            while len(self.connections) < self.max_players and self.running:
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                self.handle_handshake(conn, addr)

            if not self.running:
                return

            threading.Thread(target=self._heartbeat, daemon=True).start()
            for pname in list(self.connections.keys()):
                threading.Thread(target=self.player_thread, args=(pname,), daemon=True).start()

            self.broadcast_rules()
            self.broadcast_state()

            while self.running:
                with self.lock:
                    if len(self.moves) >= 2 and len(self.moves) == len(self.connections):
                        moves_copy = dict(self.moves)
                        players_order = list(self.connections.keys())
                        winner, loser, reason = self.decide_winner(moves_copy, players_order)
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
        if not hello:
            conn.close()
            return
        if hello.get("client_token") != self.client_token:
            send_json(conn, {"ok": False, "reason": "invalid client token"})
            conn.close()
            return
        if hello.get("match_id") != self.match_id:
            send_json(conn, {"ok": False, "reason": "invalid match_id"})
            conn.close()
            return
        if int(hello.get("room_id", -1)) != self.room_id:
            send_json(conn, {"ok": False, "reason": "invalid room_id"})
            conn.close()
            return
        pname = hello.get("player_name")
        if not pname:
            send_json(conn, {"ok": False, "reason": "player_name required"})
            conn.close()
            return
        with self.lock:
            if pname in self.connections:
                send_json(conn, {"ok": False, "reason": "duplicate player"})
                conn.close()
                return
            if pname not in self.players and len(self.players) < self.max_players:
                self.players.append(pname)
            if pname not in self.players or len(self.connections) >= self.max_players:
                send_json(conn, {"ok": False, "reason": "bad player"})
                conn.close()
                return
            self.connections[pname] = conn
        send_json(conn, {"ok": True, "assigned_player_index": self.players.index(pname), "game_protocol_version": 1})
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
                    self.finish_game(self.pick_alt_winner(exclude=pname), pname, reason="disconnect")
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
                    self.finish_game(self.pick_alt_winner(exclude=pname), pname, reason="surrender")
                    return
                else:
                    send_json(conn, {"type": "error", "message": "unknown command"})
        except Exception as exc:
            logger.warning("error in player thread %s: %s", pname, exc)
            self.finish_game(self.pick_alt_winner(exclude=pname), pname, reason="error")

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

    def decide_winner(self, moves_copy: Optional[Dict[str, str]] = None, players_order: Optional[list[str]] = None):
        """
        With up to 3 players:
          - If all same move → tie (deterministic winner = first player).
          - If all three moves present → tie (first player wins tie-break).
          - If two moves present → move that beats the other wins; all players with that move are winners,
            tie-broken deterministically by name.
        """
        beats = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
        if moves_copy is None or players_order is None:
            with self.lock:
                moves_copy = dict(self.moves)
                players_order = list(self.connections.keys())
        unique_moves = set(moves_copy.values())
        if len(unique_moves) == 1 or len(unique_moves) == 3:
            winner = players_order[0] if players_order else None
            loser = next((p for p in players_order if p != winner), None)
            return winner, loser, "tie_break"
        # Two-move case
        mlist = list(unique_moves)
        win_move = None
        if (mlist[0], mlist[1]) in beats:
            win_move = mlist[0]
        elif (mlist[1], mlist[0]) in beats:
            win_move = mlist[1]
        winners = sorted([p for p, mv in moves_copy.items() if mv == win_move])
        winner = winners[0] if winners else None
        loser = next((p for p in players_order if p not in winners), None)
        return winner, loser, "normal"

    def finish_game(self, winner: Optional[str], loser: Optional[str], reason: str = "normal"):
        if not self.running:
            return
        self.running = False
        for conn in list(self.connections.values()):
            send_json(conn, {"type": "game_over", "winner": winner, "loser": loser, "reason": reason})
        print(f"[server] game over winner={winner} loser={loser} reason={reason}")
        results = []
        if winner:
            results.append({"player": winner, "outcome": "WIN", "rank": 1, "score": None})
        if loser:
            results.append({"player": loser, "outcome": "LOSE", "rank": 2, "score": None})
        if not results:
            for pname in self.players:
                results.append({"player": pname, "outcome": "DRAW", "rank": None, "score": None})
        self._report_status("END", winner=winner, loser=loser, reason=reason, results=results)
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
        results: Optional[list] = None,
    ):
        if not self.report_host or not self.report_port:
            return
        payload = {
            "type": "GAME.REPORT",
            "status": status,
            "game": "RockPaperScissors",
            "room_id": self.room_id,
            "match_id": self.match_id,
            "report_token": self.report_token,
            "timestamp": time.time(),
        }
        if status == "STARTED":
            payload["port"] = self.port
        if winner:
            payload["winner"] = winner
        if loser:
            payload["loser"] = loser
        if err_msg:
            payload["err_msg"] = err_msg
        if reason:
            payload["reason"] = reason
        if results is not None:
            payload["results"] = results
        try:
            with socket.create_connection((self.report_host, self.report_port), timeout=3) as conn:
                send_json(conn, payload)
        except Exception as exc:
            logger.warning("failed to report result: %s", exc)

    def _heartbeat(self):
        while self.running:
            self._report_status("HEARTBEAT", reason="heartbeat")
            time.sleep(10)

    def other_player(self, pname: str) -> Optional[str]:
        for p in self.players:
            if p != pname:
                return p
        return None

    def pick_alt_winner(self, exclude: str) -> Optional[str]:
        with self.lock:
            for p in self.players:
                if p != exclude and p in self.connections:
                    return p
        return None


def main():
    parser = argparse.ArgumentParser(description="Rock-Paper-Scissors room-local server.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--p1", required=True)
    parser.add_argument("--p2", required=True)
    parser.add_argument("--p3", default="")
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
                return open(explicit_path, "r", encoding="utf-8").read().strip()
            except Exception:
                return ""
        return _read_secret(env_name, path_env)

    client_token = resolve_secret(args.client_token, args.client_token_path, "CLIENT_TOKEN", "CLIENT_TOKEN_PATH")
    report_token = resolve_secret(args.report_token, args.report_token_path, "REPORT_TOKEN", "REPORT_TOKEN_PATH")
    match_id = args.match_id or os.getenv("MATCH_ID", "")
    if not client_token or not report_token or not match_id:
        logger.error("missing required client_token/report_token/match_id; aborting")
        sys.exit(2)

    srv = RPSServer(
        port=args.port,
        room_id=args.room,
        client_token=client_token,
        match_id=match_id,
        p1=args.p1,
        p2=args.p2,
        p3=args.p3,
        bind_host=args.bind_host,
        report_host=args.report_host,
        report_port=args.report_port,
        report_token=report_token,
    )
    try:
        srv.start()
    except KeyboardInterrupt:
        srv.running = False
        srv._report_status("ERROR", err_msg="interrupted")
        logger.warning("interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()
