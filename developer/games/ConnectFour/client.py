import argparse
import json
import socket
import sys
import threading
import time
from queue import Queue, Empty
from typing import Optional, Dict

import pygame


SQUARESIZE = 100
RADIUS = int(SQUARESIZE / 2 - 6)
BLUE = (0, 0, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
WHITE = (255, 255, 255)
BG = (20, 20, 20)


def send_json(conn: socket.socket, obj: dict) -> bool:
    try:
        conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")
        return True
    except Exception:
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
    except Exception:
        return None
    try:
        return json.loads(buf.decode("utf-8"))
    except Exception:
        return None


def draw_board(screen, board_state: Dict, status_text: str, winner_text: str, your_name: str, turn_player: str):
    rows = board_state.get("rows", 6)
    cols = board_state.get("cols", 7)
    grid = board_state.get("grid", [[0] * cols for _ in range(rows)])
    width = cols * SQUARESIZE
    height = (rows + 1) * SQUARESIZE
    screen.fill(BG)

    # Header bar
    font = pygame.font.SysFont("arial", 24)
    header = font.render(status_text, True, WHITE)
    screen.blit(header, (10, 10))
    if winner_text:
        win_label = font.render(winner_text, True, WHITE)
        screen.blit(win_label, (10, 40))
    turn_label = font.render(f"Your name: {your_name} | Turn: {turn_player}", True, WHITE)
    screen.blit(turn_label, (10, 70))

    # Grid
    for c in range(cols):
        for r in range(rows):
            pygame.draw.rect(screen, BLUE, (c * SQUARESIZE, (r + 1) * SQUARESIZE, SQUARESIZE, SQUARESIZE))
            pygame.draw.circle(
                screen,
                BLACK,
                (int(c * SQUARESIZE + SQUARESIZE / 2), int((r + 1) * SQUARESIZE + SQUARESIZE / 2)),
                RADIUS,
            )

    for c in range(cols):
        for r in range(rows):
            piece = grid[r][c]
            if piece == 1:
                color = RED
            elif piece == 2:
                color = YELLOW
            else:
                continue
            pygame.draw.circle(
                screen,
                color,
                (int(c * SQUARESIZE + SQUARESIZE / 2), int((r + 1) * SQUARESIZE + SQUARESIZE / 2)),
                RADIUS,
            )
    pygame.display.update()


def main():
    parser = argparse.ArgumentParser(description="ConnectFour client")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connected = False
    for attempt in range(6):
        try:
            conn.connect((args.host, args.port))
            connected = True
            break
        except Exception:
            time.sleep(0.5)
    if not connected:
        print("Unable to connect to server.")
        sys.exit(1)

    send_json(conn, {"type": "hello", "player": args.player, "token": args.token, "role": "player"})

    messages: Queue = Queue()
    disconnected = threading.Event()

    def reader():
        while True:
            msg = recv_json(conn)
            if msg is None:
                disconnected.set()
                messages.put({"type": "disconnected"})
                break
            messages.put(msg)

    threading.Thread(target=reader, daemon=True).start()

    current_state: Optional[Dict] = None
    winner_text = ""
    status_text = "Waiting for game to start..."
    your_turn = False
    turn_player = ""
    rows = 6
    cols = 7
    width = cols * SQUARESIZE
    height = (rows + 1) * SQUARESIZE

    pygame.init()
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("Connect Four")
    clock = pygame.time.Clock()

    running = True
    game_over = False

    try:
        while running:
            try:
                msg = messages.get_nowait()
            except Empty:
                msg = None

            if msg:
                mtype = msg.get("type")
                if mtype == "state":
                    current_state = msg.get("board")
                    rows = current_state.get("rows", rows)
                    cols = current_state.get("cols", cols)
                    width = cols * SQUARESIZE
                    height = (rows + 1) * SQUARESIZE
                    screen = pygame.display.set_mode((width, height))
                    turn_player = msg.get("turn_player", "")
                    your_turn = turn_player == args.player
                    status_text = "Your turn" if your_turn else f"Waiting for {turn_player}"
                    winner_text = ""
                elif mtype == "game_over":
                    current_state = msg.get("board", current_state)
                    winner = msg.get("winner")
                    reason = msg.get("reason", "")
                    if winner:
                        winner_text = f"Winner: {winner} (reason: {reason})"
                    else:
                        winner_text = f"Game over ({reason})"
                    status_text = "Game finished"
                    game_over = True
                elif mtype == "error":
                    status_text = f"Error: {msg.get('message')}"
                elif mtype == "disconnected":
                    status_text = "Disconnected from server"
                    game_over = True

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if not game_over:
                        send_json(conn, {"type": "surrender"})
                    running = False
                if event.type == pygame.MOUSEBUTTONDOWN and not game_over and your_turn and current_state:
                    x_pos = event.pos[0]
                    col = int(x_pos // SQUARESIZE)
                    send_json(conn, {"type": "move", "col": col})
                    your_turn = False

            if current_state:
                draw_board(screen, current_state, status_text, winner_text, args.player, turn_player)

            if game_over and disconnected.is_set():
                running = False

            clock.tick(30)
    except KeyboardInterrupt:
        if not game_over:
            send_json(conn, {"type": "surrender"})
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        conn.close()
        pygame.quit()


if __name__ == "__main__":
    main()
