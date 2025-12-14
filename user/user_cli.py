import time

from server.core.room_genie import Room
from shared.input_helpers import user_review
from user.api.user_api import UserClient
from shared.main_menu import show_main_menu
from user.ui.user_menu import show_authed_menu, show_store_menu, show_game_detail, show_lobby_menu, show_rooms, \
    show_room_menu, show_game_menu, show_review_menu, show_review_detail_menu, show_local_game_menu, \
    show_local_game_submenu
from server.core.protocol import Message


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
                #======================================AUTH===================================
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
#============================MAIN MENU===========================================
            while auth_status and running:
                try:
#==============================REVIEW_MENU=======================================
                    action = show_authed_menu()
                    if action == "visit_downloaded_games":
                        downloaded = client.list_local_games(username)
                        if not downloaded:
                            print("No downloaded games found. Visit the store to download games first.")
                            continue
                        action = show_local_game_menu(downloaded, "\nSelect a game to manage.")
                        if action == "back":
                            continue
                        if isinstance(action, tuple) and action[0] == "select":
                            selected = downloaded[action[1]]
                            while True:
                                action = show_local_game_submenu()
                                if action == "back":
                                    break
                                if action == "view_game_details":
                                    show_game_detail([selected])
                                if action == "update_game":
                                    resp = client.update_game(username, selected.get("game_name"), require_installed=True)
                                    if resp.status != "ok":
                                        print(f"Error [{resp.code}]: {resp.message}")
                                    else:
                                        print(resp.message or "Updated to latest version.")
                                if action == "delete_game":
                                    resp = client.delete_game(username, selected.get("game_name"))
                                    if resp.status != "ok":
                                        print(f"Error [{resp.code}]: {resp.message}")
                                    else:
                                        print("Local game deleted.")
                                        break
                                if action == "view_game_reviews":
                                    resp = client.list_game_review(selected.get("game_name", ""))
                                    if resp.status != "ok":
                                        print(f"Error [{resp.code}]: {resp.message}")
                                    else:
                                        reviews = resp.payload.get("reviews", []) or []
                                        if not reviews:
                                            print("No reviews for this game yet!")
                                        else:
                                            for r in reviews:
                                                print(f"{r.get('author')}: {r.get('content')}")

                    if action == "visit_review":
                        while auth_status and running:
                            resp = client.list_author_review(username)
                            if resp.status != "ok":
                                print(f"Error [{resp.code}]: {resp.message}")
                            else:
                                reviews = resp.payload.get("reviews", [])
                                action = show_review_menu(reviews)
                                if action == "back":
                                    break
                                if isinstance(action, tuple) and action[0] == "select":
                                    selected = reviews[action[1]]
                                    while True:
                                        action = show_review_detail_menu()
                                        if action == "delete_review":
                                            resp = client.delete_review(username, selected.get("game_name"), selected.get("content"), selected.get("version"),)
                                            if resp.status != "ok":
                                                print(f"Error [{resp.code}]: {resp.message}")
                                            else:
                                                print("Review successfully deleted.")
                                        if action == "edit_review":
                                            new_review = user_review()
                                            resp = client.edit_review(username,selected.get("game_name"),selected.get("content"),new_review.get("content"),new_review.get("score"),selected.get("version"),)
                                            if resp.status != "ok":
                                                print(f"Error [{resp.code}]: {resp.message}")
                                            else:
                                                print("Review successfully edited.")
                                        if action == "back":
                                            break

#=============================STORE PAGE=====================================================
                    if action == "visit_store":
                        page_start = 0
                        while True:
                            resp = client.list_games()
                            if resp.status == "ok":
                                game_catalogue = resp.payload.get("games", [])
                            else:
                                print(f"Error [{resp.code}]: {resp.message}")
                            print("Select the game to view details, leave a review, or to begin download.")
                            page_end = page_start + 2
                            page_slice = game_catalogue[page_start:page_end]
                            if not page_slice:
                                print("No games available.")
                                break
                            action = show_store_menu(page_slice, has_prev=page_start > 0,
                                                     has_next=page_end < len(game_catalogue))
#===========================================GAME_DETAILS===============================================
                            if isinstance(action, tuple) and action[0] == "select":
                                selected = page_slice[action[1]]
                                while True:
                                    action = show_game_menu()
                                    if action == "back":
                                        break
                                    if action == "view_game_details":
                                        show_game_detail([selected])
                                    if action == "download_game":
                                        try:
                                            resp = client.download_game(username, selected.get("game_name", ""))
                                            if isinstance(resp, Message) and resp.status != "ok":
                                                print(f"Error [{resp.code}]: {resp.message}")
                                            else:
                                                print("Download completed.")
                                        except Exception as e:
                                            print(f"Download failed: {e}")
                                    if action == "update_game":
                                        resp = client.update_game(username, selected.get("game_name", ""), require_installed=True)
                                        if resp.status != "ok":
                                            print(f"Error [{resp.code}]: {resp.message}")
                                        else:
                                            msg = resp.message or "Updated to latest version."
                                            print(msg)
                                    if action == "delete_game":
                                        resp = client.delete_game(username, selected.get("game_name", ""))
                                        if resp.status != "ok":
                                            print(f"Error [{resp.code}]: {resp.message}")
                                        else:
                                            print("Local copy deleted.")
                                    if action == "view_game_reviews":
                                        resp = client.list_game_review(selected.get("game_name", ""))
                                        if resp.status != "ok":
                                            print(f"Error [{resp.code}]: {resp.message}")
                                        else:
                                            reviews = resp.payload.get("reviews", []) or []
                                            if not reviews:
                                                print("No reviews for this game yet! Be the first to review!")
                                            else:
                                                for r in reviews:
                                                    print(f"{r.get('author')}: {r.get('content')}")
                                    if action == "review_game":
                                        resp = client.list_game_review(selected.get("game_name", ""))
                                        if resp.status != "ok":
                                            print(f"Error [{resp.code}]: {resp.message}")
                                        else:
                                            reviews = resp.payload.get("reviews", []) or []
                                            existing = next((r for r in reviews if r.get("author") == username), None)
                                            if existing:
                                                print(f"You have already reviewed this game. Review content: {existing.get('content', '')}, score = {existing.get('score', 0)}")
                                                print("Please go back to main menu and edit your review there.")
                                            else:
                                                elig = client.check_review_eligibility(username, selected.get("game_name", ""), selected.get("version"))
                                                if elig.status != "ok":
                                                    print(f"Error [{elig.code}]: {elig.message}")
                                                else:
                                                    content = user_review()
                                                    add_resp = client.add_review(username,selected.get("game_name", ""),content.get("content", ""),content.get("score"),selected.get("version"),)
                                                    if add_resp.status != "ok":
                                                        print(f"Error [{add_resp.code}]: {add_resp.message}")
                                                    else:
                                                        print("Review submitted.")
#===========================================GAME DETAILS END=================================================================
                            elif action == "next":
                                if page_end < len(game_catalogue):
                                    page_start += 2
                            elif action == "prev":
                                page_start = max(0, page_start - 2)
                            elif action == "back":
                                break

                    if action == "visit_lobby":
#===============================================LOBBY MENU==============================================================
                        in_room = False
                        curr_room_id = 0
                        game_name = ""
                        lobby_state = {"rooms": [], "players": []}

                        def wait_for_launch(room_id: int, username: str, is_host: bool, game_name: str):
                            launched = False
                            try:
                                while True:
                                    room_resp = client.get_room(room_id)
                                    if room_resp.status != "ok":
                                        print(f"Error [{room_resp.code}]: {room_resp.message}")
                                        return False
                                    room_info = room_resp.payload or {}
                                    status = room_info.get("status", "WAITING")
                                    ready_players = room_info.get("ready_players") or []
                                    room_port = room_info.get("port")
                                    room_token = room_info.get("token")
                                    host = room_info.get("host")
                                    if status == "IN_GAME" or (room_port and room_token):
                                        auto = client.launch_started_game(room_id, username)
                                        if auto.status == "ok":
                                            print(f"Game launching for room {room_id}...")
                                            launched = True
                                        else:
                                            print(f"Launch failed: [{auto.code}] {auto.message}")
                                        return launched
                                    needed_ready = [p for p in (room_info.get("players") or []) if p != host]
                                    all_ready = set(needed_ready).issubset(set(ready_players))
                                    if is_host and status == "WAITING" and all_ready and len(needed_ready) > 0:
                                        resp = client.start_game(room_id, game_name, username)
                                        if resp.status != "ok":
                                            print(f"Error starting game: [{resp.code}] {resp.message}")
                                            time.sleep(1.0)
                                            continue
                                    if status == "WAITING":
                                        print(f"Waiting for game start... Ready: {ready_players}, Host: {host}")
                                    time.sleep(1.0)
                            except KeyboardInterrupt:
                                print("\nCancelled waiting.")
                                return launched

                        def refresh_lobby(show: bool = True, print_if_changed: bool = False):
                            nonlocal lobby_state
                            prev_rooms = lobby_state.get("rooms", [])
                            prev_players = lobby_state.get("players", [])
                            rooms_resp = client.list_rooms()
                            players_resp = client.list_players()
                            lobby_state = {
                                "rooms": rooms_resp.payload.get("rooms", []) if rooms_resp.status == "ok" else [],
                                "players": players_resp.payload.get("players", []) if players_resp.status == "ok" else [],
                            }
                            changed = lobby_state.get("rooms", []) != prev_rooms or lobby_state.get("players", []) != prev_players
                            if show or (print_if_changed and changed):
                                print("\n=== Lobby Snapshot ===")
                                show_rooms(lobby_state.get("rooms", []))
                                print("Online players:", ", ".join(lobby_state.get("players", [])))
                            return changed

                        refresh_lobby(show=True)
                        while True:
                            refresh_lobby(show=False, print_if_changed=True)
                            lobby_action = show_lobby_menu()
                            if lobby_action == "back":
                                break
                            if lobby_action == "list_players":
                                refresh_lobby(show=False)
                                players = lobby_state.get("players", [])
                                print("Currently online players:")
                                for p in players:
                                    print(p)
                            if lobby_action == "list_rooms":
                                refresh_lobby(show=False)
                                show_rooms(lobby_state.get("rooms", []))
                            if lobby_action == "refresh":
                                refresh_lobby(show=True)
                            elif lobby_action == "create_room":
                                downloaded = client.list_local_games(username)
                                if not downloaded:
                                    print("No downloaded games found. Visit the store to download games first.")
                                    continue
                                action = show_local_game_menu(downloaded, "\nSelect a game to play.")
                                if action == "back":
                                    continue
                                if isinstance(action, tuple) and action[0] == "select":
                                    selected = downloaded[action[1]]
                                    game_name = selected.get("game_name", "")
                                else:
                                    # unexpected response; restart loop
                                    continue
                                if not game_name:
                                    print("No game selected. Please try again.")
                                    continue

                                room_name = input("Enter room name: ").strip()
                                resp = client.create_room(username, game_name, room_name)
                                if resp.status == "ok":
                                    in_room = True
                                    curr_room_id = resp.payload.get('room', {}).get('room_id', 0)
                                    print(f"Room created with id {curr_room_id}")
                                    refresh_lobby(show=True)
                                    break
                                else:
                                    print(f"Error [{resp.code}]: {resp.message}")
                            elif lobby_action == "join_room":
                                room_id_raw = input("Enter room id to join: ").strip()
                                try:
                                    room_id = int(room_id_raw)
                                except ValueError:
                                    print("Invalid room id.")
                                    continue
                                resp = client.join_room(username, room_id)
                                if resp.status == "ok":
                                    print(f"Joined room {room_id}.")
                                    in_room = True
                                    curr_room_id = room_id
                                    game_name = client.get_room(curr_room_id).payload["metadata"]["game_name"]
                                    refresh_lobby(show=False)
                                    break
                                else:
                                    print(f"Error [{resp.code}]: {resp.message}")
                        if in_room:
#=============================================IN ROOM============================================================
                            launched = False
                            waiting_msg_shown = False
                            while True:
                                room_resp = client.get_room(curr_room_id)
                                if room_resp.status != "ok":
                                    print(f"Error [{room_resp.code}]: {room_resp.message}")
                                    in_room = False
                                    curr_room_id = 0
                                    break
                                room_info = room_resp.payload or {}
                                room_host = room_info.get("host")
                                room_status = room_info.get("status", "WAITING")
                                room_port = room_info.get("port")
                                room_token = room_info.get("token")
                                ready_players = room_info.get("ready_players") or []
                                game_name = (room_info.get("metadata") or {}).get("game_name", game_name) or game_name
                                is_host = room_host == username
                                if not is_host and room_status == "WAITING":
                                    is_ready = username in ready_players
                                    state = "READY" if is_ready else "NOT READY"
                                    print(f"Your status: {state}. Host: {room_host}. Ready players: {ready_players}")
                                if is_host and room_status == "WAITING":
                                    print(f"Ready players: {ready_players}")

                                ready_to_launch = room_status == "IN_GAME" or (room_port and room_token)
                                if ready_to_launch and not launched:
                                    auto = client.launch_started_game(curr_room_id, username)
                                    if auto.status == "ok":
                                        launched = True
                                        print(f"Game already in progress; launched client for room {curr_room_id}.")
                                    else:
                                        print(f"Game in progress but launch failed: [{auto.code}] {auto.message}")
                                if launched and room_status == "IN_GAME":
                                    if not waiting_msg_shown:
                                        print("Game in progress... waiting to return to room menu after it ends.")
                                        waiting_msg_shown = True
                                    time.sleep(1.0)
                                    continue
                                if launched and room_status != "IN_GAME":
                                    launched = False
                                    waiting_msg_shown = False

                                ready_players = room_info.get("ready_players") or []
                                room_action = show_room_menu(
                                    is_host,
                                    room_status,
                                    can_ready=(not is_host and room_status == "WAITING" and username not in ready_players),
                                )
                                if room_action == "leave_room":
                                    try:
                                        resp = client.leave_room(username, curr_room_id)
                                        if resp.status == "ok":
                                            if resp.payload.get("host") == "":
                                                print("Room deleted; no host remaining.")
                                            else:
                                                print(f"Left room {curr_room_id}. New host: {resp.payload.get('host')}")
                                        else:
                                            print(f"Error [{resp.code}]: {resp.message}")
                                    except Exception as e:
                                        print(f"Error leaving room: {e}")
                                    in_room = False
                                    curr_room_id = 0
                                    break
                                if room_action == "ready":
                                    resp = client.set_ready(username, curr_room_id, ready=True)
                                    if resp.status == "ok":
                                        ready_players = resp.payload.get("ready_players", ready_players)
                                        print(f"Set ready. Ready players: {ready_players}")
                                        wait_for_launch(curr_room_id, username, is_host=False, game_name=game_name)
                                    else:
                                        print(f"Error [{resp.code}]: {resp.message}")
                                    time.sleep(0.5)
                                    continue
                                if room_action == "start_game":
                                    resp = client.start_game(curr_room_id, game_name, username)
                                    if resp.status != "ok":
                                        print(f"Error [{resp.code}]: {resp.message}")
                                        time.sleep(1.0)
                                    # wait/poll for launch or readiness
                                    wait_for_launch(curr_room_id, username, is_host=True, game_name=game_name)
                                    continue
                                if room_action == "launch_game":
                                    resp = client.launch_started_game(curr_room_id, username)
                                    if resp.status == "ok":
                                        print(f"Launched local game client for room {curr_room_id}. When the game ends, go back to the lobby if you need to leave the room.")
                                        launched = True
                                        waiting_msg_shown = False
                                        # loop will wait until game ends
                                        continue
                                    else:
                                        print(f"Error [{resp.code}]: {resp.message}")
                                        time.sleep(1.0)
                    if action == "logout":
                        resp = client.logout()
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
                client.logout()
            except Exception:
                pass
        print("\nInterrupted. Exiting user client.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
