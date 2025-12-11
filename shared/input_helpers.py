def read_choice(min_val: int, max_val: int) -> int:
    """
    Prompt until the user enters an integer in [min_val, max_val]. Returns the chosen integer.
    """
    while True:
        raw = input(f"Select an option: ({min_val}-{max_val}): ").strip()
        if not raw.isdigit():
            print("Please enter a number.")
            continue
        choice = int(raw)
        if choice < min_val or choice > max_val:
            print(f"Please enter a number between {min_val} and {max_val}.")
            continue
        return choice

def dev_create_game() -> dict:
    game_name = ""
    game_type = ""
    version = "1.0.0"
    description = ""
    while True:
        raw = input("Enter game name: ").strip()
        if not raw:
            print("Please enter a game name.")
            continue
        game_name = raw
        break

    while True:
        raw = input("Enter game type (CLI/GUI, 2P/Multi): ").strip()
        if raw not in ["CLI", "GUI", "2P", "Multi"]:
            print("Please enter a valid game type.")
            continue
        game_type = raw
        break
    raw_ver = input("Enter version (default 1.0.0): ").strip()
    if raw_ver:
        version = raw_ver
    description = input("Enter description (optional): ").strip()
    return {"game_name": game_name, "game_type": game_type, "version": version, "description": description}

def dev_upload_game() -> dict:
    game_name = ""
    game_type = ""
    description = ""
    max_players = 0
    while True:
        raw = input("Enter game name: ").strip()
        if not raw:
            print("Please enter a game name.")
            continue
        game_name = raw
        break

    while True:
        raw = input("Enter game type (CLI/GUI, 2P/Multi): ").strip()
        if raw not in ["CLI", "GUI", "2P", "Multi"]:
            print("Please enter a valid game type.")
            continue
        game_type = raw
        break

    description = input("Enter description (optional): ").strip()
    raw_max = input("Enter max players (default 0): ").strip()
    if raw_max.isdigit():
        max_players = int(raw_max)

    return {
        "game_name": game_name,
        "game_type": game_type,
        "description": description,
        "max_players": max_players,
    }

def user_review() -> dict:
    while True:
        score = input("Enter review score (1~5): ").strip()
        if not score:
            print("Please enter a review score.")
            continue
        if not score.isdigit():
            print("Please enter a valid review score (1~5).")
            continue
        if int(score) > 5 or int(score) < 1:
            print("Please enter a valid review score (1~5).")
            continue
        break
    while True:
        raw = input("Enter review details (\"==\" not accepted.) : ").strip()
        if not raw:
            print("Please enter review details.")
            continue
        if "==" in raw:
            print("Please enter a valid review.")
            continue
        break
    return {"score": int(score), "content": raw}


