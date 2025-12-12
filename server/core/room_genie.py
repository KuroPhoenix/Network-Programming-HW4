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
    spectators: list[str] = field(default_factory=list)
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
            return [asdict(room) for room in self.rooms.values()]

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
            return room

    def get_room(self, room_id: int) -> Room:
        room = self.rooms.get(room_id)
        if not room:
            raise ValueError(f"Room ID: {room_id} does not exist.")
        return room

    def _watch_room(self, room_id, launcher, interval=0.5):
        try:
            while True:
                res = launcher.describe(room_id)
                proc = res.proc if res else None
                if not proc:
                    break
                if proc.poll() is not None:  # exited
                    code = proc.returncode
                    with self.lock:
                        room = self.rooms.get(room_id)
                        if room:
                            room.status = "WAITING"
                            room.port = None
                            room.token = None
                            room.server_pid = None
                    launcher.stop_room(room_id)
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
            room.status = "IN_GAME"
            running_result = gmLauncher.launch_room(room_id, room.host, room.metadata, room.players)
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
            return {"room": asdict(room), "launch": launch_info}

    def _clear_running(self, room: Room, gmLauncher: GameLauncher):
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
            self._clear_running(room, gmLauncher)
            if reviewMgr:
                reviewMgr.add_play_history(str(room.metadata["game_name"]), str(room.metadata["version"]), winner)
                reviewMgr.add_play_history(str(room.metadata["game_name"]), str(room.metadata["version"]), loser)

    def game_ended_with_error(self, err_msg: str, room_id: int, gmLauncher: GameLauncher):
        with self.lock:
            room = self.get_room(room_id)
            room.status = "WAITING"
            self._clear_running(room, gmLauncher)
        logger.error(err_msg)

    def join_room_as_player(self, username: str, target_room_id: int):
        with self.lock:
            room = self.get_room(target_room_id)
            if username in room.players or username in room.spectators:
                return
            if room.max_players is not None and len(room.players) >= room.max_players:
                raise ValueError(f"Room ID: {room.room_id} {room.room_name} is full.")
            room.players.append(username)

    def join_room_as_spectator(self, username: str, target_room_id: int):
        with self.lock:
            room = self.get_room(target_room_id)
            if username in room.players or username in room.spectators:
                return
            room.spectators.append(username)

    def _delete_room(self, room_id: int, gmLauncher: GameLauncher | None = None):
        with self.lock:
            room = self.rooms.get(room_id)
            if not room:
                raise ValueError(f"Room ID: {room_id} does not exist.")
            if gmLauncher and room.status == "IN_GAME":
                self._clear_running(room, gmLauncher)
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
            elif username in room.spectators:
                room.spectators.remove(username)
            else:
                raise ValueError(f"User {username} not in room {target_room_id}")

            if was_host:
                if room.players:
                    room.host = room.players[0]
                elif room.spectators:
                    new_host = room.spectators.pop(0)
                    room.host = new_host
                    room.players.append(new_host)
                else:
                    self._delete_room(target_room_id, gmLauncher)
                    return ""

            return room.host
