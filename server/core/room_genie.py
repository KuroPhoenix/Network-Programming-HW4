from dataclasses import asdict, dataclass, field
from loguru import logger

from server.core.config import USER_SERVER_HOST
from server.core.game_launcher import GameLauncher
from server.core.game_manager import GameManager
from typing import Literal, Optional
import threading
import time
from pathlib import Path
import secrets
import uuid
import shutil

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
    client_token: Optional[str] = None
    report_token: Optional[str] = None
    match_id: Optional[str] = None
    players: list[str] = field(default_factory=list)
    ready_players: set[str] = field(default_factory=set)
    metadata: dict = field(default_factory=dict)
    max_players: Optional[int] = None
    status: Literal["WAITING", "STARTING", "IN_GAME", "ENDING"] = "WAITING"
    port: Optional[int] = field(default=None)
    server_pid: Optional[int] = field(default=None)
    created_at: float = field(default_factory=time.time)
    wins: dict = field(default_factory=dict)
    losses: dict = field(default_factory=dict)
    launch_seq: int = 0
    launch_started_at: Optional[float] = None
    startup_timeout: Optional[float] = None
    last_heartbeat: Optional[float] = None
    registered: bool = False
    last_error: Optional[str] = None
    players_json_dir: Optional[str] = None

class RoomGenie:
    def __init__(self):
        self.rooms: dict[int, Room] = {}
        self.next_room_id = 1
        self.lock = threading.Lock()
        self._cleanup_stale_match_dirs()

    def list_rooms(self) -> list[dict]:
        with self.lock:
            rooms = []
            for room in self.rooms.values():
                data = self._snapshot_room_locked(room, include_launch_info=False)
                rooms.append(data)
            logger.debug(f"list_rooms returning {len(rooms)} rooms")
            return rooms

    def _snapshot_room_locked(self, room: Room, *, include_launch_info: bool) -> dict:
        data = asdict(room)
        data["ready_players"] = list(room.ready_players)
        data.pop("report_token", None)
        if room.status != "IN_GAME" or not include_launch_info:
            data["port"] = None
            data["client_token"] = None
        if room.status not in ("STARTING", "IN_GAME"):
            data["match_id"] = None
        return data

    def snapshot_room(self, room_id: int, *, include_launch_info: bool = True) -> dict:
        with self.lock:
            room = self.get_room(room_id)
            return self._snapshot_room_locked(room, include_launch_info=include_launch_info)

    def remove_user_from_rooms(self, username: str, gmLauncher: GameLauncher | None = None) -> list[int]:
        """
        Remove a user from any rooms they occupy. If they were host and no players remain,
        the room is deleted (and any running game is stopped). Returns list of room_ids affected.
        """
        affected: list[int] = []
        to_stop: list[tuple[int, Optional[str], Optional[str], bool]] = []
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
                        if gmLauncher and room.status in ("IN_GAME", "STARTING", "ENDING"):
                            match_id, temp_dir = self._mark_room_ending(room, clear_ready=True)
                            to_stop.append((room_id, match_id, temp_dir, True))
                        logger.info(f"deleting empty room {room_id} after host left")
                        del self.rooms[room_id]
                        continue
                if not room.players:
                    if gmLauncher and room.status in ("IN_GAME", "STARTING", "ENDING"):
                        match_id, temp_dir = self._mark_room_ending(room, clear_ready=True)
                        to_stop.append((room_id, match_id, temp_dir, True))
                    logger.info(f"deleting empty room {room_id}")
                    del self.rooms[room_id]
        for room_id, match_id, temp_dir, was_deleted in to_stop:
            if gmLauncher:
                gmLauncher.stop_room(room_id, match_id)
            self._cleanup_match_dir(temp_dir, match_id)
            if not was_deleted:
                with self.lock:
                    room = self.rooms.get(room_id)
                    if room and room.match_id == match_id:
                        self._finalize_room_cleanup(room)
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

    def _cleanup_match_dir(self, match_dir: Optional[str], match_id: Optional[str]):
        if not match_dir:
            return
        path = Path(match_dir)
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
        except Exception as exc:
            suffix = f"{match_id or 'unknown'}_{int(time.time())}"
            stale = path.parent / f"stale_{suffix}"
            try:
                path.rename(stale)
            except Exception:
                logger.warning(f"failed to clean match dir {path}: {exc}")

    def _cleanup_stale_match_dirs(self, max_age_sec: int = 3600):
        base = Path(__file__).resolve().parent.parent / "tmp_matches"
        if not base.exists():
            return
        now = time.time()
        in_use = set()
        with self.lock:
            for room in self.rooms.values():
                if room.players_json_dir:
                    in_use.add(Path(room.players_json_dir))
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            if entry in in_use:
                continue
            try:
                age = now - entry.stat().st_mtime
            except Exception:
                continue
            if age < max_age_sec:
                continue
            try:
                shutil.rmtree(entry)
            except Exception as exc:
                suffix = f"unknown_{int(time.time())}"
                stale = entry.parent / f"stale_{suffix}"
                try:
                    entry.rename(stale)
                except Exception:
                    logger.warning(f"failed to cleanup stale match dir {entry}: {exc}")

    def _mark_room_ending(self, room: Room, *, clear_ready: bool, err: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        room.status = "ENDING"
        if clear_ready:
            room.ready_players.clear()
        if err:
            room.last_error = err
        return room.match_id, room.players_json_dir

    def _finalize_room_cleanup(self, room: Room):
        room.status = "WAITING"
        room.port = None
        room.client_token = None
        room.report_token = None
        room.match_id = None
        room.server_pid = None
        room.players_json_dir = None
        room.launch_started_at = None
        room.startup_timeout = None
        room.last_heartbeat = None
        room.registered = False
        room.last_error = None
        room.ready_players.clear()

    def _watch_room(self, room_id, launcher, match_id: str, interval=0.5, heartbeat_interval=5.0):
        logger.debug(f"starting watcher for room {room_id} match={match_id}")
        warn_after = heartbeat_interval * 3
        kill_after = heartbeat_interval * 5
        last_warn = 0.0
        try:
            while True:
                try:
                    res = launcher.describe(room_id)
                    proc = res.proc if res and res.match_id == match_id else None
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
                        if not room or room.match_id != match_id:
                            break
                        _, temp_dir = self._mark_room_ending(room, clear_ready=True, err="process exit")
                    logger.info(f"room {room_id} server exited with code {code}")
                    launcher.stop_room(room_id, match_id)
                    self._cleanup_match_dir(temp_dir, match_id)
                    with self.lock:
                        room = self.rooms.get(room_id)
                        if room and room.match_id == match_id:
                            self._finalize_room_cleanup(room)
                        break
                except Exception as e:
                    logger.exception(f"room watcher poll failed for room {room_id}: {e}")
                    break
                now = time.time()
                should_stop = False
                temp_dir = None
                with self.lock:
                    room = self.rooms.get(room_id)
                    if not room or room.match_id != match_id:
                        break
                    if room.status == "STARTING" and room.launch_started_at and room.startup_timeout:
                        if now - room.launch_started_at > room.startup_timeout:
                            _, temp_dir = self._mark_room_ending(room, clear_ready=True, err="startup timeout")
                            should_stop = True
                    if should_stop:
                        pass
                    if room.status == "IN_GAME" and room.last_heartbeat:
                        delta = now - room.last_heartbeat
                        if delta > warn_after and now - last_warn > warn_after:
                            logger.warning(f"room {room_id} heartbeat late by {delta:.1f}s")
                            last_warn = now
                        if delta > kill_after:
                            _, temp_dir = self._mark_room_ending(room, clear_ready=True, err="heartbeat timeout")
                            should_stop = True
                if should_stop:
                    launcher.stop_room(room_id, match_id)
                    self._cleanup_match_dir(temp_dir, match_id)
                    with self.lock:
                        room = self.rooms.get(room_id)
                        if room and room.match_id == match_id:
                            self._finalize_room_cleanup(room)
                    break
                time.sleep(interval)
        finally:
            logger.debug(f"watcher cleanup complete for room {room_id} match={match_id}")

    def start_game(self, room_id: int, gmLauncher: GameLauncher, gmgr: GameManager) -> dict:
        with self.lock:
            room = self.get_room(room_id)
            if room.status != "WAITING":
                logger.error("Game already started or in progress")
                raise ValueError("Game already started or in progress")
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
            room.status = "STARTING"
            room.launch_seq += 1
            room.client_token = secrets.token_hex(16)
            room.report_token = secrets.token_hex(16)
            room.match_id = uuid.uuid4().hex
            room.registered = False
            room.last_heartbeat = None
            room.last_error = None
            room.launch_started_at = time.time()
            room.startup_timeout = None
            expected_match_id = room.match_id
            expected_client_token = room.client_token
            expected_report_token = room.report_token
            logger.info(f"starting game for room {room_id} host={room.host} players={room.players} match={expected_match_id}")

        try:
            running_result = gmLauncher.launch_room(
                room_id,
                USER_SERVER_HOST,
                room.metadata,
                room.players,
                match_id=expected_match_id,
                client_token=expected_client_token,
                report_token=expected_report_token,
            )
        except Exception:
            with self.lock:
                room = self.rooms.get(room_id)
                if room and room.match_id == expected_match_id:
                    self._finalize_room_cleanup(room)
            logger.exception(f"failed to launch room {room_id}; reverted to WAITING state")
            raise

        should_stop = False
        with self.lock:
            room = self.rooms.get(room_id)
            if not room or room.match_id != expected_match_id:
                should_stop = True
            else:
                room.port = running_result.port
                room.server_pid = running_result.proc.pid
                room.players_json_dir = str(running_result.temp_dir) if running_result.temp_dir else None
                room.startup_timeout = running_result.startup_timeout

        if should_stop:
            gmLauncher.stop_room(room_id, expected_match_id)
            self._cleanup_match_dir(str(running_result.temp_dir) if running_result.temp_dir else None, expected_match_id)
            raise ValueError("launch aborted due to stale match")

        t = threading.Thread(target=self._watch_room, args=(room_id, gmLauncher, expected_match_id), daemon=True)
        t.start()
        room_data = self.snapshot_room(room_id, include_launch_info=False)
        return {"room": room_data, "launch": None}

    def game_ended_normally(
        self,
        winner: str,
        loser: str,
        room_id: int,
        gmLauncher: GameLauncher,
        reviewMgr: ReviewManager | None = None,
        match_id: Optional[str] = None,
    ):
        temp_dir = None
        with self.lock:
            room = self.get_room(room_id)
            if match_id and room.match_id != match_id:
                logger.warning(f"ignoring END for stale match room={room_id} match={match_id}")
                return
            if winner:
                room.wins[winner] = room.wins.get(winner, 0) + 1
            if loser:
                room.losses[loser] = room.losses.get(loser, 0) + 1
            _, temp_dir = self._mark_room_ending(room, clear_ready=True)
        gmLauncher.stop_room(room_id, match_id)
        self._cleanup_match_dir(temp_dir, match_id)
        with self.lock:
            room = self.rooms.get(room_id)
            if room and (match_id is None or room.match_id == match_id):
                self._finalize_room_cleanup(room)
            if reviewMgr and room:
                if winner:
                    reviewMgr.add_play_history(str(room.metadata["game_name"]), str(room.metadata["version"]), winner)
                if loser:
                    reviewMgr.add_play_history(str(room.metadata["game_name"]), str(room.metadata["version"]), loser)
        logger.info(f"room {room_id} ended normally winner={winner} loser={loser}")

    def game_ended_with_error(self, err_msg: str, room_id: int, gmLauncher: GameLauncher, match_id: Optional[str] = None):
        temp_dir = None
        with self.lock:
            room = self.get_room(room_id)
            if match_id and room.match_id != match_id:
                logger.warning(f"ignoring ERROR for stale match room={room_id} match={match_id}")
                return
            _, temp_dir = self._mark_room_ending(room, clear_ready=True, err=err_msg)
        gmLauncher.stop_room(room_id, match_id)
        self._cleanup_match_dir(temp_dir, match_id)
        with self.lock:
            room = self.rooms.get(room_id)
            if room and (match_id is None or room.match_id == match_id):
                self._finalize_room_cleanup(room)
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
        match_id = None
        temp_dir = None
        with self.lock:
            room = self.rooms.get(room_id)
            if not room:
                raise ValueError(f"Room ID: {room_id} does not exist.")
            if gmLauncher and room.status in ("IN_GAME", "STARTING", "ENDING"):
                match_id, temp_dir = self._mark_room_ending(room, clear_ready=True)
            logger.info(f"deleting room {room_id}")
            del self.rooms[room_id]
        if gmLauncher and match_id:
            gmLauncher.stop_room(room_id, match_id)
            self._cleanup_match_dir(temp_dir, match_id)
        return True

    def leave_room(self, username: str, target_room_id: int, gmLauncher: GameLauncher | None = None) -> str:
        """
        Returns the name of the room host; empty string if the room was deleted.
        """
        delete_room = False
        new_host = ""
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
                    new_host = room.host
                    logger.info(f"{username} left room {target_room_id}; host transferred to {room.host}")
                else:
                    delete_room = True
            else:
                new_host = room.host
            logger.info(f"{username} left room {target_room_id}; remaining players={room.players}")

        if delete_room:
            self._delete_room(target_room_id, gmLauncher)
            logger.info(f"{username} left room {target_room_id}; room deleted because it became empty")
            return ""
        return new_host

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
