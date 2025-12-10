from shared.input_helpers import read_choice

MAIN_OPTIONS = [
    ("Visit Store", "visit_store"),
    ("Lobby", "visit_lobby"),
    ("Logout", "logout"),
]
STORE_OPTIONS = [
    ("Next page", "next"),
    ("Previous page", "prev"),
    ("Back to previous menu", "back"),
]

LOBBY_OPTIONS = [
    ("List rooms", "list_rooms"),
    ("Create room", "create_room"),
    ("Join room", "join_room"),
    ("Back to main menu", "back"),
]

ROOM_OPTIONS = [
    ("Start game", "start_game"),
    ("Leave room", "leave_room"),
    ("Invite other players", "invite_other_players"),
]

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
        status = room.get("status", "")
        host = room.get("host", "")
        players = room.get("players", [])
        max_p = room.get("max_players") or meta.get("max_players")
        cap = f"{len(players)}/{max_p}" if max_p else f"{len(players)}"
        print(f"[{rid}] {name} | Game: {game} | Host: {host} | Players: {cap} | Status: {status}")
