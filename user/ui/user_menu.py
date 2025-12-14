from server.core.protocol import REVIEW_ADD
from shared.input_helpers import read_choice

MAIN_OPTIONS = [
    ("Visit Store to download games", "visit_store"),
    ("Visit Lobby to play games", "visit_lobby"),
    ("View my reviews", "visit_review"),
    ("View my downloaded games", "visit_downloaded_games"),
    ("Logout", "logout"),
]

LOCAL_GAME_OPTIONS = [
    ("View game details", "view_game_details"),
    ("View game reviews", "view_game_reviews"),
    ("Update to latest version", "update_game"),
    ("Delete game", "delete_game"),
    ("Go Back", "back")
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
    ("Refresh lobby snapshot", "refresh"),
    ("List rooms", "list_rooms"),
    ("List online players", "list_players"),
    ("Create room", "create_room"),
    ("Join room", "join_room"),
    ("Back to main menu", "back"),
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

def show_local_game_submenu():
    print("\n=== Local Game Submenu ===")
    for idx, (label, _) in enumerate(LOCAL_GAME_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(LOCAL_GAME_OPTIONS))
    return LOCAL_GAME_OPTIONS[choice - 1][1]

def show_local_game_menu(sub_catalogue: list[dict], prompt: str | None = None):
    options: list[tuple[str, str | tuple[str, int]]] = []
    for idx, entry in enumerate(sub_catalogue, 1):
        game_name = entry.get("game_name", f"Game {idx}")
        version = entry.get("latest_version", f"Latest version: {idx}")
        options.append((f"{game_name} | Version: {version}", ("select", idx - 1)))  # idx-1 is index into the slice
    options.append(("Back", "back"))

    print("\n=== Local Game Menu ===")
    if prompt:
        print(prompt)
    else:
        print("Select to manage game.")
    for idx, (label, _) in enumerate(options, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(options))
    return options[choice - 1][1]

def show_review_menu(sub_catalogue: list[dict]):
    options: list[tuple[str, str | tuple[str, int]]] = []
    for idx, entry in enumerate(sub_catalogue, 1):
        game_name = entry.get("game_name", f"Game {idx}")
        content = entry.get("content", f"Review content: {idx}")
        options.append((f"{game_name} | {content}", ("select", idx - 1)))  # idx-1 is index into the slice
    options.append(("Back", "back"))

    print("\n=== Your Reviews ===")
    print("Select one review to edit or delete.")
    for idx, (label, _) in enumerate(options, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(options))
    return options[choice - 1][1]

def show_review_detail_menu():
    print("\n=== Review Details Menu ===")
    for idx, (label, _) in enumerate(REVIEW_DETAIL_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(REVIEW_DETAIL_OPTIONS))
    return REVIEW_DETAIL_OPTIONS[choice - 1][1]

def show_game_menu():
    print("\n=== Game Menu ===")
    for idx, (label, _) in enumerate(GAME_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(GAME_OPTIONS))
    return GAME_OPTIONS[choice - 1][1]

def show_room_menu(is_host: bool, status: str, can_ready: bool):
    """
    status: WAITING | IN_GAME
    Host can start when waiting; anyone can launch when IN_GAME.
    """
    print("=== Room Menu ===")
    options: list[tuple[str, str]] = []
    if is_host and status == "WAITING":
        options.append(("Start game", "start_game"))
    if not is_host and status == "WAITING" and can_ready:
        options.append(("Ready up", "ready"))
    if status == "IN_GAME":
        options.append(("Launch started game", "launch_game"))
    options.append(("Leave room", "leave_room"))
    for idx, (label, _) in enumerate(options, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(options))
    return options[choice - 1][1]

def show_authed_menu():
    print("\n=== Main Menu ===")
    for idx, (label, _) in enumerate(MAIN_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(MAIN_OPTIONS))
    return MAIN_OPTIONS[choice - 1][1]

def show_lobby_menu():
    print("\n=== Lobby Menu ===")
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

    print("\n=== Store Menu ===")
    for idx, (label, _) in enumerate(options, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(options))
    return options[choice - 1][1]


def show_game_detail(rows):
    for row in rows:
        print("\n")
        print("===GAME DETAILS===")
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
        print("===GAME DETAILS===")


def show_rooms(rooms: list[dict]):
    print("\n=== Rooms ===")
    if not rooms:
        print("\nNo rooms available.")
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
