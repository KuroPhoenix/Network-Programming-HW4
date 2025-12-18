import argparse
import json
import socket
import sys
import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from collections import Counter

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


_configure_logging("game_bigtwo_client.log")
logger = logging.getLogger(__name__)

SUITS = ["C", "D", "H", "S"]  # ascending; S highest
SUIT_VALUE = {"C": 1, "D": 2, "H": 3, "S": 4}
RANK_VAL = {str(r): r for r in range(3, 11)} | {"J": 11, "Q": 12, "K": 13, "A": 14, "2": 15}
RANK_STR = {11: "J", 12: "Q", 13: "K", 14: "A", 15: "2"}


@dataclass(frozen=True)
class Card:
    rank: int
    suit: str

    def label(self) -> str:
        return f"{RANK_STR.get(self.rank, str(self.rank))}{self.suit}"


@dataclass
class Combo:
    kind: str
    cards: list[Card]
    weight: tuple


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
            return open(path, "r", encoding="utf-8").read().strip()
        except Exception:
            return ""
    return ""


def prompt_play(hand, can_pass):
    print("Your hand:", " ".join(hand))
    if can_pass:
        print("Type card codes separated by spaces, or 'pass', or 'surrender'")
    else:
        print("Type card codes separated by spaces (must play), or 'surrender'")
    raw = input("> ").strip()
    if can_pass and raw.lower() == "pass":
        return {"type": "pass"}
    if raw.lower() == "surrender":
        return {"type": "surrender"}
    cards = raw.replace(",", " ").split()
    return {"type": "play", "cards": cards}


def parse_cards(labels: list[str]) -> list[Card]:
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


def normalize_hand(cards: list[Card]) -> list[Card]:
    return sorted(cards, key=lambda c: (c.rank, SUIT_VALUE[c.suit]))


def classify_combo(cards: list[Card]) -> Optional[Combo]:
    sorted_cards = normalize_hand(cards)
    if len(sorted_cards) == 1:
        c = sorted_cards[0]
        return Combo("single", sorted_cards, (c.rank, SUIT_VALUE[c.suit]))
    if len(sorted_cards) == 2 and sorted_cards[0].rank == sorted_cards[1].rank:
        top = max(sorted_cards, key=lambda c: SUIT_VALUE[c.suit])
        return Combo("pair", sorted_cards, (top.rank, SUIT_VALUE[top.suit]))
    if len(sorted_cards) != 5:
        return None

    counts: dict[int, int] = {}
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


COMBO_ORDER = {
    "single": 1,
    "pair": 2,
    "fullhouse": 3,
    "straight": 4,
    "fourofkind": 5,
    "straightflush": 6,
}


def beats(candidate: Combo, current: Combo) -> bool:
    c_mode = COMBO_ORDER[candidate.kind]
    cur_mode = COMBO_ORDER[current.kind]
    if c_mode > 4:
        return c_mode > cur_mode
    if c_mode != cur_mode:
        return False
    return candidate.weight > current.weight


def has_cards(hand: list[str], play: list[str]) -> bool:
    hand_counts = Counter(c.upper() for c in hand)
    play_counts = Counter(c.upper() for c in play)
    for card, cnt in play_counts.items():
        if hand_counts.get(card, 0) < cnt:
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description="BigTwo Python client.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--room_id", type=int, default=int(os.getenv("ROOM_ID", "0") or 0))
    parser.add_argument("--match_id", default=os.getenv("MATCH_ID", ""))
    parser.add_argument("--client_token", default=os.getenv("CLIENT_TOKEN", ""))
    parser.add_argument("--client_protocol_version", type=int, default=int(os.getenv("CLIENT_PROTOCOL_VERSION", "1") or 1))
    parser.add_argument("--spectator", action="store_true", help="connect as spectator")
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
    role = "spectator" if args.spectator else "player"
    hello = {
        "room_id": room_id,
        "match_id": match_id,
        "player_name": args.player,
        "client_token": client_token,
        "client_protocol_version": args.client_protocol_version,
        "role": role,
    }
    if not send_json(conn, hello):
        print("Failed to send handshake.")
        return
    resp = recv_json(conn)
    if not resp or not resp.get("ok"):
        print(f"Handshake rejected: {resp.get('reason') if resp else 'no response'}")
        return
    print("Connected. Waiting for game start...")

    try:
        while True:
            msg = recv_json(conn)
            if not msg:
                print("Disconnected from server.")
                return
            mtype = msg.get("type")
            if mtype == "state":
                if args.spectator and "hand" not in msg:
                    print("\n=== Spectator view ===")
                    for p, count in (msg.get("hand_counts") or {}).items():
                        print(f"{p}: {count} cards")
                    last_combo = msg.get("last_combo")
                    if last_combo:
                        print(f"On table: {last_combo.get('kind')} by {msg.get('last_player')}: {' '.join(last_combo.get('cards', []))}")
                    else:
                        print("On table: (empty)")
                    print(f"Next player: {msg.get('next_player')}")
                    continue

                your_turn = msg.get("your_turn", False)
                hand = msg.get("hand", [])
                last_combo = msg.get("last_combo")
                last_player = msg.get("last_player")
                print("\n=== Game State ===")
                for p, count in (msg.get("hand_counts") or {}).items():
                    print(f"{p}: {count} cards")
                if last_combo:
                    print(f"On table: {last_combo.get('kind')} by {last_player}: {' '.join(last_combo.get('cards', []))}")
                else:
                    print("On table: (empty)")
                if your_turn:
                    print(">> Your turn <<")
                    can_pass = True  # pass is always allowed in the C++ ruleset
                    while True:
                        play = prompt_play(hand, can_pass)
                        if play.get("type") == "play":
                            cards_raw = play.get("cards", [])
                            if not has_cards(hand, cards_raw):
                                print("Invalid move: cards not in hand")
                                continue
                            try:
                                play_cards = parse_cards(cards_raw)
                            except ValueError as e:
                                print(f"Invalid move: {e}")
                                continue
                            combo = classify_combo(play_cards)
                            if not combo:
                                print("Invalid move: invalid combo")
                                continue
                            if last_combo:
                                try:
                                    last_cards = parse_cards(last_combo.get("cards", []))
                                    last_combo_obj = classify_combo(last_cards)
                                except Exception:
                                    last_combo_obj = None
                                if last_combo_obj:
                                    if len(combo.cards) != len(last_combo_obj.cards):
                                        print("Invalid move: must match card count")
                                        continue
                                    if not beats(combo, last_combo_obj):
                                        print("Invalid move: does not beat current combo")
                                        continue
                        send_json(conn, play)
                        resp = recv_json(conn)
                        if not resp:
                            print("Disconnected.")
                            return
                        if resp.get("type") == "error":
                            print(f"Invalid move: {resp.get('message')}")
                            continue
                        # server will broadcast state; break the play loop
                        break
                else:
                    print("Waiting for opponent...")
            elif mtype == "error":
                print(f"Error: {msg.get('message')}")
            elif mtype == "game_over":
                print(f"Game over. Winner: {msg.get('winner')} (reason: {msg.get('reason')})")
                return
            else:
                # ignore unknown
                pass
    except KeyboardInterrupt:
        if not args.spectator:
            try:
                send_json(conn, {"type": "surrender"})
            except Exception:
                pass
        print("\nExiting game...")
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    main()
