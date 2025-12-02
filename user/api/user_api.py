import base64
from typing import Any

import user.config.user_config as cfg
from shared.net import connect_to_server, send_request
from user.utils.download_wizard import DownloadWizard
from server.core.protocol import (
    ACCOUNT_LOGIN_PLAYER,
    ACCOUNT_REGISTER_PLAYER,
    ACCOUNT_LOGOUT_PLAYER,
    Message,
    GAME_LIST_GAME,
    GAME_GET_DETAILS,
    GAME_DOWNLOAD_BEGIN,
    GAME_DOWNLOAD_CHUNK,
    GAME_DOWNLOAD_END,
    LOBBY_LIST_ROOMS,
    LOBBY_CREATE_ROOM,
    LOBBY_JOIN_ROOM,
    LOBBY_LEAVE_ROOM,
)


class UserClient:
    """
    Thin networking wrapper for the player client. Handles socket lifecycle,
    session token storage, and sending/receiving protocol envelopes.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or cfg.HOST_IP
        self.port = port or cfg.HOST_PORT
        self.token: str | None = None
        self.conn, self.file = connect_to_server(self.host, self.port)

    def close(self):
        try:
            self.file.close()
        finally:
            self.conn.close()

    def register(self, username: str, password: str) -> Message:
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_REGISTER_PLAYER, {"username": username, "password": password})
        if resp.status == "ok" and resp.payload.get("session_token"):
            self.token = resp.payload["session_token"]
        return resp

    def login(self, username: str, password: str) -> Message:
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGIN_PLAYER, {"username": username, "password": password})
        if resp.status == "ok" and resp.payload.get("session_token"):
            self.token = resp.payload["session_token"]
        return resp

    def logout(self):
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGOUT_PLAYER, {"token": self.token})
        return resp

    def list_games(self) -> Message:
        resp = send_request(self.conn, self.file, self.token, GAME_LIST_GAME, {"role": "PLAYER"})
        return resp

    def get_game_details(self, game_name: str):
        resp = send_request(self.conn, self.file, self.token, GAME_GET_DETAILS, {"game_name": game_name})
        return resp

    def list_rooms(self):
        return send_request(self.conn, self.file, self.token, LOBBY_LIST_ROOMS, {})

    def create_room(self, username: str, game_name: str, room_name: str | None = None):
        payload = {"username": username, "game_name": game_name}
        if room_name:
            payload["room_name"] = room_name
        return send_request(self.conn, self.file, self.token, LOBBY_CREATE_ROOM, payload)

    def join_room(self, username: str, room_id: int, spectator: bool = False):
        payload = {"username": username, "room_id": room_id, "spectator": spectator}
        return send_request(self.conn, self.file, self.token, LOBBY_JOIN_ROOM, payload)

    def leave_room(self, username: str, room_id: int):
        payload = {"username": username, "room_id": room_id}
        return send_request(self.conn, self.file, self.token, LOBBY_LEAVE_ROOM, payload)

    def download_game(self, username: str, game_name: str):
        if not game_name:
            raise ValueError("game_name required")
        dwzd = DownloadWizard()
        resp = self.get_game_details(game_name)
        if resp.status != "ok":
            raise ValueError(f"Failed to get game detail: {resp.message}")
        game_info = resp.payload.get("game") or {}
        begin_payload = {"game_name": game_name}
        resp = send_request(self.conn, self.file, self.token, GAME_DOWNLOAD_BEGIN, begin_payload)
        if resp.status != "ok":
            raise ValueError(f"Download begin failed: {resp.message}")
        download_id = resp.payload.get("download_id")
        if not download_id:
            raise ValueError("Download begin missing download_id")

        expected = {
            "game_name": game_name,
            "version": game_info.get("version"),
        }
        dwzd.init_download_verification(expected, download_id)

        seq = 0
        while True:
            chunk_req = {"download_id": download_id, "seq": seq}
            resp = send_request(self.conn, self.file, self.token, GAME_DOWNLOAD_CHUNK, chunk_req)
            if resp.status != "ok":
                raise ValueError(f"Download chunk failed at seq {seq}: {resp.message}")
            b64data = resp.payload.get("data", "")
            chunk = base64.b64decode(b64data) if b64data else b""
            dwzd.append_chunk(download_id, chunk, seq)
            done = bool(resp.payload.get("done"))
            seq += 1
            if done:
                break

        dwzd.finalise_download(download_id)
        send_request(self.conn, self.file, self.token, GAME_DOWNLOAD_END, {"download_id": download_id})

def get_client() -> UserClient:
    return UserClient()
