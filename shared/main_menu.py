from shared.input_helpers import read_choice

MAIN_OPTIONS = [
    ("Register", "register"),
    ("Login", "login"),
    ("Exit", "exit"),
]


def show_main_menu():
    print("\n=== Main Menu ===")
    for idx, (label, _) in enumerate(MAIN_OPTIONS, 1):
        print(f"{idx}. {label}")
    choice = read_choice(1, len(MAIN_OPTIONS))
    return MAIN_OPTIONS[choice - 1][1]