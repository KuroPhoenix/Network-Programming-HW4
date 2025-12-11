import base64
import json, shlex, os
import subprocess
from pathlib import Path
from typing import Any

from server.core.config import USER_SERVER_HOST, USER_SERVER_HOST_PORT
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
    GAME_REPORT,
    GAME_START,
    LOBBY_LIST_ROOMS,
    LOBBY_CREATE_ROOM,
    LOBBY_JOIN_ROOM,
    LOBBY_LEAVE_ROOM, REVIEW_SEARCH_AUTHOR, REVIEW_SEARCH_GAME, REVIEW_DELETE, REVIEW_ADD, REVIEW_EDIT,
)


class UserClient:
    """
    Thin networking wrapper for the player client. Handles socket lifecycle,
    session token storage, and sending/receiving protocol envelopes.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or USER_SERVER_HOST
        self.port = port or USER_SERVER_HOST_PORT
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
        payload = {"username": username, "game_name": game_name, "room_name": room_name}
        return send_request(self.conn, self.file, self.token, LOBBY_CREATE_ROOM, payload)

    def join_room(self, username: str, room_id: int, spectator: bool = False):
        payload = {"username": username, "room_id": room_id, "spectator": spectator}
        return send_request(self.conn, self.file, self.token, LOBBY_JOIN_ROOM, payload)

    def leave_room(self, username: str, room_id: int):
        payload = {"username": username, "room_id": room_id}
        return send_request(self.conn, self.file, self.token, LOBBY_LEAVE_ROOM, payload)

    def list_author_review(self, author: str):
        payload = {"author": author}
        return send_request(self.conn, self.file, self.token, REVIEW_SEARCH_AUTHOR, payload)

    def list_game_review(self, game_name: str):
        payload = {"game_name": game_name}
        return send_request(self.conn, self.file, self.token, REVIEW_SEARCH_GAME, payload)

    def delete_review(self, author: str, game_name: str, content: str):
        payload = {"author": author, "game_name": game_name, "content": content}
        return send_request(self.conn, self.file, self.token, REVIEW_DELETE, payload)

    def add_review(self, author: str, game_name: str, content: str, score: int):
        payload = {"author": author, "game_name": game_name, "content": content, "score": score}
        return send_request(self.conn, self.file, self.token, REVIEW_ADD, payload)

    def edit_review(self, author, game_name, old_content: str, new_content: str, score: int):
        payload = {
            "author": author,
            "game_name": game_name,
            "old_content": old_content,
            "new_content": new_content,
            "score": score,
        }
        return send_request(self.conn, self.file, self.token, REVIEW_EDIT, payload)

    def start_game(self, room_id, username: str = ""):
        """
        Ask the server to start the room and then launch the local game client using the downloaded manifest.
        """
        payload = {"room_id": room_id}
        resp = send_request(self.conn, self.file, self.token, GAME_START, payload)
        if resp.status != "ok":
            return resp
        launch = resp.payload["launch"] or {}
        # Expect server to return host/port/token/game_name/version
        host = cfg.HOST_IP
        port = launch.get("port")
        token = launch.get("token")
        game_name = launch.get("game_name") or (launch.get("metadata") or {}).get("game_name")
        version = launch.get("version") or (launch.get("metadata") or {}).get("version")
        if not all([port, token, game_name, version]):
            raise ValueError("GAME_START missing launch details (host/port/token/game/version)")

        # Resolve manifest path from local downloads
        manifest_path = Path(cfg.manifest_base_path) / str(game_name) / str(version) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found at {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        client_cfg = manifest["client"]

        ctx = {
            "host": host,
            "port": port,
            "token": token,
            "player_name": username or (launch.get("player") or ""),
        }
        cmd = shlex.split(client_cfg["command"].format(**ctx))
        workdir = (manifest_path.parent / client_cfg.get("working_dir", ".")).resolve()
        env = os.environ.copy()
        env.update({k: str(v).format(**ctx) for k, v in client_cfg.get("env", {}).items()})
        subprocess.Popen(cmd, cwd=workdir, env=env)
        return resp

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
