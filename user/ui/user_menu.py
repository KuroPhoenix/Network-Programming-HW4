from server.core.protocol import REVIEW_ADD
from shared.input_helpers import read_choice

MAIN_OPTIONS = [
    ("Visit Store to download games", "visit_store"),
    ("Visit Lobby to play games", "visit_lobby"),
    ("View my reviews", "visit_review"),
    ("Logout", "logout"),
]
REVIEW_DETAIL_OPTIONS = [
    ("Delete this review", "delete_review"),
    ("Edit this review", "edit_review"),
    ("Go Back", "back"),
]
STORE_OPTIONS = [
    ("Next page", "next"),
    ("Previous page", "prev"),
    ("Back to previous menu", "back"),
]

LOBBY_OPTIONS = [
    ("List rooms", "list_rooms"),
    ("List online players", "list_players"),
    ("Create room", "create_room"),
    ("Join room", "join_room"),
    ("Back to main menu", "back"),
]

ROOM_OPTIONS = [
    ("Start game", "start_game"),
    ("Launch started game", "launch_game"),
    ("Leave room", "leave_room"),
]

GAME_OPTIONS = [
    ("View game details", "view_game_details"),
    ("View game reviews", "view_game_reviews"),
    ("Download game", "download_game"),
    ("Update to latest version", "update_game"),
    ("Delete local copy", "delete_game"),
    ("Give this game a review", "review_game"),
    ("Go back", "back"),
]

def show_review_menu(sub_catalogue: list[dict]):
    options: list[tuple[str, str | tuple[str, int]]] = []
    for idx, entry in enumerate(sub_catalogue, 1):
        game_name = entry.get("game_name", f"Game {idx}")
        content = entry.get("content", f"Review content: {idx}")
        options.append((f"{game_name} | {content}", ("select", idx - 1)))  # idx-1 is index into the slice
    options.append(("Back", "back"))

    print("=== Your Reviews ===")
    print("Select one review to edit or delete.")
    for idx, (label, _) in enumerate(options, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(options))
    return options[choice - 1][1]

def show_review_detail_menu():
    print("=== Review Details Menu ===")
    for idx, (label, _) in enumerate(REVIEW_DETAIL_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(REVIEW_DETAIL_OPTIONS))
    return REVIEW_DETAIL_OPTIONS[choice - 1][1]

def show_game_menu():
    print("=== Game Menu ===")
    for idx, (label, _) in enumerate(GAME_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(GAME_OPTIONS))
    return GAME_OPTIONS[choice - 1][1]

def show_room_menu():
    print("=== Room Menu ===")
    for idx, (label, _) in enumerate(ROOM_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(ROOM_OPTIONS))
    return ROOM_OPTIONS[choice - 1][1]

def show_authed_menu():
    print("=== Main Menu ===")
    for idx, (label, _) in enumerate(MAIN_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(MAIN_OPTIONS))
    return MAIN_OPTIONS[choice - 1][1]

def show_lobby_menu():
    print("=== Lobby Menu ===")
    for idx, (label, _) in enumerate(LOBBY_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(LOBBY_OPTIONS))
    return LOBBY_OPTIONS[choice - 1][1]

def show_store_menu(sub_catalogue: list[dict], has_prev: bool, has_next: bool):
    options: list[tuple[str, str | tuple[str, int]]] = []
    for idx, entry in enumerate(sub_catalogue, 1):
        name = entry.get("game_name", f"Game {idx}")
        options.append((f"{name}", ("select", idx - 1)))  # idx-1 is index into the slice
    if has_next:
        options.append(("Next page", "next"))
    if has_prev:
        options.append(("Previous page", "prev"))
    options.append(("Back", "back"))

    print("=== Store Menu ===")
    for idx, (label, _) in enumerate(options, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(options))
    return options[choice - 1][1]


def show_game_detail(rows):
    for row in rows:
        print("*" * 20)
        print(f"Game: {row.get('game_name')}")
        if "author" in row:
            print(f"Author: {row.get('author')}")
        if "type" in row:
            print(f"Type: {row.get('type')}")
        if "description" in row:
            print(f"Description: {row.get('description')}")
        if "version" in row:
            print(f"Version: {row.get('version')}")
        if "avg_score" in row:
            score = row.get("avg_score")
            if score is not None and score > 0:
                print(f"Average score: {score}")
            else:
                print("No average score available. (No reviews for this game).")
        print("*" * 20)


def show_rooms(rooms: list[dict]):
    print("=== Rooms ===")
    if not rooms:
        print("No rooms available.")
        return
    for room in rooms:
        rid = room.get("room_id")
        name = room.get("room_name", "")
        meta = room.get("metadata", {}) or {}
        game = meta.get("game_name") or room.get("game_name", "")
        version = meta.get("version") or room.get("version", "")
        status = room.get("status", "")
        host = room.get("host", "")
        players = room.get("players", [])
        max_p = room.get("max_players") or meta.get("max_players")
        cap = f"{len(players)}/{max_p}" if max_p else f"{len(players)}"
        print(f"[{rid}] {name} | Game: {game} (Version: {version}) | Host: {host} | Players: {cap} | Status: {status}")
