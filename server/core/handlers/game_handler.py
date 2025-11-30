from server.core.game_manager import GameManager
def list_game(payload: dict, mgr: GameManager):
    """
    Handles game listing
    """
    game_entries = mgr.list_games(payload["username"], payload["role"])
    return {"status": "ok", "code": 0, "payload": {"games": game_entries}}

def upload_game(payload: dict, mgr: GameManager):
    """
    Handles game creation
    """
    new_entry = mgr.create_game(
        payload["username"],
        payload["game_name"],
        payload["type"],
        payload.get("description", ""),
        int(payload.get("max_players", 0) or 0),
    )
    return {"status": "ok", "code": 0, "payload": {"game": new_entry}}

def detail_game(payload: dict, mgr: GameManager):
    """
    Handles game details
    """
    game_name = payload["game_name"]
    row = mgr.get_game(game_name)
    if not row:
        return {"status": "error", "code": 103, "message": "NOT_FOUND"}
    return {"status": "ok", "code": 0, "payload": {"game": row}}
