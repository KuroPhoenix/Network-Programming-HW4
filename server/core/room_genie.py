from dataclasses import asdict, dataclass, field
from loguru import logger

from server.core.config import USER_SERVER_HOST
from server.core.game_launcher import GameLauncher
from server.core.game_manager import GameManager
from typing import Literal, Optional
import threading
import time
from pathlib import Path

from server.core.review_manager import ReviewManager
from shared.logger import ensure_global_logger, log_dir

# Module-specific logging
LOG_DIR = log_dir()
ensure_global_logger()
logger.add(LOG_DIR / "room_genie.log", rotation="1 MB", level="INFO", filter=lambda r: r["file"] == "room_genie.py")
logger.add(LOG_DIR / "room_genie_errors.log", rotation="1 MB", level="ERROR", filter=lambda r: r["file"] == "room_genie.py")

@dataclass
class Room:
    room_id: int
    host: str
    room_name: str
    token: Optional[str] = None
    players: list[str] = field(default_factory=list)
    ready_players: set[str] = field(default_factory=set)
    metadata: dict = field(default_factory=dict)
    max_players: Optional[int] = None
    status: Literal["WAITING", "IN_GAME"] = "WAITING"
    port: Optional[int] = field(default=None)
    server_pid: Optional[int] = field(default=None)
    created_at: float = field(default_factory=time.time)
    wins: dict = field(default_factory=dict)
    losses: dict = field(default_factory=dict)

class RoomGenie:
    def __init__(self):
        self.rooms: dict[int, Room] = {}
        self.next_room_id = 1
        self.lock = threading.Lock()

    def list_rooms(self) -> list[dict]:
        with self.lock:
            rooms = []
            for room in self.rooms.values():
                data = asdict(room)
                data["ready_players"] = list(room.ready_players)
                rooms.append(data)
            logger.debug(f"list_rooms returning {len(rooms)} rooms")
            return rooms

    def remove_user_from_rooms(self, username: str, gmLauncher: GameLauncher | None = None) -> list[int]:
        """
        Remove a user from any rooms they occupy. If they were host and no players remain,
        the room is deleted (and any running game is stopped). Returns list of room_ids affected.
        """
        affected: list[int] = []
        with self.lock:
            for room_id, room in list(self.rooms.items()):
                if username not in room.players:
                    continue
                affected.append(room_id)
                room.players = [p for p in room.players if p != username]
                was_host = room.host == username
                logger.info(f"removing {username} from room {room_id} (host={room.host}, remaining={room.players})")
                if was_host:
                    if room.players:
                        logger.info(f"transferring host of room {room_id} to {room.players[0]}")
                        room.host = room.players[0]
                    else:
                        if gmLauncher and room.status == "IN_GAME":
                            self._clear_running(room, gmLauncher)
                        logger.info(f"deleting empty room {room_id} after host left")
                        del self.rooms[room_id]
                        continue
                if not room.players:
                    if gmLauncher and room.status == "IN_GAME":
                        self._clear_running(room, gmLauncher)
                    logger.info(f"deleting empty room {room_id}")
                    del self.rooms[room_id]
        return affected

    def create_room(self, host: str, room_name: str, metadata: dict, gmgr: GameManager) -> Room:
        game_name = metadata.get("game_name")
        if not game_name:
            raise ValueError("game_name required")
        latest = gmgr.get_game(game_name)
        if not latest or latest.get("version") is None:
            raise ValueError("game not found or no version available")

        room_meta = {
            "game_name": latest["game_name"],
            "version": latest["version"],
            # lock room to this version
            "max_players": latest.get("max_players"),
            "type": latest.get("type"),
        }

        with self.lock:
            room_id = self.next_room_id
            self.next_room_id += 1
            max_players = room_meta.get("max_players")
            if isinstance(max_players, int) and max_players <= 0:
                max_players = None
            room = Room(room_id, host, room_name, players=[host], metadata=room_meta, max_players=max_players)
            self.rooms[room_id] = room
            logger.info(f"created room {room_id} '{room_name}' for game {room_meta['game_name']} v{room_meta['version']} host={host}")
            return room

    def get_room(self, room_id: int) -> Room:
        room = self.rooms.get(room_id)
        if not room:
            raise ValueError(f"Room ID: {room_id} does not exist.")
        return room

    def _watch_room(self, room_id, launcher, interval=0.5):
        logger.debug(f"starting watcher for room {room_id}")
        try:
            while True:
                try:
                    res = launcher.describe(room_id)
                    proc = res.proc if res else None
                except Exception as e:
                    logger.exception(f"room watcher describe failed for room {room_id}: {e}")
                    break
                if not proc:
                    logger.debug(f"room watcher exiting for {room_id}: no running process found")
                    break
                try:
                    if proc.poll() is not None:  # exited
                        code = proc.returncode
                        with self.lock:
                            room = self.rooms.get(room_id)
                            if room:
                                room.status = "WAITING"
                                room.port = None
                                room.token = None
                                room.server_pid = None
                        logger.info(f"room {room_id} server exited with code {code}")
                        launcher.stop_room(room_id)
                        break
                except Exception as e:
                    logger.exception(f"room watcher poll failed for room {room_id}: {e}")
                    break
                time.sleep(interval)
        finally:
            with self.lock:
                room = self.rooms.get(room_id)
                if room:
                    room.status = "WAITING"
                    room.port = None
                    room.token = None
                    room.server_pid = None
            logger.debug(f"watcher cleanup stopping room {room_id}")
            launcher.stop_room(room_id)

    def start_game(self, room_id: int, gmLauncher: GameLauncher, gmgr: GameManager) -> dict:
        with self.lock:
            room = self.get_room(room_id)
            if room.status == "IN_GAME":
                logger.error("Game already started")
                raise ValueError("Game already started")
            latest_game = gmgr.get_game(room.metadata.get("game_name"))
            if not latest_game or latest_game.get("version") is None:
                raise ValueError("game not found or no version available in store.")
            if room.metadata.get("version") != latest_game.get("version"):
                raise ValueError("game version mismatch")
            required_players = 2 if (room.max_players is None or room.max_players >= 2) else 1
            if len(room.players) < required_players:
                raise ValueError(f"Not enough players to start. Need at least {required_players}.")
            needed_ready = [p for p in room.players if p != room.host]
            if needed_ready and not set(needed_ready).issubset(room.ready_players):
                raise ValueError("Not all players are ready.")
            room.status = "IN_GAME"
            logger.info(f"starting game for room {room_id} host={room.host} players={room.players}")
            try:
                running_result = gmLauncher.launch_room(room_id, room.host, room.metadata, room.players)
            except Exception:
                # rollback the state so lobby remains usable after a failed launch
                room.status = "WAITING"
                room.port = None
                room.token = None
                room.server_pid = None
                logger.exception(f"failed to launch room {room_id}; reverted to WAITING state")
                raise
            room.port = running_result.port
            room.server_proc = running_result.proc
            room.server_pid = room.server_proc.pid
            room.token = running_result.token
            launch_info = {
                "host": USER_SERVER_HOST,
                "port": room.port,
                "token": room.token,
                "game_name": room.metadata.get("game_name"),
                "version": room.metadata.get("version"),
            }
            t = threading.Thread(target=self._watch_room, args=(room_id, gmLauncher), daemon=True)
            t.start()
            room_data = asdict(room)
            room_data["ready_players"] = list(room.ready_players)
            return {"room": room_data, "launch": launch_info}

    def _clear_running(self, room: Room, gmLauncher: GameLauncher):
        logger.debug(f"clearing running state for room {room.room_id}")
        gmLauncher.stop_room(room.room_id)
        room.port = None
        room.token = None
        room.server_pid = None
        if hasattr(room, "server_proc"):
            room.server_proc = None  # type: ignore[attr-defined]

    def game_ended_normally(self, winner: str, loser: str, room_id: int, gmLauncher: GameLauncher, reviewMgr: ReviewManager | None = None):
        with self.lock:
            room = self.get_room(room_id)
            room.status = "WAITING"
            room.wins[winner] = room.wins.get(winner, 0) + 1
            room.losses[loser] = room.losses.get(loser, 0) + 1
            room.ready_players.clear()
            self._clear_running(room, gmLauncher)
            if reviewMgr:
                reviewMgr.add_play_history(str(room.metadata["game_name"]), str(room.metadata["version"]), winner)
                reviewMgr.add_play_history(str(room.metadata["game_name"]), str(room.metadata["version"]), loser)
        logger.info(f"room {room_id} ended normally winner={winner} loser={loser}")

    def game_ended_with_error(self, err_msg: str, room_id: int, gmLauncher: GameLauncher):
        with self.lock:
            room = self.get_room(room_id)
            room.status = "WAITING"
            room.ready_players.clear()
            self._clear_running(room, gmLauncher)
        logger.error(f"room {room_id} ended with error: {err_msg}")

    def join_room_as_player(self, username: str, target_room_id: int):
        with self.lock:
            room = self.get_room(target_room_id)
            if username in room.players:
                logger.info(f"user {username} already in room {target_room_id}")
                return
            if room.max_players is not None and len(room.players) >= room.max_players:
                raise ValueError(f"Room ID: {room.room_id} {room.room_name} is full.")
            room.players.append(username)
            room.ready_players.discard(username)
            logger.info(f"user {username} joined room {target_room_id}; players now={room.players}")

    def _delete_room(self, room_id: int, gmLauncher: GameLauncher | None = None):
        with self.lock:
            room = self.rooms.get(room_id)
            if not room:
                raise ValueError(f"Room ID: {room_id} does not exist.")
            if gmLauncher and room.status == "IN_GAME":
                self._clear_running(room, gmLauncher)
            logger.info(f"deleting room {room_id}")
            del self.rooms[room_id]
            return True

    def leave_room(self, username: str, target_room_id: int, gmLauncher: GameLauncher | None = None) -> str:
        """
        Returns the name of the room host; empty string if the room was deleted.
        """
        with self.lock:
            room = self.get_room(target_room_id)
            was_host = room.host == username

            if username in room.players:
                room.players.remove(username)
                room.ready_players.discard(username)
            else:
                raise ValueError(f"User {username} not in room {target_room_id}")

            if was_host:
                if room.players:
                    room.host = room.players[0]
                    logger.info(f"{username} left room {target_room_id}; host transferred to {room.host}")
                else:
                    self._delete_room(target_room_id, gmLauncher)
                    logger.info(f"{username} left room {target_room_id}; room deleted because it became empty")
                    return ""
            logger.info(f"{username} left room {target_room_id}; remaining players={room.players}")
            return room.host

    def set_ready(self, username: str, room_id: int, ready: bool = True) -> dict:
        with self.lock:
            room = self.get_room(room_id)
            if username not in room.players:
                raise ValueError(f"User {username} not in room {room_id}")
            if ready:
                room.ready_players.add(username)
            else:
                room.ready_players.discard(username)
            logger.info(f"player {username} ready={ready} in room {room_id}; ready now={room.ready_players}")
            return {"room_id": room_id, "ready_players": list(room.ready_players)}
