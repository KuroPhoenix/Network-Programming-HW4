import argparse
import json
import socket
import sys
import os
from typing import Optional, Dict


def send_json(conn: socket.socket, obj: dict):
    conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")


def recv_json(conn: socket.socket) -> Optional[dict]:
    buf = b""
    while True:
        chunk = conn.recv(1)
        if not chunk:
            return None
        if chunk == b"\n":
            break
        buf += chunk
    try:
        return json.loads(buf.decode("utf-8"))
    except Exception:
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


def prompt_move() -> dict:
    raw = input("Enter your move (rock/paper/scissors) or 'surrender': ").strip().lower()
    if raw == "surrender":
        return {"type": "surrender"}
    return {"type": "move", "move": raw}


def main():
    parser = argparse.ArgumentParser(description="Rock-Paper-Scissors client.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--room_id", type=int, default=int(os.getenv("ROOM_ID", "0") or 0))
    parser.add_argument("--match_id", default=os.getenv("MATCH_ID", ""))
    parser.add_argument("--client_token", default=os.getenv("CLIENT_TOKEN", ""))
    parser.add_argument("--client_protocol_version", type=int, default=int(os.getenv("CLIENT_PROTOCOL_VERSION", "1") or 1))
    args = parser.parse_args()
    client_token = args.client_token or _read_secret("CLIENT_TOKEN", "CLIENT_TOKEN_PATH")
    match_id = args.match_id or os.getenv("MATCH_ID", "")
    room_id = args.room_id or int(os.getenv("ROOM_ID", "0") or 0)
    if not client_token or not match_id or not room_id:
        print("Missing client_token/match_id/room_id; check environment or args.")
        sys.exit(2)

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((args.host, args.port))
    hello = {
        "room_id": room_id,
        "match_id": match_id,
        "player_name": args.player,
        "client_token": client_token,
        "client_protocol_version": args.client_protocol_version,
    }
    send_json(conn, hello)
    resp = recv_json(conn)
    if not resp or not resp.get("ok"):
        print(f"Handshake rejected: {resp.get('reason') if resp else 'no response'}")
        return
    print("Connected. Waiting for updates...")

    have_printed_rules = False
    try:
        while True:
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
                    move = prompt_move()
                    try:
                        send_json(conn, move)
                    except Exception as e:
                        print(f"Failed to send move: {e}")
                        return
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
            else:
                # ignore unknown
                pass
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
