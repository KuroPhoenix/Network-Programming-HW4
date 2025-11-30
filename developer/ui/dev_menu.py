from shared.input_helpers import read_choice
MAIN_OPTIONS = [
    ("List my games", "list"),
    ("Create new game", "create"),
    ("Logout", "logout"),
]


def show_lobby_menu():
    print("=== Main Menu ===")
    for idx, (label, _) in enumerate(MAIN_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(MAIN_OPTIONS))
    return MAIN_OPTIONS[choice - 1][1]


def show_game_entries(rows):
    print("=== Game Entries ===")
    for row in rows:
        print(f"Game: {row.get('game_name')}")
        print(f"Author: {row.get('author')}")
        print(f"Type: {row.get('type')}")
        print(f"Version: {row.get('version')}")
        print("-" * 20)
