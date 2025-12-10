import argparse
import json
import queue
import socket
import sys
import threading
import time
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


def render(board: list[str], score: int, lines: int, alive: bool, opponent: dict, hold: Optional[str]):
    print("\n" + "=" * 22)
    print(f"Score: {score}  Lines: {lines}  Alive: {alive}  Hold: {hold or '-'}")
    print(f"Opponent {opponent.get('name')}: score={opponent.get('score')} lines={opponent.get('lines')} alive={opponent.get('alive')}")
    if opponent.get("hold") is not None:
        print(f"Opponent hold: {opponent.get('hold')}")
    for row in board:
        line = "|" + "".join("#" if c != "." else " " for c in row) + "|"
        print(line)
    print("+" + "-" * len(board[0]) + "+")
    print("Controls: a=left d=right w=rotate s=down h=hold space/drop q=quit")


def render_spectator(players: dict):
    print("\n=== Spectator view ===")
    for name, state in players.items():
        print(f"{name}: score={state.get('score')} lines={state.get('lines')} alive={state.get('alive')} hold={state.get('hold')}")
        for row in state.get("board", []):
            line = "|" + "".join("#" if c != "." else " " for c in row) + "|"
            print(line)
        if state.get("board"):
            print("+" + "-" * len(state["board"][0]) + "+")
        print("")


def input_thread(cmd_queue: queue.Queue):
    while True:
        try:
            raw = input().strip().lower()
        except EOFError:
            raw = "q"
        if raw == "a":
            cmd_queue.put("LEFT")
        elif raw == "d":
            cmd_queue.put("RIGHT")
        elif raw == "w":
            cmd_queue.put("ROTATE")
        elif raw == "s":
            cmd_queue.put("DOWN")
        elif raw == " " or raw == "space" or raw == "drop":
            cmd_queue.put("DROP")
        elif raw == "h" or raw == "hold":
            cmd_queue.put("HOLD")
        elif raw == "q" or raw == "quit":
            cmd_queue.put("QUIT")
            break


def sender_thread(conn: socket.socket, cmd_queue: queue.Queue):
    while True:
        try:
            cmd = cmd_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        send_json(conn, {"type": "cmd", "cmd": cmd})
        if cmd == "QUIT":
            return


def main():
    parser = argparse.ArgumentParser(description="Tetris Python client.")
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

    cmd_queue: queue.Queue = queue.Queue()
    if not args.spectator:
        threading.Thread(target=input_thread, args=(cmd_queue,), daemon=True).start()
        threading.Thread(target=sender_thread, args=(conn, cmd_queue), daemon=True).start()

    try:
        while True:
            msg = recv_json(conn)
            if not msg:
                print("Disconnected from server.")
                break
            mtype = msg.get("type")
            if mtype == "ok":
                print("Connected. Waiting for ticks...")
            elif mtype == "tick":
                if args.spectator and "players" in msg:
                    render_spectator(msg.get("players", {}))
                else:
                    render(
                        msg.get("board", []),
                        msg.get("score", 0),
                        msg.get("lines", 0),
                        msg.get("alive", False),
                        msg.get("opponent", {}),
                        msg.get("hold"),
                    )
            elif mtype == "game_over":
                print(f"Game over. Winner: {msg.get('winner')}")
                break
            elif mtype == "error":
                print(f"Error: {msg.get('message')}")
            else:
                pass
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
