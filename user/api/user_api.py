from typing import Any

import user.config.user_config as cfg
from shared.net import connect_to_server, send_request
from server.core.protocol import (
    ACCOUNT_LOGIN_PLAYER,
    ACCOUNT_REGISTER_PLAYER,
    Message,
    message_from_dict,
    message_to_dict,
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


def get_client() -> UserClient:
    return UserClient()
