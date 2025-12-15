import argparse
import json
import random
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def send_json(conn: socket.socket, obj: Dict) -> bool:
    try:
        conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")
        return True
    except Exception:
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
    except Exception:
        return None
    try:
        return json.loads(buf.decode("utf-8"))
    except Exception:
        return None


def _load_dictionary() -> tuple[list[str], set[str]]:
    """
    Load the full English word list from words_dictionary.json.
    Falls back to a small built-in list if the file is missing or unreadable.
    """
    fallback = [
        "apple",
        "cabin",
        "crane",
        "crown",
        "daily",
        "eager",
        "flame",
        "gamer",
        "glove",
        "honey",
        "input",
        "jelly",
        "knock",
        "lemon",
        "movie",
        "noble",
        "ocean",
        "piano",
        "quilt",
        "rider",
        "stone",
        "tiger",
        "vivid",
        "waltz",
        "xenon",
        "young",
        "zebra",
    ]
    path = Path(__file__).resolve().parent / "words_dictionary.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            words = [w.lower() for w in data.keys() if len(w) == 5 and w.isalpha()]
        elif isinstance(data, list):
            words = [str(w).lower() for w in data if len(str(w)) == 5 and str(w).isalpha()]
        else:
            words = fallback
    except Exception as exc:
        print(f"[server] failed to load dictionary {path}: {exc}; using fallback list")
        words = fallback
    if not words:
        words = fallback
    allowed = set(words)
    return words, allowed


TARGET_WORDS, ALLOWED_GUESSES = _load_dictionary()


class PlayerState:
    def __init__(self, name: str):
        self.name = name
        self.guesses: List[Dict] = []  # list of {"word": str, "result": [status]}
        self.solved: bool = False


class WordleServer:
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
        target_word: Optional[str] = None,
        max_attempts: int = 6,
    ):
        self.port = port
        self.room = room
        self.token = token
        self.players_order = [p1, p2]
        self.states: Dict[str, PlayerState] = {p1: PlayerState(p1), p2: PlayerState(p2)}
        self.connections: Dict[str, socket.socket] = {}
        self.spectators: Dict[str, socket.socket] = {}
        self.report_host = report_host
        self.report_port = report_port
        self.report_token = report_token or token
        self.max_attempts = max_attempts
        self.target_word = (target_word or random.choice(TARGET_WORDS)).lower()
        self.running = True
        self.winner: Optional[str] = None
        self.listener: Optional[socket.socket] = None
        self.lock = threading.Lock()

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self.port))
        listener.listen(2)
        listener.settimeout(1.0)
        self.listener = listener
        print(f"[server] Wordle listening on 0.0.0.0:{self.port} room={self.room}")

        try:
            while len(self.connections) < 2:
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                self.handle_handshake(conn, addr, allow_players=True)

            # Start watcher threads
            for pname in self.players_order:
                threading.Thread(target=self.player_thread, args=(pname,), daemon=True).start()
            threading.Thread(target=self.accept_spectators, args=(listener,), daemon=True).start()
            threading.Thread(target=self._heartbeat, daemon=True).start()

            # Send initial state
            self.broadcast_state()

            # Main wait loop; threads drive the gameplay.
            while self.running:
                time.sleep(0.2)
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

    def handle_handshake(self, conn: socket.socket, addr, allow_players: bool):
        try:
            conn.settimeout(120)
        except Exception:
            pass
        hello = recv_json(conn)
        if not hello or hello.get("token") != self.token:
            conn.close()
            return
        role = hello.get("role", "player").lower()
        pname = hello.get("player")
        if role == "spectator":
            sid = pname or f"spec-{addr[0]}:{addr[1]}"
            if sid in self.spectators:
                conn.close()
                return
            self.spectators[sid] = conn
            send_json(conn, {"type": "ok", "role": "spectator", "room": self.room})
            self.send_spectator_state(conn)
            print(f"[server] spectator {sid} connected from {addr}")
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
        try:
            conn.settimeout(None)
        except Exception:
            pass
        send_json(conn, {"type": "ok", "role": "player", "room": self.room, "you": pname})
        print(f"[server] player {pname} connected from {addr}")

    def accept_spectators(self, listener: socket.socket):
        while self.running:
            try:
                conn, addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle_handshake(conn, addr, allow_players=False)

    def player_thread(self, pname: str):
        conn = self.connections[pname]
        try:
            conn.settimeout(120)
        except Exception:
            pass
        try:
            while self.running:
                try:
                    msg = recv_json(conn)
                except socket.timeout:
                    print(f"[server] {pname} timed out")
                    self.finish_game(winner=self.other_player(pname), loser=pname, reason="timeout")
                    return
                if not msg:
                    print(f"[server] {pname} disconnected")
                    self.finish_game(winner=self.other_player(pname), loser=pname, reason="disconnect")
                    return
                mtype = msg.get("type")
                if mtype == "guess":
                    word = str(msg.get("word", "")).strip().lower()
                    self.handle_guess(pname, word)
                elif mtype in ("surrender", "quit"):
                    self.finish_game(winner=self.other_player(pname), loser=pname, reason="surrender")
                    return
                else:
                    send_json(conn, {"type": "error", "message": "unknown command"})
        except Exception as exc:
            print(f"[server] error in player thread {pname}: {exc}")
            self.finish_game(winner=self.other_player(pname), loser=pname, reason="error")

    def handle_guess(self, pname: str, word: str):
        if not word.isalpha() or len(word) != len(self.target_word):
            send_json(self.connections[pname], {"type": "error", "message": f"word must be {len(self.target_word)} letters"})
            return
        if word not in ALLOWED_GUESSES and word not in TARGET_WORDS:
            send_json(self.connections[pname], {"type": "error", "message": "word not in allowed list"})
            return
        with self.lock:
            state = self.states[pname]
            if state.solved or len(state.guesses) >= self.max_attempts or not self.running:
                return
            result = self.evaluate(word)
            state.guesses.append({"word": word, "result": result})
            if word == self.target_word:
                state.solved = True
                self.finish_game(winner=pname, loser=self.other_player(pname), reason="solved")
            else:
                self.broadcast_state()
                self._maybe_finish_on_attempts()

    def _maybe_finish_on_attempts(self):
        if self.winner or not self.running:
            return
        all_spent = all(len(s.guesses) >= self.max_attempts or s.solved for s in self.states.values())
        if not all_spent:
            return
        winner = self.progress_winner()
        loser = self.other_player(winner) if winner else None
        self.finish_game(winner=winner, loser=loser, reason="attempts_exhausted")

    def evaluate(self, guess: str) -> List[str]:
        target = list(self.target_word)
        result = ["absent"] * len(target)
        # First pass: correct positions
        for idx, ch in enumerate(guess):
            if ch == target[idx]:
                result[idx] = "correct"
                target[idx] = None  # mark consumed
        # Second pass: present letters
        for idx, ch in enumerate(guess):
            if result[idx] == "correct":
                continue
            if ch in target:
                result[idx] = "present"
                target[target.index(ch)] = None
        return result

    def progress_winner(self) -> Optional[str]:
        def score(ps: PlayerState) -> Tuple[int, int, int]:
            best_green = 0
            best_yellow = 0
            for g in ps.guesses:
                greens = g["result"].count("correct")
                yellows = g["result"].count("present")
                if greens > best_green or (greens == best_green and yellows > best_yellow):
                    best_green, best_yellow = greens, yellows
            attempts_used = len(ps.guesses)
            return (best_green, best_yellow, -attempts_used)

        p1, p2 = self.players_order
        s1, s2 = self.states[p1], self.states[p2]
        if s1.solved and not s2.solved:
            return p1
        if s2.solved and not s1.solved:
            return p2
        if s1.solved and s2.solved:
            # Both solved after exhausting attempts; earlier solver wins by guess count.
            if len(s1.guesses) == len(s2.guesses):
                return p1
            return p1 if len(s1.guesses) < len(s2.guesses) else p2
        score1 = score(s1)
        score2 = score(s2)
        if score1 == score2:
            return p1  # deterministic tie-breaker
        return p1 if score1 > score2 else p2

    def broadcast_state(self):
        for pname, conn in list(self.connections.items()):
            opp = self.other_player(pname)
            ok = send_json(
                conn,
                {
                    "type": "state",
                    "you": pname,
                    "room": self.room,
                    "target_length": len(self.target_word),
                    "max_attempts": self.max_attempts,
                    "guesses": self.states[pname].guesses,
                    "attempts_left": max(0, self.max_attempts - len(self.states[pname].guesses)),
                    "solved": self.states[pname].solved,
                    "opponent": {
                        "name": opp,
                        "guesses": len(self.states[opp].guesses),
                        "solved": self.states[opp].solved,
                        "attempts_left": max(0, self.max_attempts - len(self.states[opp].guesses)),
                    },
                },
            )
            if not ok:
                self.finish_game(winner=self.other_player(pname), loser=pname, reason="disconnect")
        if self.spectators:
            payload = {
                "type": "state",
                "room": self.room,
                "target_length": len(self.target_word),
                "max_attempts": self.max_attempts,
                "players": {
                    p: {
                        "guesses": len(st.guesses),
                        "solved": st.solved,
                        "attempts_left": max(0, self.max_attempts - len(st.guesses)),
                    }
                    for p, st in self.states.items()
                },
            }
            for sid, conn in list(self.spectators.items()):
                if not send_json(conn, payload):
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self.spectators.pop(sid, None)

    def send_spectator_state(self, conn: socket.socket):
        send_json(
            conn,
            {
                "type": "state",
                "room": self.room,
                "target_length": len(self.target_word),
                "max_attempts": self.max_attempts,
                "players": {
                    p: {
                        "guesses": len(st.guesses),
                        "solved": st.solved,
                        "attempts_left": max(0, self.max_attempts - len(st.guesses)),
                    }
                    for p, st in self.states.items()
                },
            },
        )

    def finish_game(self, winner: Optional[str], loser: Optional[str], reason: str):
        with self.lock:
            if not self.running:
                return
            self.running = False
            self.winner = winner
        for conn in list(self.connections.values()):
            send_json(conn, {"type": "game_over", "winner": winner, "loser": loser, "reason": reason})
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
        for conn in list(self.spectators.values()):
            send_json(conn, {"type": "game_over", "winner": winner, "loser": loser, "reason": reason})
            try:
                conn.close()
            except Exception:
                pass
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
            "game": "Wordle",
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
        payload["attempts"] = {p: len(st.guesses) for p, st in self.states.items()}
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
        for p in self.players_order:
            if p != pname:
                return p
        return None


def main():
    parser = argparse.ArgumentParser(description="Wordle duel game server.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--p1", required=True)
    parser.add_argument("--p2", required=True)
    parser.add_argument("--report_host", help="optional host to report game results to")
    parser.add_argument("--report_port", type=int, help="optional port to report game results to")
    parser.add_argument("--report_token", help="token to authenticate reports", default="")
    parser.add_argument("--word", help="optional fixed target word (for testing)")
    args = parser.parse_args()

    srv = WordleServer(
        port=args.port,
        room=args.room,
        token=args.token,
        p1=args.p1,
        p2=args.p2,
        report_host=args.report_host,
        report_port=args.report_port,
        report_token=args.report_token or args.token,
        target_word=args.word,
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
