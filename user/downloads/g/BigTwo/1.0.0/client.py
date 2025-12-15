import argparse
import json
import socket
import sys
from typing import Optional


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
    parser.add_argument("--token", required=True)
    parser.add_argument("--spectator", action="store_true", help="connect as spectator")
    args = parser.parse_args()

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((args.host, args.port))
    role = "spectator" if args.spectator else "player"
    send_json(conn, {"type": "hello", "player": args.player, "token": args.token, "role": role})

    try:
        while True:
            msg = recv_json(conn)
            if not msg:
                print("Disconnected from server.")
                return
            mtype = msg.get("type")
            if mtype == "ok":
                print("Connected. Waiting for game start...")
            elif mtype == "state":
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
