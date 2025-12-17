import argparse
import json
import random
import socket
import sys
import threading
import time
import os
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

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


_configure_logging("game_wordle_server.log")
logger = logging.getLogger(__name__)

MAX_LINE_BYTES = 64 * 1024

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def send_json(conn: socket.socket, obj: Dict):
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
            if len(buf) >= MAX_LINE_BYTES:
                logger.warning("received line exceeds max (%d bytes); discarding", MAX_LINE_BYTES)
                return None
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


DEFAULT_TARGETS = [
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
    "cider",
    "pride",
    "stare",
    "stark",
    "blaze",
    "trick",
    "spice",
    "grace",
    "brink",
    "sound",
    "trace",
    "swift",
]


def _load_dictionary_words() -> List[str]:
    """
    Try to load a larger 5-letter word list from assets/words.txt or system dictionaries.
    Falls back to the bundled defaults if nothing is found.
    """
    candidates: set[str] = set()
    assets_path = Path(__file__).parent / "assets" / "words.txt"
    system_dicts = [
        Path("/usr/share/dict/words"),
        Path("/usr/share/dict/american-english"),
        Path("/usr/share/dict/british-english"),
    ]

    def load_from_path(path: Path) -> List[str]:
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                return [line.strip().lower() for line in f if line.strip()]
        except Exception:
            return []

    # Prefer bundled assets if present.
    for word in load_from_path(assets_path):
        if len(word) == 5 and word.isalpha():
            candidates.add(word.lower())

    # Fall back to system dictionaries.
    if not candidates:
        for sys_path in system_dicts:
            for word in load_from_path(sys_path):
                if len(word) == 5 and word.isalpha():
                    candidates.add(word.lower())
            if candidates:
                break

    # Final fallback to defaults.
    if not candidates:
        candidates.update(DEFAULT_TARGETS)
    return sorted(candidates)


_ALL_WORDS = _load_dictionary_words()
# Use the loaded words as both targets and allowed guesses to keep the rules consistent.
TARGET_WORDS = list(_ALL_WORDS)
ALLOWED_GUESSES = set(_ALL_WORDS)


class WordleServer:
    def __init__(
        self,
        port: int,
        room_id: str,
        client_token: str,
        match_id: str,
        p1: str,
        p2: str,
        bind_host: str = "0.0.0.0",
        report_host: Optional[str] = None,
        report_port: Optional[int] = None,
        report_token: str = "",
        target_word: Optional[str] = None,
        max_attempts: int = 6,
    ):
        self.port = port
        self.room_id = int(room_id)
        self.room = str(room_id)
        self.client_token = client_token
        self.match_id = match_id
        self.bind_host = bind_host
        self.players_order = [p1, p2]
        self.guesses: List[Dict] = []
        self.current_turn_idx = 0
        self.solved = False
        self.connections: Dict[str, socket.socket] = {}
        self.spectators: Dict[str, socket.socket] = {}
        self.report_host = report_host
        self.report_port = report_port
        self.report_token = report_token
        self.max_attempts = max_attempts
        self.target_word = (target_word or random.choice(TARGET_WORDS)).lower()
        self.running = True
        self.winner: Optional[str] = None
        self.listener: Optional[socket.socket] = None
        self.lock = threading.Lock()
        self.handshake_timeout_sec = _env_float("WORDLE_HANDSHAKE_TIMEOUT_SEC", 10.0)
        self.wait_for_players_sec = _env_float("WORDLE_WAIT_FOR_PLAYERS_SEC", 60.0)
        self.game_timeout_sec = _env_float("WORDLE_GAME_TIMEOUT_SEC", 300.0)
        self.started_at: Optional[float] = None

    def _rules_payload(self) -> dict:
        payload = {
            "type": "rules",
            "target_length": len(self.target_word),
            "max_attempts": self.max_attempts,
            "text": (
                f"Take turns guessing the shared {len(self.target_word)}-letter word. "
                f"Each guess returns: G = correct letter/place, Y = letter in word wrong place, . = absent. "
                f"Only the current player may guess while the other waits. "
                f"You have {self.max_attempts} total attempts; the first correct guess wins."
            ),
        }
        if self.game_timeout_sec > 0:
            payload["time_limit_sec"] = int(self.game_timeout_sec)
            payload["text"] += f" Time limit: {int(self.game_timeout_sec)} seconds."
        return payload

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
        print(f"[server] Wordle listening on {self.bind_host}:{self.port} room={self.room}")
        self._report_status("STARTED")

        try:
            wait_deadline = None
            if self.wait_for_players_sec > 0:
                wait_deadline = time.time() + self.wait_for_players_sec
            threading.Thread(target=self._heartbeat, daemon=True).start()
            listener.settimeout(1.0)
            while self.running and len(self.connections) < 2:
                if wait_deadline and time.time() >= wait_deadline:
                    self.finish_game(winner=None, loser=None, reason="player_timeout")
                    break
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                self.handle_handshake(conn, addr, allow_players=True)

            if not self.running or len(self.connections) < 2:
                return

            # Start watcher threads
            for pname in self.players_order:
                threading.Thread(target=self.player_thread, args=(pname,), daemon=True).start()
            threading.Thread(target=self.accept_spectators, args=(listener,), daemon=True).start()
            self.started_at = time.time()
            threading.Thread(target=self._watchdog, daemon=True).start()

            # Share rules once the game begins.
            self.broadcast_rules()

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
            conn.settimeout(self.handshake_timeout_sec)
        except Exception:
            pass
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
        role = (hello.get("role") or "player").lower()
        pname = hello.get("player_name")
        if not pname:
            send_json(conn, {"ok": False, "reason": "player_name required"})
            conn.close()
            return
        if role == "spectator":
            sid = pname
            if sid in self.spectators:
                send_json(conn, {"ok": False, "reason": "spectator already connected"})
                conn.close()
                return
            self.spectators[sid] = conn
            send_json(conn, {"ok": True, "game_protocol_version": 1})
            self.send_spectator_state(conn)
            print(f"[server] spectator {sid} connected from {addr}")
            try:
                conn.settimeout(None)
            except Exception:
                pass
            return
        if not allow_players:
            send_json(conn, {"ok": False, "reason": "spectators only"})
            conn.close()
            return
        if pname not in self.players_order or pname in self.connections:
            send_json(conn, {"ok": False, "reason": "bad player"})
            conn.close()
            return
        self.connections[pname] = conn
        send_json(conn, {"ok": True, "assigned_player_index": self.players_order.index(pname), "game_protocol_version": 1})
        print(f"[server] player {pname} connected from {addr}")
        try:
            conn.settimeout(None)
        except Exception:
            pass

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
            while self.running:
                msg = recv_json(conn)
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
        # Accept any alphabetic word with the correct length to keep play smooth across dictionaries.
        if not word.isalpha() or len(word) != len(self.target_word):
            send_json(self.connections[pname], {"type": "error", "message": f"word must be {len(self.target_word)} letters"})
            state_payload = self._player_state_payload(pname)
            send_json(self.connections[pname], state_payload)
            return
        winner = None
        loser = None
        reason = None
        broadcast = False
        with self.lock:
            if not self.running or self.solved:
                return
            current_player = self.players_order[self.current_turn_idx]
            if pname != current_player:
                send_json(self.connections[pname], {"type": "error", "message": "not your turn"})
                state_payload = self._player_state_payload(pname)
                send_json(self.connections[pname], state_payload)
                return
            if len(self.guesses) >= self.max_attempts:
                send_json(self.connections[pname], {"type": "error", "message": "no attempts left"})
                return
            result = self.evaluate(word)
            self.guesses.append({"word": word, "result": result, "player": pname})
            if word == self.target_word:
                self.solved = True
                winner = pname
                loser = self.other_player(pname)
                reason = "solved"
            elif len(self.guesses) >= self.max_attempts:
                reason = "attempts_exhausted"
            else:
                self.current_turn_idx = 1 - self.current_turn_idx
                broadcast = True
        if reason == "attempts_exhausted":
            self.finish_game(winner=None, loser=None, reason=reason)
            return
        if winner:
            self.finish_game(winner=winner, loser=loser, reason=reason or "solved")
            return
        if broadcast:
            self.broadcast_state()

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

    def _attempts_by_player(self) -> Dict[str, int]:
        counts = Counter()
        for guess in self.guesses:
            player = guess.get("player")
            if player:
                counts[player] += 1
        return {p: counts.get(p, 0) for p in self.players_order}

    def broadcast_state(self):
        current_player = self.players_order[self.current_turn_idx]
        attempts_left = max(0, self.max_attempts - len(self.guesses))
        for pname, conn in list(self.connections.items()):
            opp = self.other_player(pname)
            send_json(
                conn,
                {
                    "type": "state",
                    "you": pname,
                    "room": self.room,
                    "target_length": len(self.target_word),
                    "max_attempts": self.max_attempts,
                    "guesses": list(self.guesses),
                    "attempts_left": attempts_left,
                    "solved": self.solved,
                    "current_player": current_player,
                    "your_turn": pname == current_player,
                    "opponent": {"name": opp},
                },
            )
        if self.spectators:
            payload = {
                "type": "state",
                "room": self.room,
                "target_length": len(self.target_word),
                "max_attempts": self.max_attempts,
                "guesses": list(self.guesses),
                "attempts_left": attempts_left,
                "current_player": current_player,
                "players": list(self.players_order),
            }
            for conn in list(self.spectators.values()):
                send_json(conn, payload)

    def _player_state_payload(self, pname: str) -> dict:
        opp = self.other_player(pname)
        current_player = self.players_order[self.current_turn_idx]
        attempts_left = max(0, self.max_attempts - len(self.guesses))
        return {
            "type": "state",
            "you": pname,
            "room": self.room,
            "target_length": len(self.target_word),
            "max_attempts": self.max_attempts,
            "guesses": list(self.guesses),
            "attempts_left": attempts_left,
            "solved": self.solved,
            "current_player": current_player,
            "your_turn": pname == current_player,
            "opponent": {"name": opp},
        }

    def send_spectator_state(self, conn: socket.socket):
        current_player = self.players_order[self.current_turn_idx]
        attempts_left = max(0, self.max_attempts - len(self.guesses))
        send_json(
            conn,
            {
                "type": "state",
                "room": self.room,
                "target_length": len(self.target_word),
                "max_attempts": self.max_attempts,
                "guesses": list(self.guesses),
                "attempts_left": attempts_left,
                "current_player": current_player,
                "players": list(self.players_order),
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
        for conn in list(self.spectators.values()):
            send_json(conn, {"type": "game_over", "winner": winner, "loser": loser, "reason": reason})
        print(f"[server] game over winner={winner} loser={loser} reason={reason}")
        results = []
        if winner:
            results.append({"player": winner, "outcome": "WIN", "rank": 1, "score": None})
        if loser:
            results.append({"player": loser, "outcome": "LOSE", "rank": 2, "score": None})
        if not results:
            for pname in self.players_order:
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
        results: Optional[List[Dict]] = None,
    ):
        if not self.report_host or not self.report_port:
            return
        payload = {
            "type": "GAME.REPORT",
            "status": status,
            "game": "Wordle",
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
        payload["attempts"] = self._attempts_by_player()
        try:
            with socket.create_connection((self.report_host, self.report_port), timeout=3) as conn:
                send_json(conn, payload)
        except Exception as exc:
            logger.warning("failed to report result: %s", exc)

    def _heartbeat(self):
        while self.running:
            self._report_status("HEARTBEAT", reason="heartbeat")
            time.sleep(10)

    def _watchdog(self):
        while self.running:
            if self.started_at and self.game_timeout_sec > 0:
                if time.time() - self.started_at >= self.game_timeout_sec:
                    self.finish_game(winner=None, loser=None, reason="timeout")
                    return
            time.sleep(0.5)

    def other_player(self, pname: str) -> Optional[str]:
        for p in self.players_order:
            if p != pname:
                return p
        return None


def main():
    parser = argparse.ArgumentParser(description="Wordle duel game server.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--p1", required=True)
    parser.add_argument("--p2", required=True)
    parser.add_argument("--bind_host", default=os.getenv("BIND_HOST", "0.0.0.0"))
    parser.add_argument("--match_id", default=os.getenv("MATCH_ID", ""))
    parser.add_argument("--client_token", default="")
    parser.add_argument("--report_token", default="")
    parser.add_argument("--client_token_path", default="")
    parser.add_argument("--report_token_path", default="")
    parser.add_argument("--report_host", help="optional host to report game results to")
    parser.add_argument("--report_port", type=int, help="optional port to report game results to")
    parser.add_argument("--word", help="optional fixed target word (for testing)")
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
        sys.exit(2)

    srv = WordleServer(
        port=args.port,
        room_id=args.room,
        client_token=client_token,
        match_id=match_id,
        p1=args.p1,
        p2=args.p2,
        bind_host=args.bind_host,
        report_host=args.report_host,
        report_port=args.report_port,
        report_token=report_token,
        target_word=args.word,
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
