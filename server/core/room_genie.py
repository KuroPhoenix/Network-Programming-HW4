from dataclasses import asdict, dataclass, field
from typing import Literal, Optional
import threading
import time


@dataclass
class Room:
    room_id: int
    host: str
    room_name: str
    players: list[str] = field(default_factory=list)
    spectators: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    max_players: Optional[int] = None
    status: Literal["WAITING", "IN_GAME"] = "WAITING"
    port: Optional[int] = field(default=None)
    server_pid: Optional[int] = field(default=None)
    created_at: float = field(default_factory=time.time)


class RoomGenie:
    def __init__(self):
        self.rooms: dict[int, Room] = {}
        self.next_room_id = 1
        self.lock = threading.Lock()

    def list_rooms(self) -> list[dict]:
        with self.lock:
            return [asdict(room) for room in self.rooms.values()]

    def create_room(self, host: str, room_name: str, metadata: dict) -> Room:
        with self.lock:
            room_id = self.next_room_id
            self.next_room_id += 1
            max_players = None
            if isinstance(metadata, dict):
                mp = metadata.get("max_players")
                if isinstance(mp, int) and mp > 0:
                    max_players = mp
            room = Room(room_id, host, room_name, players=[host], metadata=metadata or {}, max_players=max_players,)
            self.rooms[room_id] = room
            return room

    def _get_room(self, room_id: int) -> Room:
        room = self.rooms.get(room_id)
        if not room:
            raise ValueError(f"Room ID: {room_id} does not exist.")
        return room

    def join_room_as_player(self, username: str, target_room_id: int):
        with self.lock:
            room = self._get_room(target_room_id)
            if username in room.players or username in room.spectators:
                return
            if room.max_players is not None and len(room.players) >= room.max_players:
                raise ValueError(f"Room ID: {room.room_id} {room.room_name} is full.")
            room.players.append(username)

    def join_room_as_spectator(self, username: str, target_room_id: int):
        with self.lock:
            room = self._get_room(target_room_id)
            if username in room.players or username in room.spectators:
                return
            room.spectators.append(username)

    def _delete_room(self, room_id: int):
        with self.lock:
            if room_id in self.rooms:
                del self.rooms[room_id]
                return True
            raise ValueError(f"Room ID: {room_id} does not exist.")

    def leave_room(self, username: str, target_room_id: int) -> str:
        """
        Returns the name of the room host; empty string if the room was deleted.
        """
        with self.lock:
            room = self._get_room(target_room_id)
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
                    self._delete_room(target_room_id)
                    return ""

            return room.host
