from developer.api.dev_api import DevClient
from shared.main_menu import show_main_menu
from developer.ui.dev_menu import show_lobby_menu, show_game_entries
from shared.input_helpers import dev_create_game
def prompt_credentials():
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    return username, password


def main():
    client = DevClient()
    auth_status = False
    username = ""
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
            if action == "list":
                resp = client.listGame(username)
                if resp.status == "ok":
                    show_game_entries(resp.payload.get("games", []))
                else:
                    print(f"Error [{resp.code}]: {resp.message}")

            if action == "create":
                create_game_params = dev_create_game()
                resp = client.createGame(username, create_game_params["game_name"], create_game_params["game_type"])
                if resp.status == "ok":
                    show_game_entries([resp.payload.get("game", {})])
                else:
                    print(f"Error [{resp.code}]: {resp.message}")

            if action == "logout":
                resp = client.logout(username)
                if resp.status == "ok":
                    auth_status = False
                    print(f"{username} logged out successfully.\n")
                else:
                    print(f"Error [{resp.code}]: {resp.message}")

    finally:
        client.close()


if __name__ == "__main__":
    main()
