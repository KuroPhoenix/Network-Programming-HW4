from shared.input_helpers import read_choice
MAIN_OPTIONS = [
    ("List online developers", "list_developers"),
    ("List my games", "list"),
    ("Create new game", "create"),
    ("Delete a local game", "delete_local"),
    ("Delete a game from store", "delete"),
    ("Logout", "logout"),
]


def show_lobby_menu():
    print("\n=== Main Menu ===")
    for idx, (label, _) in enumerate(MAIN_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(MAIN_OPTIONS))
    return MAIN_OPTIONS[choice - 1][1]


def show_game_entries(rows, with_index: bool = False):
    print("\n=== Game Entries ===")
    for idx, row in enumerate(rows, 1):
        prefix = f"{idx}. " if with_index else ""
        print(f"{prefix}{row.get('game_name')}")
        if "author" in row:
            print(f"  Author: {row.get('author')}")
        if "type" in row:
            print(f"  Type: {row.get('type')}")
        if "version" in row:
            print(f"  Version: {row.get('version')}")
        if "description" in row:
            print(f"  Description: {row.get('description')}")
        if "_path" in row:
            print(f"  Path: {row.get('_path')}")
        print("\n")


def show_game_menu(username: str, page_slice: list[dict], has_prev: bool, has_next: bool):
    options: list[tuple[str, str | tuple[str, int]]] = []
    for idx, entry in enumerate(page_slice, 1):
        label = entry.get("game_name", f"Game {idx}")
        author = entry.get("author")
        if author == username:
            label = f"{label}"
            options.append((label, ("select", idx - 1)))
    if not options:
        print("You did not develop any games. Timmy already designed Genshin and won 2 Nobel Prizes while you are still here procrastinating!")
        return -1
    if has_next:
        options.append(("Next page", "next"))
    if has_prev:
        options.append(("Previous page", "prev"))
    options.append(("Back", "back"))

    print("\n=== My Games ===")
    for idx, (label, _) in enumerate(options, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(options))
    return options[choice - 1][1]
