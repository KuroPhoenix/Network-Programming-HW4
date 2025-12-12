import json
from pathlib import Path

from developer.api.dev_api import DevClient
from developer.util.local_game_manager import LocalGameManager
from shared.main_menu import show_main_menu
from developer.ui.dev_menu import show_lobby_menu, show_game_entries, show_game_menu
from shared.input_helpers import dev_create_game, read_choice


def prompt_credentials():
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    return username, password


def main():
    client = DevClient()
    local_mgr = LocalGameManager()
    auth_status = False
    username = ""
    running = True
    try:
        while running:
            while not auth_status and running:
                action = show_main_menu()
                if action == "exit":
                    print("Goodbye.")
                    running = False
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

            while auth_status and running:
                try:
                    action = show_lobby_menu()
                    if action == "list_developers":
                        resp = client.list_players()
                        if resp.status == "ok":
                            players = resp.payload.get("players", []) or []
                            print("Current online developers:")
                            for player in players:
                                print(json.dumps(player, indent=2))
                        else:
                            print(f"Error [{resp.code}]: {resp.message}")
                    if action == "list":
                        # Show local manifests first, then server-side entries.
                        local_entries = local_mgr.list_manifests()
                        page_start = 0
                        page_size = 2
                        while True:
                            page_slice = local_entries[page_start : page_start + page_size]
                            if not page_slice:
                                print("No local games.")
                                break
                            action_sel = show_game_menu(
                                page_slice,
                                has_prev=page_start > 0,
                                has_next=page_start + page_size < len(local_entries),
                            )
                            if isinstance(action_sel, tuple) and action_sel[0] == "select":
                                selected = page_slice[action_sel[1]]
                                try:
                                    manifest = local_mgr.load_manifest(Path(selected["_path"]))
                                except Exception as e:
                                    print(f"Failed to read manifest: {e}")
                                    manifest = None
                                if manifest:
                                    print("=== Selected Manifest ===")
                                    print(json.dumps(manifest, indent=2))
                                    confirm = input("Upload this game to server? (y/n): ").strip().lower()
                                    if confirm.startswith("y"):
                                        upload_payload = {
                                            "game_name": manifest.get("game_name"),
                                            "game_type": manifest.get("type"),
                                            "version": manifest.get("version", "0"),
                                            "description": manifest.get("description", ""),
                                            "max_players": manifest.get("max_players", 0),
                                        }
                                        try:
                                            resp = client.uploadGame(username, upload_payload)
                                            local_mgr.upload_game(manifest.get("game_name", ""))
                                            if resp.status == "ok":
                                                print("Upload succeeded.")
                                            else:
                                                print(f"Error [{resp.code}]: {resp.message}")
                                        except Exception as e:
                                            print(f"Upload failed: {e}")
                            elif action_sel == "next":
                                page_start += page_size
                            elif action_sel == "prev":
                                page_start = max(0, page_start - page_size)
                            elif action_sel == "back":
                                break
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

                    if action == "delete":
                        resp = client.listGame(username)
                        if resp.status != "ok":
                            print(f"Error [{resp.code}]: {resp.message}")
                            continue
                        games = resp.payload.get("games", []) or []
                        if not games:
                            print("No games found on server.")
                            continue
                        unique_games = []
                        seen = set()
                        for row in games:
                            name = row.get("game_name")
                            if not name or name in seen:
                                continue
                            seen.add(name)
                            unique_games.append(row)
                        if not unique_games:
                            print("No games found on server.")
                            continue
                        show_game_entries(unique_games, with_index=True)
                        cancel_idx = len(unique_games) + 1
                        print(f"{cancel_idx}. Cancel")
                        choice = read_choice(1, cancel_idx)
                        if choice == cancel_idx:
                            continue
                        target = unique_games[choice - 1]
                        confirm = input(
                            f"Delete {target.get('game_name')} from the store (all versions)? (y/n): "
                        ).strip().lower()
                        if not confirm.startswith("y"):
                            print("Delete cancelled.")
                            continue
                        resp = client.deleteGame(username, target.get("game_name", ""))
                        if resp.status == "ok":
                            print(f"Deleted {target.get('game_name')} from the store.")
                        else:
                            print(f"Error [{resp.code}]: {resp.message}")

                    if action == "logout":
                        resp = client.logout(username)
                        if resp.status == "ok":
                            auth_status = False
                            print(f"{username} logged out successfully.\n")
                        else:
                            print(f"Error [{resp.code}]: {resp.message}")
                except Exception as e:
                    print(f"Operation failed: {e}")
    except KeyboardInterrupt:
        if auth_status:
            try:
                client.logout(username)
            except Exception:
                pass
        print("\nInterrupted. Exiting developer client.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
