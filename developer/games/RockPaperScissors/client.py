import argparse
import json
import socket
import sys
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
    parser.add_argument("--token", required=True)
    parser.add_argument("--spectator", action="store_true", help="connect as spectator")
    args = parser.parse_args()

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((args.host, args.port))
    role = "spectator" if args.spectator else "player"
    send_json(conn, {"type": "hello", "player": args.player, "token": args.token, "role": role})

    have_printed_rules = False
    try:
        while True:
            msg = recv_json(conn)
            if not msg:
                print("Disconnected from server.")
                return
            mtype = msg.get("type")
            if mtype == "ok":
                print(f"Connected as {role}. Waiting for updates...")
                if not have_printed_rules:
                    print_rules()
                    have_printed_rules = True
            elif mtype == "rules":
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
