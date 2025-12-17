import argparse
import json
import socket
import sys
import os
import logging
from pathlib import Path
from typing import Optional

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
