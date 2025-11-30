from user.api.user_api import UserClient
from shared.main_menu import show_main_menu
from user.ui.user_menu import show_lobby_menu, show_store_menu, show_game_entries


def prompt_credentials():
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    return username, password


def main():
    client = UserClient()
    auth_status = False
    username = ""
    cached_games = []
    page_idx = 0
    page_size = 3
    try:
        while not auth_status:
            action = show_main_menu()
            if action == "exit":
                print("Goodbye.")
                break
            username, password = prompt_credentials()
            if action == "register":
                resp = client.register(username, password)
            elif action == "login":
                resp = client.login(username, password)
            else:
                print("Unknown action.")
                continue

            if resp.status == "ok":
                print("Success.")
                auth_status = True
            else:
                print(f"Error [{resp.code}]: {resp.message}")

        while True:
            action = show_lobby_menu()
            if action == "visit_store":
                while True:
                    action = show_store_menu()
                    if action == "back":
                        break
                    if action == "list_games":
                        resp = client.list_games()
                        if resp.status == "ok":
                            cached_games = resp.payload.get("games", [])
                            page_idx = 0
                            to_show = cached_games[page_idx * page_size:(page_idx + 1) * page_size]
                            show_game_entries(to_show)
                        else:
                            print(f"Error [{resp.code}]: {resp.message}")
                    if action == "next":
                        if cached_games and (page_idx + 1) * page_size < len(cached_games):
                            page_idx += 1
                            to_show = cached_games[page_idx * page_size:(page_idx + 1) * page_size]
                            show_game_entries(to_show)
                        else:
                            print("No more pages.")
                    if action == "prev":
                        if cached_games and page_idx > 0:
                            page_idx -= 1
                            to_show = cached_games[page_idx * page_size:(page_idx + 1) * page_size]
                            show_game_entries(to_show)
                        else:
                            print("Already at first page.")
                    if action == "detail":
                        if not cached_games:
                            print("No games loaded. List games first.")
                            continue
                        name = input("Enter game name to view details: ").strip()
                        resp = client.get_game_details(name)
                        if resp.status == "ok":
                            show_game_entries([resp.payload.get("game", {})])
                        else:
                            print(f"Error [{resp.code}]: {resp.message}")

            if action == "logout":
                resp = client.logout()
                if resp.status == "ok":
                    auth_status = False
                    print(f"{username} logged out successfully.\n")
                else:
                    print(f"Error [{resp.code}]: {resp.message}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
