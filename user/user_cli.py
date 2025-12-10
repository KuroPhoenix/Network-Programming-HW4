from user.api.user_api import UserClient
from shared.main_menu import show_main_menu
from user.ui.user_menu import show_authed_menu, show_store_menu, show_game_detail, show_lobby_menu, show_rooms, \
    show_room_menu


def prompt_credentials():
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    return username, password


def main():
    client = UserClient()
    auth_status = False
    username = ""
    game_catalogue = []
    try:
        running = True
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
                action = show_authed_menu()
                if action == "visit_store":
                    page_start = 0
                    while True:
                        resp = client.list_games()
                        if resp.status == "ok":
                            game_catalogue = resp.payload.get("games", [])
                        else:
                            print(f"Error [{resp.code}]: {resp.message}")
                        print("Select the game to get a detailed view.")
                        page_end = page_start + 2
                        page_slice = game_catalogue[page_start:page_end]
                        if not page_slice:
                            print("No games available.")
                            break
                        action = show_store_menu(page_slice, has_prev=page_start > 0,
                                                 has_next=page_end < len(game_catalogue))
                        if isinstance(action, tuple) and action[0] == "select":
                            selected = page_slice[action[1]]
                            show_game_detail([selected])
                            raw = input("Download this game? (y/n) ").strip()
                            if raw == "y":
                                client.download_game(username, selected.get("game_name", ""))
                        elif action == "next":
                            if page_end < len(game_catalogue):
                                page_start += 2
                        elif action == "prev":
                            page_start = max(0, page_start - 2)
                        elif action == "back":
                            break

                if action == "visit_lobby":
                    in_room = False
                    curr_room_id = 0
                    while True:
                        lobby_action = show_lobby_menu()
                        if lobby_action == "back":
                            break
                        if lobby_action == "list_rooms":
                            resp = client.list_rooms()
                            if resp.status == "ok":
                                show_rooms(resp.payload.get("rooms", []))
                            else:
                                print(f"Error [{resp.code}]: {resp.message}")
                        elif lobby_action == "create_room":
                            game_name = input("Enter game name: ").strip()
                            room_name = input("Enter room name: ").strip()
                            resp = client.create_room(username, game_name, room_name)
                            if resp.status == "ok":
                                print(f"Room created with id {resp.payload.get('room', {}).get('room_id')}")
                            else:
                                print(f"Error [{resp.code}]: {resp.message}")
                        elif lobby_action == "join_room":
                            room_id_raw = input("Enter room id to join: ").strip()
                            try:
                                room_id = int(room_id_raw)
                            except ValueError:
                                print("Invalid room id.")
                                continue
                            spect = input("Join as spectator? (y/n): ").strip().lower().startswith("y")
                            resp = client.join_room(username, room_id, spectator=spect)
                            if resp.status == "ok":
                                print(f"Joined room {room_id}.")
                                in_room = True
                                curr_room_id = room_id
                            else:
                                print(f"Error [{resp.code}]: {resp.message}")
                        if in_room:
                            while True:
                                room_action = show_room_menu()
                                if room_action == "leave_room":
                                    resp = client.leave_room(username, curr_room_id)
                                    if resp.status == "ok":
                                        if resp.payload.get("host") == "":
                                            print("Room deleted; no host remaining.")
                                        else:
                                            print(f"Left room {curr_room_id}. New host: {resp.payload.get('host')}")
                                    else:
                                        print(f"Error [{resp.code}]: {resp.message}")
                                if room_action == "start_game":
                                    resp = client.start_game(curr_room_id, username)
                                    if resp.status == "ok":
                                        print("Game started successfully!")
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
