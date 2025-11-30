from loguru import logger
from typing import Any

from shared.net import connect_to_server, send_request
from developer.dev_config.dev_config import HOST_IP, HOST_PORT
from server.core.protocol import (
    ACCOUNT_LOGIN_DEVELOPER,
    ACCOUNT_REGISTER_DEVELOPER,
    ACCOUNT_LOGOUT_DEVELOPER,
    GAME_UPLOAD_GAME,
    GAME_LIST_GAME,
    Message,
)


class DevClient:
    """
    Developer-side networking wrapper. Connects to the dev server and sends Message envelopes.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        logger.remove()
        logger.add("dev_client.log", rotation="1 MB", level="INFO")
        self.host = host or HOST_IP
        self.port = port or HOST_PORT
        self.token: str | None = None
        self.conn, self.file = connect_to_server(self.host, self.port)

    def close(self):
        try:
            self.file.close()
        finally:
            self.conn.close()


    def register(self, username: str, password: str) -> Message:
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_REGISTER_DEVELOPER,{"username": username, "password": password})
        if resp.status == "ok" and resp.payload.get("session_token"):
            self.token = resp.payload["session_token"]
        return resp

    def login(self, username: str, password: str) -> Message:
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGIN_DEVELOPER, {"username": username, "password": password})
        if resp.status == "ok" and resp.payload.get("session_token"):
            self.token = resp.payload["session_token"]
        return resp

    def listGame(self, username: str):
        resp = send_request(self.conn, self.file, self.token, GAME_LIST_GAME, {"username": username, "role": "DEVELOPER"})
        return resp

    def uploadGame(self, username: str, payload: dict[str, Any]):
        resp = send_request(
            self.conn,
            self.file,
            self.token,
            GAME_UPLOAD_GAME,
            {
                "username": username,
                "game_name": payload["game_name"],
                "type": payload["game_type"],
                "description": payload.get("description", ""),
                "max_players": payload.get("max_players", 0),
            },
        )
        return resp

    def logout(self, username: str):
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGOUT_DEVELOPER, {"username": username})
        return resp
