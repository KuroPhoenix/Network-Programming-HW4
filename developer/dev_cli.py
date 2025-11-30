from developer.api.dev_api import DevClient
from developer.util.local_game_manager import LocalGameManager
from shared.main_menu import show_main_menu
from developer.ui.dev_menu import show_lobby_menu, show_game_entries
from shared.input_helpers import dev_create_game, dev_upload_game


def prompt_credentials():
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    return username, password


def main():
    client = DevClient()
    local_mgr = LocalGameManager()
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
                # Show local manifests first, then server-side entries.
                local_entries = local_mgr.list_manifests()
                if local_entries:
                    print("=== Local Game Manifests ===")
                    show_game_entries(local_entries)
                resp = client.listGame(username)
                if resp.status == "ok":
                    print("=== Server Game Manifests ===")
                    show_game_entries(resp.payload.get("games", []))
                else:
                    print(f"Error [{resp.code}]: {resp.message}")

            if action == "create":
                create_game_params = dev_create_game()
                local_mgr.create_manifest(
                    create_game_params["game_name"],
                    create_game_params["version"],
                    create_game_params["game_type"],
                    create_game_params["description"],
                )

            if action == "upload":
                upload_game_params = dev_upload_game()
                local_mgr.upload_game(upload_game_params["game_name"])
                resp = client.uploadGame(username, upload_game_params)
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
