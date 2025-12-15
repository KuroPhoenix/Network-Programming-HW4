from base64 import b64decode, b64encode
from server.core.game_manager import GameManager
from server.core.storage_manager import StorageManager
from server.core.game_launcher import GameLauncher
from server.core.room_genie import RoomGenie
from server.core.review_manager import ReviewManager
from loguru import logger


def report_game(payload: dict, genie: RoomGenie, gmLauncher: GameLauncher, reviewMgr: ReviewManager) -> dict:
    """
    Receives game status updates from game servers and forwards to RoomGenie.
    Expected payload:
      status: RUNNING | END | ERROR
      room_id: int
      winner/loser: usernames (for END)
      err_msg/reason: strings (for ERROR/INFO)
    """
    status = (payload.get("status") or "").upper()
    room_id = payload.get("room_id") or payload.get("room")
    logger.info(f"report_game room_id={room_id} status={status} keys={list(payload.keys())}")
    if room_id is None:
        raise ValueError("room_id required")
    # Verify report_token against room
    try:
        room = genie.get_room(int(room_id))
    except Exception as e:
        logger.warning(f"report_game could not find room {room_id}: {e}")
        return {"status": "error", "code": 103, "message": str(e)}
    report_token = payload.get("report_token")
    if report_token and room.token and report_token != room.token:
        logger.warning(f"invalid report token for room {room_id}")
        return {"status": "error", "code": 101, "message": "invalid report token"}

    try:
        if status == "RUNNING":
            return {"status": "ok", "code": 0, "payload": {"room_id": room_id, "status": status}}
        if status == "END":
            genie.game_ended_normally(payload.get("winner", ""), payload.get("loser", ""), int(room_id), gmLauncher, reviewMgr)
            logger.info(f"room {room_id} reported END")
            return {"status": "ok", "code": 0, "payload": {"room_id": room_id, "status": status}}
        if status == "ERROR":
            err_msg = payload.get("err_msg") or payload.get("reason") or "unknown error"
            genie.game_ended_with_error(err_msg, int(room_id), gmLauncher)
            logger.error(f"room {room_id} reported ERROR: {err_msg}")
            return {"status": "ok", "code": 0, "payload": {"room_id": room_id, "status": status, "err_msg": err_msg}}
        return {"status": "error", "code": 100, "message": "UNKNOWN_STATUS"}
    except Exception as exc:
        logger.exception(f"report_game handling failed for room {room_id}: {exc}")
        return {"status": "error", "code": 199, "message": str(exc)}

def start_game(payload: dict, gmLauncher: GameLauncher, genie: RoomGenie, gmgr: GameManager) -> dict:
    """
    From room Genie: def start_game(self, room_id: int, gmLauncher: GameLauncher):
    :param gmgr:
    :param gmLauncher:
    :param payload:
    :param genie:
    :return:
    """
    username = payload.get("username")
    if not username:
        raise ValueError("username required")
    room = genie.get_room(payload["room_id"])
    if room.host != username:
        raise ValueError("only host can start the game")
    required_players = 2 if (room.max_players is None or room.max_players >= 2) else 1
    if len(room.players) < required_players:
        raise ValueError(f"Not enough players to start. Need at least {required_players}.")
    logger.info(f"start_game request user={username} room_id={room.room_id} players={room.players}")
    try:
        start_session_info = genie.start_game(payload["room_id"], gmLauncher, gmgr)
    except ValueError as e:
        logger.warning(f"start_game validation failed room {room.room_id}: {e}")
        return {"status": "error", "code": 101, "message": str(e)}
    except Exception as exc:
        logger.exception(f"start_game failed for room {room.room_id}: {exc}")
        return {"status": "error", "code": 199, "message": str(exc)}
    return {"status": "ok", "code": 0, "payload": start_session_info}

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
        "size_bytes": int(payload.get("size_bytes", 0) or 0) or None,
        "checksum": payload.get("checksum"),
    }
    upload_id = smgr.init_upload_verification(expected)
    chunk_size = smgr.uploadID_to_info[upload_id].chunk_size if hasattr(smgr, "uploadID_to_info") else 64 * 1024
    return {"status": "ok", "code": 0, "payload": {"upload_id": upload_id, "chunk_size": chunk_size}}

def download_begin(payload: dict, gmgr: GameManager, smgr: StorageManager) -> dict:
    game_name = payload.get("game_name")
    if not game_name:
        raise ValueError("game_name required")
    row = gmgr.get_game(game_name)
    if not row:
        return {"status": "error", "code": 103, "message": "NOT_FOUND"}
    download_id = smgr.init_download_verification(row)
    meta = getattr(smgr, "download_meta_cache", {}).get(download_id, {})
    chunk_size = 64 * 1024
    payload_resp = {"download_id": download_id, "game": row, "chunk_size": chunk_size}
    if meta:
        payload_resp.update(meta)
    return {"status": "ok", "code": 0, "payload": payload_resp}

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
    try:
        smgr.append_chunk(upload_id, data, seq)
        return {"status": "ok", "code": 0, "payload": {"upload_id": upload_id, "seq": seq}}
    except ValueError as e:
        msg = str(e)
        if "out-of-order" in msg:
            return {"status": "error", "code": 120, "message": msg}
        return {"status": "error", "code": 105, "message": msg}


def upload_end(payload: dict, gmgr: GameManager, smgr: StorageManager) -> dict:
    upload_id = payload["upload_id"]
    try:
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
    except ValueError as e:
        msg = str(e)
        if "checksum mismatch" in msg:
            return {"status": "error", "code": 121, "message": msg}
        if "size mismatch" in msg or "size overflow" in msg:
            return {"status": "error", "code": 105, "message": msg}
        return {"status": "error", "code": 199, "message": msg}

def delete_game(payload: dict, gmgr: GameManager, smgr: StorageManager, reviewMgr=None) -> dict:
    username = payload.get("username")
    game_name = payload.get("game_name")
    if not username or not game_name:
        raise ValueError("username and game_name required")
    folders, deleted_rows = gmgr.delete_game(username, game_name)
    removed = smgr.delete_game(game_name, folders)
    if reviewMgr:
        try:
            reviewMgr.delete_game_reviews(game_name)
        except Exception as e:
            logger.warning(f"Failed to purge reviews for {game_name}: {e}")
    return {
        "status": "ok",
        "code": 0,
        "payload": {"game_name": game_name, "deleted_versions": deleted_rows, "removed_paths": removed},
    }


def detail_game(payload: dict, mgr: GameManager):
    """
    Handles game details
    """
    game_name = payload["game_name"]
    row = mgr.get_game(game_name)
    if not row:
        return {"status": "error", "code": 103, "message": "NOT_FOUND"}
    # Enrich with fields expected by store UI
    row["latest_version"] = row.get("version")
    row.setdefault("status", "ONLINE")
    return {"status": "ok", "code": 0, "payload": {"game": row}}


def latest_version(payload: dict, gmgr: GameManager, smgr: StorageManager) -> dict:
    game_name = payload.get("game_name")
    if not game_name:
        raise ValueError("game_name required")
    row = gmgr.get_game(game_name)
    if not row:
        return {"status": "error", "code": 103, "message": "NOT_FOUND"}
    stats = smgr.describe_package(game_name, str(row.get("version")), row.get("game_folder"))
    resp_payload = {
        "version": str(row.get("version")),
        "size_bytes": stats.get("size_bytes", 0),
        "checksum": stats.get("checksum"),
    }
    return {"status": "ok", "code": 0, "payload": resp_payload}
