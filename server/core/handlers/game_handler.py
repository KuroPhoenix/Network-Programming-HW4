from base64 import b64decode, b64encode
from server.core.game_manager import GameManager
from server.core.storage_manager import StorageManager


def list_game(payload: dict, mgr: GameManager):
    """
    Handles game listing
    """
    role = payload.get("role", "")
    username = payload.get("username", "")
    game_entries = mgr.list_games(username, role)
    return {"status": "ok", "code": 0, "payload": {"games": game_entries}}


def upload_metadata(payload: dict, gmgr: GameManager):
    """
    Handles game creation on metadata scale
    """
    new_entry = gmgr.create_metadata(
        payload["username"],
        payload["game_name"],
        payload["type"],
        payload.get("description", ""),
        int(payload.get("max_players", 0) or 0),
    )
    return {"status": "ok", "code": 0, "payload": {"game": new_entry}}


def upload_begin(payload: dict, smgr: StorageManager) -> dict:
    expected = {
        "game_name": payload["game_name"],
        "type": payload["type"],
        "version": str(payload.get("version", "")),
        "description": payload.get("description", ""),
        "max_players": int(payload.get("max_players", 0) or 0),
    }
    upload_id = smgr.init_upload_verification(expected)
    return {"status": "ok", "code": 0, "payload": {"upload_id": upload_id}}

def download_begin(payload: dict, gmgr: GameManager, smgr: StorageManager) -> dict:
    game_name = payload.get("game_name")
    if not game_name:
        raise ValueError("game_name required")
    row = gmgr.get_game(game_name)
    if not row:
        return {"status": "error", "code": 103, "message": "NOT_FOUND"}
    download_id = smgr.init_download_verification(row)
    return {"status": "ok", "code": 0, "payload": {"download_id": download_id, "game": row}}

def download_chunk(payload: dict, smgr: StorageManager) -> dict:
    download_id = payload["download_id"]
    seq = int(payload.get("seq", 0))
    chunk, done = smgr.read_download_chunk(download_id, seq)
    enc = b64encode(chunk).decode("ascii")
    return {
        "status": "ok",
        "code": 0,
        "payload": {"download_id": download_id, "seq": seq, "data": enc, "done": done},
    }

def download_end(payload: dict, smgr: StorageManager) -> dict:
    download_id = payload.get("download_id")
    smgr.complete_download(download_id)
    return {"status": "ok", "code": 0, "payload": {"download_id": download_id}}

def upload_chunk(payload: dict, smgr: StorageManager) -> dict:
    upload_id = payload["upload_id"]
    seq = int(payload.get("seq", 0))
    data = b64decode(payload.get("data", ""))
    smgr.append_chunk(upload_id, data, seq)
    return {"status": "ok", "code": 0, "payload": {"upload_id": upload_id, "seq": seq}}


def upload_end(payload: dict, gmgr: GameManager, smgr: StorageManager) -> dict:
    upload_id = payload["upload_id"]
    result = smgr.finalise_upload(upload_id)
    manifest = result["manifest"]
    gmgr.create_game(
        payload["username"],
        manifest["game_name"],
        manifest["type"],
        manifest["version"],
        {
            "path": result["path"],
            "manifest": result["manifest"],
            "description": manifest.get("description", ""),
            "max_players": manifest.get("max_players", 0),
        },
    )
    return {"status": "ok", "code": 0, "payload": result}


def detail_game(payload: dict, mgr: GameManager):
    """
    Handles game details
    """
    game_name = payload["game_name"]
    row = mgr.get_game(game_name)
    if not row:
        return {"status": "error", "code": 103, "message": "NOT_FOUND"}
    return {"status": "ok", "code": 0, "payload": {"game": row}}
