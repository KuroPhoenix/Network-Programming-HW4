import base64
import tarfile
from io import BytesIO
from pathlib import Path
from loguru import logger
from typing import Any

from shared.net import connect_to_server, send_request
from server.core.config import DEV_SERVER_HOST_IP, DEV_SERVER_HOST_PORT
from server.core.protocol import (
    ACCOUNT_LOGIN_DEVELOPER,
    ACCOUNT_REGISTER_DEVELOPER,
    ACCOUNT_LOGOUT_DEVELOPER,
    GAME_LIST_GAME,
    GAME_UPLOAD_BEGIN,
    GAME_UPLOAD_CHUNK,
    GAME_UPLOAD_END,
    Message,
)


class DevClient:
    """
    Developer-side networking wrapper. Connects to the dev server and sends Message envelopes.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        logger.remove()
        logger.add("dev_client.log", rotation="1 MB", level="INFO")
        self.host = host or DEV_SERVER_HOST_IP
        self.port = port or DEV_SERVER_HOST_PORT
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

    def _pack_game(self, game_name: str) -> bytes:
        base_dir = Path(__file__).resolve().parent.parent / "games" / game_name
        if not base_dir.exists():
            raise ValueError(f"game folder not found: {base_dir}")
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            tar.add(base_dir, arcname=".")
        return buffer.getvalue()

    def uploadGame(self, username: str, payload: dict[str, Any]):
        # Begin upload
        begin_payload = {
            "game_name": payload["game_name"],
            "type": payload["game_type"],
            "version": payload.get("version", "0"),
            "description": payload.get("description", ""),
            "max_players": payload.get("max_players", 0),
        }
        resp = send_request(self.conn, self.file, self.token, GAME_UPLOAD_BEGIN, begin_payload)
        if resp.status != "ok":
            raise ValueError(f"Upload begin failed: {resp.message}")
        upload_id = resp.payload.get("upload_id")
        if not upload_id:
            raise ValueError("Upload begin missing upload_id")

        # Stream chunks
        data = self._pack_game(payload["game_name"])
        chunk_size = 64 * 1024
        seq = 0
        for offset in range(0, len(data), chunk_size):
            chunk = data[offset : offset + chunk_size]
            enc = base64.b64encode(chunk).decode("ascii")
            chunk_payload = {"upload_id": upload_id, "seq": seq, "data": enc}
            resp = send_request(self.conn, self.file, self.token, GAME_UPLOAD_CHUNK, chunk_payload)
            if resp.status != "ok":
                raise ValueError(f"Upload chunk failed at seq {seq}: {resp.message}")
            seq += 1

        # End upload
        end_payload = {"upload_id": upload_id, "username": username}
        resp = send_request(self.conn, self.file, self.token, GAME_UPLOAD_END, end_payload)
        if resp.status != "ok":
            raise ValueError(f"Upload end failed: {resp.message}")
        return resp


    def logout(self, username: str):
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGOUT_DEVELOPER, {"username": username})
        return resp
