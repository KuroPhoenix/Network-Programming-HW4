from shared.input_helpers import read_choice
MAIN_OPTIONS = [
    ("Visit Store", "visit_store"),
    ("Logout", "logout"),
]
STORE_OPTIONS = [
    ("List games (paged)", "list_games"),
    ("Next page", "next"),
    ("Previous page", "prev"),
    ("View game detail", "detail"),
    ("Back", "back"),
]

def show_lobby_menu():
    print("=== Main Menu ===")
    for idx, (label, _) in enumerate(MAIN_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(MAIN_OPTIONS))
    return MAIN_OPTIONS[choice - 1][1]


def show_store_menu():
    print("=== Store Menu ===")
    for idx, (label, _) in enumerate(STORE_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(STORE_OPTIONS))
    return STORE_OPTIONS[choice - 1][1]

def show_game_entries(rows):
    print("=== Game Entries ===")
    for row in rows:
        print(f"Game: {row.get('game_name')}")
        if "author" in row:
            print(f"Author: {row.get('author')}")
        if "type" in row:
            print(f"Type: {row.get('type')}")
        if "description" in row:
            print(f"Description: {row.get('description')}")
        if "version" in row:
            print(f"Version: {row.get('version')}")
        print("-" * 20)
