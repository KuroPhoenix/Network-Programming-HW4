from loguru import logger
from typing import Any

from shared.net import connect_to_server, send_request
from developer.dev_config.dev_config import HOST_IP, HOST_PORT
from server.core.protocol import (
    ACCOUNT_LOGIN_DEVELOPER,
    ACCOUNT_REGISTER_DEVELOPER,
    Message,
    AccountReq,
    message_from_dict,
    message_to_dict,
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

    def send_request(
        self, mtype: str, payload: dict[str, Any], request_id: str | None = None
    ) -> Message:
        msg = Message(type=mtype, payload=payload, token=self.token, request_id=request_id)
        resp_dict = send_request(self.conn, self.file, message_to_dict(msg))
        return message_from_dict(resp_dict)

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

