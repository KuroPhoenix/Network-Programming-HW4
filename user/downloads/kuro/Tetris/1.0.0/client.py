import argparse
import json
import queue
import socket
import sys
import threading
import time
from typing import Optional, Dict

try:
    import tkinter as tk
except Exception:
    tk = None  # GUI fallback handled later


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


class TetrisGUI:
    """
    Minimal Tkinter renderer for Tetris state. Renders your board and opponent summary.
    """

    def __init__(self, cmd_queue: queue.Queue):
        if tk is None:
            raise RuntimeError("Tkinter not available; cannot run GUI")
        self.root = tk.Tk()
        self.root.title("Tetris")
        self.status_var = tk.StringVar(value="Waiting for match snapshots...")
        self.status_label = tk.Label(self.root, textvariable=self.status_var, font=("Arial", 12))
        self.status_label.pack()
        self.canvas = tk.Canvas(self.root, width=260, height=520, bg="black")
        self.canvas.pack()
        self.cell_size = 20
        self.board_width = 10
        self.board_height = 20
        self.cmd_queue = cmd_queue
        self._bind_keys()
        self.running = True

    def _bind_keys(self):
        bindings = {
            "<Left>": "LEFT",
            "<Right>": "RIGHT",
            "<Down>": "DOWN",
            "<Up>": "ROTATE",
            "<space>": "DROP",
            "<h>": "HOLD",
            "<H>": "HOLD",
            "<Escape>": "QUIT",
            "<q>": "QUIT",
            "<Q>": "QUIT",
        }
        for k, cmd in bindings.items():
            self.root.bind(k, lambda _e, c=cmd: self.cmd_queue.put(c))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.running = False
        self.cmd_queue.put("QUIT")

    def set_status(self, text: str):
        self.status_var.set(text)

    def render(self, board: list[str], score: int, lines: int, alive: bool, opponent: Dict, hold: Optional[str]):
        if not board:
            return
        self.board_height = len(board)
        self.board_width = len(board[0]) if board else 10
        self.canvas.delete("all")
        for y, row in enumerate(board):
            for x, ch in enumerate(row):
                if ch != ".":
                    x0 = x * self.cell_size
                    y0 = y * self.cell_size
                    x1 = x0 + self.cell_size
                    y1 = y0 + self.cell_size
                    self.canvas.create_rectangle(x0, y0, x1, y1, fill="cyan", outline="gray")
        opp_text = f"Opp: {opponent.get('name')} score={opponent.get('score')} lines={opponent.get('lines')} alive={opponent.get('alive')}"
        self.status_var.set(f"Score={score} Lines={lines} Alive={alive} Hold={hold or '-'} | {opp_text}")
        self.root.update_idletasks()
        self.root.update()

    def render_spectator(self, players: dict):
        text = []
        for name, state in players.items():
            text.append(f"{name}: score={state.get('score')} lines={state.get('lines')} alive={state.get('alive')}")
        self.status_var.set(" | ".join(text) or "Spectating...")
        self.root.update_idletasks()
        self.root.update()

    def is_running(self) -> bool:
        try:
            self.root.update()
            return self.running
        except Exception:
            return False


def main():
    parser = argparse.ArgumentParser(description="Tetris Python client.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--spectator", action="store_true", help="connect as spectator")
    parser.add_argument("--gui", action="store_true", help="launch with Tkinter GUI if available")
    args = parser.parse_args()

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((args.host, args.port))
    role = "spectator" if args.spectator else "player"
    send_json(conn, {"type": "hello", "player": args.player, "token": args.token, "role": role})

    cmd_queue: queue.Queue = queue.Queue()
    gui_renderer: Optional[TetrisGUI] = None
    if args.gui:
        try:
            gui_renderer = TetrisGUI(cmd_queue)
        except Exception as e:
            print(f"GUI not available ({e}), falling back to console.")
            gui_renderer = None

    if not args.spectator:
        if gui_renderer:
            # Tk handles key events; sender thread still sends commands.
            threading.Thread(target=sender_thread, args=(conn, cmd_queue), daemon=True).start()
        else:
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
                if gui_renderer:
                    gui_renderer.set_status("Connected. Waiting for ticks...")
            elif mtype == "tick":
                if args.spectator and "players" in msg:
                    if gui_renderer:
                        gui_renderer.render_spectator(msg.get("players", {}))
                    else:
                        render_spectator(msg.get("players", {}))
                else:
                    board = msg.get("board", [])
                    score = msg.get("score", 0)
                    lines = msg.get("lines", 0)
                    alive = msg.get("alive", False)
                    opponent = msg.get("opponent", {})
                    hold = msg.get("hold")
                    if gui_renderer:
                        gui_renderer.render(board, score, lines, alive, opponent, hold)
                    else:
                        render(board, score, lines, alive, opponent, hold)
            elif mtype == "game_over":
                print(f"Game over. Winner: {msg.get('winner')}")
                if gui_renderer:
                    gui_renderer.set_status(f"Game over. Winner: {msg.get('winner')}")
                break
            elif mtype == "error":
                print(f"Error: {msg.get('message')}")
                if gui_renderer:
                    gui_renderer.set_status(f"Error: {msg.get('message')}")
            else:
                pass
            if gui_renderer and not gui_renderer.is_running():
                break
    except KeyboardInterrupt:
        if not args.spectator:
            try:
                send_json(conn, {"type": "cmd", "cmd": "QUIT"})
                time.sleep(0.1)
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
