import argparse
import json
import socket
import sys
import os
import logging
import select
from pathlib import Path
from typing import Optional, Dict

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


_configure_logging("game_rps_client.log")
logger = logging.getLogger(__name__)
CHOICES = {"rock", "paper", "scissors"}


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


def print_rules(text: str | None = None):
    print("\n=== How to Play ===")
    print("- Submit one of: rock, paper, scissors.")
    print("- First valid round decides winner; tie breaks to player 1.")
    print("- Type 'surrender' to forfeit.")
    if text:
        print(text)


def print_state(state: Dict):
    you = state.get("you")
    your_move = state.get("your_move")
    opp = (state.get("opponent") or {}).get("name")
    opp_sub = (state.get("opponent") or {}).get("submitted")
    print("\n=== RPS State ===")
    print(f"You: {you}, move: {your_move or 'PENDING'}")
    print(f"Opponent {opp}: submitted={bool(opp_sub)}")


def print_prompt() -> None:
    sys.stdout.write("Enter your move (rock/paper/scissors) or 'surrender': ")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Rock-Paper-Scissors client.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--room_id", type=int, default=int(os.getenv("ROOM_ID", "0") or 0))
    parser.add_argument("--match_id", default=os.getenv("MATCH_ID", ""))
    parser.add_argument("--client_token", default=os.getenv("CLIENT_TOKEN", ""))
    parser.add_argument("--client_protocol_version", type=int, default=int(os.getenv("CLIENT_PROTOCOL_VERSION", "1") or 1))
    parser.add_argument("--spectator", action="store_true", help="connect without submitting a move")
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
    hello = {
        "room_id": room_id,
        "match_id": match_id,
        "player_name": args.player,
        "client_token": client_token,
        "client_protocol_version": args.client_protocol_version,
    }
    if not send_json(conn, hello):
        print("Failed to send handshake.")
        return
    resp = recv_json(conn)
    if not resp or not resp.get("ok"):
        print(f"Handshake rejected: {resp.get('reason') if resp else 'no response'}")
        return
    print("Connected. Waiting for updates...")

    have_printed_rules = False
    can_play = False
    try:
        while True:
            watch = [conn]
            if can_play and not args.spectator:
                watch.append(sys.stdin)
            readable, _, _ = select.select(watch, [], [])
            if conn in readable:
                msg = recv_json(conn)
                if not msg:
                    print("Disconnected from server.")
                    return
                mtype = msg.get("type")
                if mtype == "rules":
                    print_rules(msg.get("text"))
                    have_printed_rules = True
                elif mtype == "state":
                    print_state(msg)
                    if not args.spectator and msg.get("your_move") is None:
                        can_play = True
                        print_prompt()
                    else:
                        can_play = False
                elif mtype == "error":
                    print(f"Error: {msg.get('message')}")
                elif mtype == "game_over":
                    winner = msg.get("winner")
                    reason = msg.get("reason")
                    if winner:
                        print(f"Game over. Winner: {winner} (reason: {reason})")
                    else:
                        print(f"Game over. Reason: {reason}")
                    return
            if sys.stdin in readable:
                raw = sys.stdin.readline()
                if not raw:
                    continue
                raw = raw.strip().lower()
                if raw == "surrender":
                    move = {"type": "surrender"}
                else:
                    if raw not in CHOICES:
                        print("Error: move must be rock, paper, or scissors")
                        if can_play:
                            print_prompt()
                        continue
                    move = {"type": "move", "move": raw}
                if not send_json(conn, move):
                    print("Failed to send move.")
                    return
                can_play = False
    except KeyboardInterrupt:
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
