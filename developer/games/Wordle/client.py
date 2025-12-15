import argparse
import json
import socket
import sys
import time
from typing import Optional, List, Dict


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


def format_guess_row(word: str, result: List[str]) -> str:
    # Use symbols to represent status: correct=G, present=Y, absent=.
    symbols = {"correct": "G", "present": "Y", "absent": "."}
    marks = "".join(symbols.get(r, ".") for r in result)
    return f"{word.upper():<7} [{marks}]"


def print_player_state(state: Dict):
    print("\n=== Wordle State ===")
    guesses = state.get("guesses", [])
    target_len = state.get("target_length", 5)
    max_attempts = state.get("max_attempts", 6)
    for g in guesses:
        print(format_guess_row(g.get("word", ""), g.get("result", [])))
    for _ in range(max_attempts - len(guesses)):
        print("_" * target_len)
    print(f"Attempts left: {state.get('attempts_left')}")
    opp = state.get("opponent") or {}
    print(f"Opponent {opp.get('name')}: guesses={opp.get('guesses')} solved={opp.get('solved')}")
    if state.get("solved"):
        print("You solved it! Waiting for result...")


def prompt_guess(target_len: int) -> dict:
    print(f"Enter a {target_len}-letter word (or type 'surrender' to give up):")
    raw = input("> ").strip()
    if raw.lower() == "surrender":
        return {"type": "surrender"}
    return {"type": "guess", "word": raw}


def main():
    parser = argparse.ArgumentParser(description="Wordle duel client.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--spectator", action="store_true", help="connect as spectator")
    args = parser.parse_args()

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for attempt in range(6):
        try:
            conn.connect((args.host, args.port))
            break
        except Exception:
            if attempt == 5:
                raise
            time.sleep(0.5)
    role = "spectator" if args.spectator else "player"
    send_json(conn, {"type": "hello", "player": args.player, "token": args.token, "role": role})

    def print_rules():
        print("=== Wordle Duel Rules ===")
        print("- Solve the shared 5-letter target word before your opponent.")
        print("- Each guess returns result codes: G=correct spot, Y=present elsewhere, .=absent.")
        print("- You have 6 attempts. Type your guess and press Enter. Type 'surrender' to forfeit.")
        print("- Disconnects or quitting will surrender the game.")

    print_rules()

    try:
        while True:
            msg = recv_json(conn)
            if not msg:
                print("Disconnected from server.")
                return
            mtype = msg.get("type")
            if mtype == "ok":
                print(f"Connected as {role}. Waiting for updates...")
            elif mtype == "state":
                if role == "spectator" and "players" in msg:
                    print("\n=== Spectator View ===")
                    for pname, info in (msg.get("players") or {}).items():
                        print(f"{pname}: guesses={info.get('guesses')} solved={info.get('solved')} attempts_left={info.get('attempts_left')}")
                    continue
                print_player_state(msg)
                if not args.spectator and not msg.get("solved") and msg.get("attempts_left", 0) > 0:
                    play = prompt_guess(msg.get("target_length", 5))
                    send_json(conn, play)
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
