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