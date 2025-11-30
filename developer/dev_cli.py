from developer.api.dev_api import DevClient
from user.ui.main_menu import show_main_menu


def prompt_credentials():
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    return username, password


def main():
    client = DevClient()
    try:
        while True:
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
            else:
                print(f"Error [{resp.code}]: {resp.message}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
