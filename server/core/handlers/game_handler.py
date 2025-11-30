from server.core.game_manager import GameManager
def list_dev(payload: dict, mgr: GameManager):
    """
    Handles game listing
    """
    game_entries = mgr.list_games(payload["username"])
    return {"status": "ok", "code": 0, "payload": {"games": game_entries}}

def create_dev(payload: dict, mgr: GameManager):
    """
    Handles game creation
    """
    new_entry = mgr.create_game(payload["username"], payload["game_name"], payload["type"])
    return {"status": "ok", "code": 0, "payload": {"game": new_entry}}