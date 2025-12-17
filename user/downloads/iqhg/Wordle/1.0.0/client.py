import argparse
import json
import socket
import sys
import time
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, IO

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


_configure_logging("game_wordle_client.log")
logger = logging.getLogger(__name__)

MAX_LINE_BYTES = 64 * 1024


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


def send_json(conn: socket.socket, obj: dict) -> bool:
    try:
        conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")
        return True
    except Exception as exc:
        logger.warning("send_json failed: %s", exc)
        return False


def recv_json(reader: IO[str]) -> Optional[dict]:
    try:
        line = reader.readline(MAX_LINE_BYTES)
    except Exception as exc:
        logger.warning("recv_json failed: %s", exc)
        return None
    if not line:
        return None
    if len(line) >= MAX_LINE_BYTES:
        logger.warning("received line exceeds max (%d bytes); discarding", MAX_LINE_BYTES)
        return None
    try:
        return json.loads(line)
    except Exception as exc:
        logger.warning("recv_json parse failed: %s", exc)
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


def print_rules(target_len: int, max_attempts: int):
    print(
        f"""
=== How to Play ===
- You and your opponent solve the same {target_len}-letter word.
- Each guess returns: G = correct letter/place, Y = letter in word wrong place, . = absent.
- You have {max_attempts} attempts. First to solve wins; if time runs out, best board wins.
- Type 'surrender' to forfeit.
"""
    )


def main():
    parser = argparse.ArgumentParser(description="Wordle duel client.")
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
    for attempt in range(6):
        try:
            conn.connect((args.host, args.port))
            break
        except Exception as exc:
            logger.warning("connect attempt %s failed: %s", attempt + 1, exc)
            if attempt == 5:
                raise
            time.sleep(0.5)
    role = "spectator" if args.spectator else "player"
    hello = {
        "room_id": room_id,
        "match_id": match_id,
        "player_name": args.player,
        "client_token": client_token,
        "client_protocol_version": args.client_protocol_version,
        "role": role,
    }
    reader = conn.makefile("r", encoding="utf-8", newline="\n")
    if not send_json(conn, hello):
        print("Failed to send handshake.")
        try:
            reader.close()
        except Exception:
            pass
        return
    resp = recv_json(reader)
    if not resp or not resp.get("ok"):
        print(f"Handshake rejected: {resp.get('reason') if resp else 'no response'}")
        try:
            reader.close()
        except Exception:
            pass
        return
    print(f"Connected as {role}. Waiting for updates...")

    printed_rules = False
    try:
        while True:
            msg = recv_json(reader)
            if not msg:
                print("Disconnected from server.")
                return
            mtype = msg.get("type")
            if mtype == "rules":
                # Server-sent rules message
                txt = msg.get("text") or ""
                print_rules(target_len=msg.get("target_length", 5), max_attempts=msg.get("max_attempts", 6))
                if txt:
                    print(txt)
            elif mtype == "state":
                if role == "spectator" and "players" in msg:
                    print("\n=== Spectator View ===")
                    for pname, info in (msg.get("players") or {}).items():
                        print(f"{pname}: guesses={info.get('guesses')} solved={info.get('solved')} attempts_left={info.get('attempts_left')}")
                    continue
                if not printed_rules:
                    print_rules(target_len=msg.get("target_length", 5), max_attempts=msg.get("max_attempts", 6))
                    printed_rules = True
                print_player_state(msg)
                if not args.spectator and not msg.get("solved") and msg.get("attempts_left", 0) > 0:
                    play = prompt_guess(msg.get("target_length", 5))
                    try:
                        send_json(conn, play)
                    except (BrokenPipeError, ConnectionResetError):
                        print("Connection closed while sending your move. Exiting.")
                        return
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
        if not args.spectator:
            try:
                send_json(conn, {"type": "surrender"})
            except Exception:
                pass
        print("\nExiting game...")
    finally:
        try:
            reader.close()
        except Exception:
            pass
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    main()
