import argparse
import json
import random
import socket
import sys
import threading
import time
import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

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


_configure_logging("game_bigtwo_server.log")
logger = logging.getLogger(__name__)


# ---------------- Cards and combos ---------------- #
SUITS = ["C", "D", "H", "S"]  # ascending; S is highest like the C++ version
SUIT_VALUE = {"C": 1, "D": 2, "H": 3, "S": 4}
RANKS = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]  # 3..A,2 (2 highest)
RANK_STR = {11: "J", 12: "Q", 13: "K", 14: "A", 15: "2"}
RANK_VAL = {str(r): r for r in range(3, 11)} | {"J": 11, "Q": 12, "K": 13, "A": 14, "2": 15}


def card_label(rank: int, suit: str) -> str:
    r = RANK_STR.get(rank, str(rank))
    return f"{r}{suit}"


@dataclass(frozen=True)
class Card:
    rank: int
    suit: str  # one of SUITS

    def label(self) -> str:
        return card_label(self.rank, self.suit)

    def key(self) -> Tuple[int, int]:
        return (self.rank, SUITS.index(self.suit))


@dataclass
class Combo:
    kind: str  # single, pair, fullhouse, straight, fourofkind, straightflush
    cards: List[Card]
    weight: Tuple  # used for comparison within same kind/category ladder


def make_deck() -> List[Card]:
    return [Card(rank, suit) for rank in RANKS for suit in SUITS]


def parse_cards(labels: List[str]) -> List[Card]:
    res = []
    for lab in labels:
        lab = lab.strip().upper()
        if len(lab) < 2:
            raise ValueError(f"bad card {lab}")
        suit = lab[-1]
        rank_str = lab[:-1]
        if suit not in SUITS:
            raise ValueError(f"bad suit {lab}")
        if rank_str not in RANK_VAL:
            raise ValueError(f"bad rank {lab}")
        res.append(Card(RANK_VAL[rank_str], suit))
    return res


def normalize_hand(cards: List[Card]) -> List[Card]:
    return sorted(cards, key=lambda c: (c.rank, SUIT_VALUE[c.suit]))


COMBO_ORDER = {
    "single": 1,
    "pair": 2,
    "fullhouse": 3,
    "straight": 4,
    "fourofkind": 5,
    "straightflush": 6,
}


def classify_combo(cards: List[Card]) -> Optional[Combo]:
    sorted_cards = normalize_hand(cards)
    if len(sorted_cards) == 1:
        c = sorted_cards[0]
        return Combo("single", sorted_cards, (c.rank, SUIT_VALUE[c.suit]))
    if len(sorted_cards) == 2 and sorted_cards[0].rank == sorted_cards[1].rank:
        top = max(sorted_cards, key=lambda c: SUIT_VALUE[c.suit])
        return Combo("pair", sorted_cards, (top.rank, SUIT_VALUE[top.suit]))
    if len(sorted_cards) != 5:
        return None

    counts: Dict[int, int] = {}
    for c in sorted_cards:
        counts[c.rank] = counts.get(c.rank, 0) + 1

    is_fullhouse = sorted(counts.values()) == [2, 3]
    four_rank = next((r for r, cnt in counts.items() if cnt == 4), None)
    straight = all(sorted_cards[i].rank + 1 == sorted_cards[i + 1].rank for i in range(4))
    same_suit = len({c.suit for c in sorted_cards}) == 1

    if is_fullhouse:
        triple_rank = max(counts, key=lambda r: counts[r])
        dom = max([c for c in sorted_cards if c.rank == triple_rank], key=lambda c: SUIT_VALUE[c.suit])
        return Combo("fullhouse", sorted_cards, (dom.rank, SUIT_VALUE[dom.suit]))
    if four_rank is not None:
        dom = max([c for c in sorted_cards if c.rank == four_rank], key=lambda c: SUIT_VALUE[c.suit])
        return Combo("fourofkind", sorted_cards, (dom.rank, SUIT_VALUE[dom.suit]))
    if straight:
        dom = sorted_cards[-1]
        if same_suit:
            return Combo("straightflush", sorted_cards, (dom.rank, SUIT_VALUE[dom.suit]))
        return Combo("straight", sorted_cards, (dom.rank, SUIT_VALUE[dom.suit]))
    return None


def beats(candidate: Combo, current: Combo) -> bool:
    c_mode = COMBO_ORDER[candidate.kind]
    cur_mode = COMBO_ORDER[current.kind]
    if c_mode > 4:
        return c_mode > cur_mode
    if c_mode != cur_mode:
        return False
    return candidate.weight > current.weight


# ---------------- Networking helpers ---------------- #
def send_json(conn: socket.socket, obj: Dict):
    data = json.dumps(obj).encode("utf-8") + b"\n"
    try:
        conn.sendall(data)
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
            return open(path, "r", encoding="utf-8").read().strip()
        except Exception:
            return ""
    return ""


# ---------------- Game server ---------------- #
class BigTwoServer:
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
    ):
        self.port = port
        self.room_id = int(room_id)
        self.room = str(room_id)
        self.client_token = client_token
        self.match_id = match_id
        self.bind_host = bind_host
        self.players = [p1, p2]
        self.hands: Dict[str, List[Card]] = {}
        self.connections: Dict[str, socket.socket] = {}
        self.spectators: Dict[str, socket.socket] = {}
        self.current_combo: Optional[Combo] = None
        self.last_player: Optional[str] = None
        self.first_turn = True
        self.report_host = report_host
        self.report_port = report_port
        self.running = True
        self.report_token = report_token

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.bind_host, self.port))
        listener.listen(2)
        print(f"[server] BigTwo listening on {self.bind_host}:{self.port} room={self.room}")
        self._report_status("STARTED")

        try:
            listener.settimeout(1.0)
            while len(self.connections) < 2:
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                self.handle_handshake(conn, addr, allow_players=True)

            # Heartbeat reporting
            threading.Thread(target=self._heartbeat, daemon=True).start()

            # Allow spectators after match starts
            threading.Thread(target=self.accept_spectators, args=(listener,), daemon=True).start()

            self.deal()
            start_player = self.find_start_player()
            turn_idx = self.players.index(start_player)
            passes = 0  # retained for readability; pass clears field immediately

            while True:
                current_player = self.players[turn_idx]
                hand = self.hands[current_player]
                send_json(self.connections[current_player], self.state_msg(current_player, your_turn=True))
                # prompt loop
                while True:
                    msg = recv_json(self.connections[current_player])
                    if not msg:
                        print(f"[server] {current_player} disconnected")
                        winner = [p for p in self.players if p != current_player][0]
                        self.finish_game(winner, reason="disconnect")
                        return
                    if msg.get("type") == "play":
                        try:
                            played_cards = parse_cards(msg.get("cards", []))
                        except ValueError as e:
                            send_json(self.connections[current_player], {"type": "error", "message": str(e)})
                            continue
                        if not self.contains_cards(hand, played_cards):
                            send_json(self.connections[current_player], {"type": "error", "message": "cards not in hand"})
                            continue
                        combo = classify_combo(played_cards)
                        if not combo:
                            send_json(self.connections[current_player], {"type": "error", "message": "invalid combo"})
                            continue
                        if self.current_combo:
                            if len(combo.cards) != len(self.current_combo.cards):
                                send_json(self.connections[current_player], {"type": "error", "message": "must match card count"})
                                continue
                            if not beats(combo, self.current_combo):
                                send_json(self.connections[current_player], {"type": "error", "message": "does not beat current combo"})
                                # keep current turn alive; prompt again
                                continue
                        # valid play
                        self.remove_cards(hand, played_cards)
                        self.current_combo = combo
                        self.last_player = current_player
                        self.first_turn = False
                        passes = 0
                        break
                    elif msg.get("type") == "pass":
                        self.current_combo = None
                        self.last_player = None
                        passes = 0
                        self.first_turn = False
                        break
                    elif msg.get("type") == "surrender":
                        winner = [p for p in self.players if p != current_player][0]
                        self.finish_game(winner, reason="surrender")
                        return
                    else:
                        send_json(self.connections[current_player], {"type": "error", "message": "unknown command"})

                # broadcast update
                next_idx = (turn_idx + 1) % len(self.players)
                self.broadcast_state(next_player=self.players[next_idx])

                # win check
                if len(hand) == 0:
                    self.finish_game(current_player)
                    return

                turn_idx = next_idx
        except Exception as exc:
            self.running = False
            self._report_status("ERROR", err_msg=str(exc))
            raise

    def handle_handshake(self, conn: socket.socket, addr, allow_players: bool):
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
            print(f"[server] spectator {sid} connected from {addr}")
            return
        if not allow_players:
            send_json(conn, {"ok": False, "reason": "spectators only"})
            conn.close()
            return
        if pname not in self.players or pname in self.connections:
            send_json(conn, {"ok": False, "reason": "bad player"})
            conn.close()
            return
        self.connections[pname] = conn
        send_json(conn, {"ok": True, "assigned_player_index": self.players.index(pname), "game_protocol_version": 1})
        print(f"[server] {pname} connected from {addr}")

    def accept_spectators(self, listener: socket.socket):
        while True:
            try:
                conn, addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle_handshake(conn, addr, allow_players=False)

    def deal(self):
        deck = make_deck()
        random.shuffle(deck)
        for idx, pname in enumerate(self.players):
            self.hands[pname] = sorted(deck[idx * 13 : (idx + 1) * 13], key=lambda c: c.key())

    def find_start_player(self) -> str:
        for pname in self.players:
            if any(c.rank == 3 and c.suit == "C" for c in self.hands[pname]):
                return pname
        return self.players[0]

    def contains_cards(self, hand: List[Card], subset: List[Card]) -> bool:
        hand_counts: Dict[Tuple[int, str], int] = {}
        for c in hand:
            hand_counts[(c.rank, c.suit)] = hand_counts.get((c.rank, c.suit), 0) + 1
        for c in subset:
            key = (c.rank, c.suit)
            if hand_counts.get(key, 0) <= 0:
                return False
            hand_counts[key] -= 1
        return True

    def remove_cards(self, hand: List[Card], subset: List[Card]):
        for c in subset:
            for i, hc in enumerate(hand):
                if hc.rank == c.rank and hc.suit == c.suit:
                    hand.pop(i)
                    break

    def combo_repr(self, combo: Optional[Combo]) -> Optional[Dict]:
        if not combo:
            return None
        return {"kind": combo.kind, "cards": [c.label() for c in combo.cards]}

    def state_msg(self, you: str, your_turn: bool) -> Dict:
        return {
            "type": "state",
            "you": you,
            "your_turn": your_turn,
            "hand": [c.label() for c in self.hands[you]],
            "hand_counts": {p: len(self.hands[p]) for p in self.players},
            "last_combo": self.combo_repr(self.current_combo),
            "last_player": self.last_player,
            "first_turn": self.first_turn,
        }

    def broadcast_state(self, next_player: Optional[str] = None):
        for p in self.players:
            if p in self.connections:
                send_json(self.connections[p], self.state_msg(p, your_turn=(next_player == p)))
        if self.spectators:
            payload = {
                "type": "state",
                "room": self.room,
                "hand_counts": {p: len(self.hands[p]) for p in self.players},
                "last_combo": self.combo_repr(self.current_combo),
                "last_player": self.last_player,
                "next_player": next_player,
            }
            for conn in list(self.spectators.values()):
                send_json(conn, payload)

    def finish_game(self, winner: str, reason: str = "normal"):
        for p in self.players:
            if p in self.connections:
                send_json(self.connections[p], {"type": "game_over", "winner": winner, "reason": reason})
        for conn in list(self.spectators.values()):
            send_json(conn, {"type": "game_over", "winner": winner, "reason": reason})
        print(f"[server] game over, winner={winner}, reason={reason}")
        self.running = False
        loser = next((p for p in self.players if p != winner), "")
        results = []
        if winner:
            results.append({"player": winner, "outcome": "WIN", "rank": 1, "score": None})
        if loser:
            results.append({"player": loser, "outcome": "LOSE", "rank": 2, "score": None})
        if not results:
            for pname in self.players:
                results.append({"player": pname, "outcome": "DRAW", "rank": None, "score": None})
        self._report_status("END", winner=winner, loser=loser, err_msg=None, reason=reason, results=results)

    def _report_status(self, status: str, winner: Optional[str] = None, loser: Optional[str] = None,
                       err_msg: Optional[str] = None, reason: Optional[str] = None, results: Optional[List[Dict]] = None):
        if not self.report_host or not self.report_port:
            return
        payload = {
            "type": "GAME.REPORT",
            "status": status,
            "game": "BigTwo",
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
        payload["hand_counts"] = {p: len(self.hands.get(p, [])) for p in self.players}
        try:
            with socket.create_connection((self.report_host, self.report_port), timeout=3) as conn:
                send_json(conn, payload)
        except Exception as exc:
            logger.warning("failed to report result: %s", exc)

    def _heartbeat(self):
        while self.running:
            self._report_status("HEARTBEAT", reason="heartbeat")
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description="BigTwo room-local server (Python rewrite).")
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

    srv = BigTwoServer(
        args.port,
        args.room,
        client_token,
        match_id,
        args.p1,
        args.p2,
        bind_host=args.bind_host,
        report_token=report_token,
        report_host=args.report_host,
        report_port=args.report_port,
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
