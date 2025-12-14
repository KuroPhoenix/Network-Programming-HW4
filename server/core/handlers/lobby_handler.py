from dataclasses import asdict


from server.core.room_genie import RoomGenie
from server.core.game_launcher import GameLauncher
from server.core.game_manager import GameManager
from server.core.auth import Authenticator

def list_rooms(genie: RoomGenie) -> dict:
    rooms = genie.list_rooms()
    return {"status": "ok", "code": 0, "payload": {"rooms": rooms}}

def list_players(payload: dict, auth: Authenticator) -> dict:
    role = payload.get("role", "")
    players = auth.list_online_players(role)
    return {"status": "ok", "code": 0, "payload": {"players": players}}

def get_room(payload: dict, genie: RoomGenie) -> dict:
    room = genie.get_room(payload.get("room_id"))
    data = asdict(room)
    data["ready_players"] = list(room.ready_players)
    return {"status": "ok", "code": 0, "payload": data}

def create_room(payload: dict, gmgr: GameManager, genie: RoomGenie) -> dict:
    username = payload.get("username", "")
    game_name = payload.get("game_name", "")
    room_name = payload.get("room_name")
    if not username or not game_name:
        raise ValueError("username and game_name required")
    game = gmgr.get_game(game_name)
    if not game:
        return {"status": "error", "code": 103, "message": "NOT_FOUND"}
    metadata = {
        "game_name": game.get("game_name"),
        "version": game.get("version"),
        "max_players": game.get("max_players"),
        "type": game.get("type"),
    }
    room = genie.create_room(username, room_name, metadata, gmgr)
    data = asdict(room)
    data["ready_players"] = list(room.ready_players)
    return {"status": "ok", "code": 0, "payload": {"room": data}}


def join_room(payload: dict, genie: RoomGenie) -> dict:
    username = payload.get("username", "")
    room_id = int(payload.get("room_id", 0))
    if not username or room_id <= 0:
        raise ValueError("username and room_id required")
    genie.join_room_as_player(username, room_id)
    return {"status": "ok", "code": 0, "payload": {"room_id": room_id}}

def ready_room(payload: dict, genie: RoomGenie) -> dict:
    username = payload.get("username", "")
    room_id = int(payload.get("room_id", 0))
    ready = bool(payload.get("ready", True))
    if not username or room_id <= 0:
        raise ValueError("username and room_id required")
    res = genie.set_ready(username, room_id, ready)
    return {"status": "ok", "code": 0, "payload": res}


def leave_room(payload: dict, genie: RoomGenie, gmLauncher: GameLauncher | None = None) -> dict:
    username = payload.get("username", "")
    room_id = int(payload.get("room_id", 0))
    if not username or room_id <= 0:
        raise ValueError("username and room_id required")
    host = genie.leave_room(username, room_id, gmLauncher)
    return {"status": "ok", "code": 0, "payload": {"room_id": room_id, "host": host}}
