import base64
import json, shlex, os, threading, time
import subprocess
from typing import Any
from loguru import logger

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
    LOBBY_LEAVE_ROOM, REVIEW_SEARCH_AUTHOR, REVIEW_SEARCH_GAME, REVIEW_DELETE, REVIEW_ADD, REVIEW_EDIT, ROOM_GET, REVIEW_ELIGIBILITY_CHECK,
    USER_LIST, ROOM_READY,
)
from user.utils.local_game_manager import LocalGameManager
from shared.logger import ensure_global_logger, log_dir

_CLIENT_SINK_ADDED = False


class UserClient:
    """
    Thin networking wrapper for the player client. Handles socket lifecycle,
    session token storage, and sending/receiving protocol envelopes.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        ensure_global_logger()
        global _CLIENT_SINK_ADDED
        if not _CLIENT_SINK_ADDED:
            logger.add(log_dir() / "user_client.log", rotation="1 MB", level="INFO", filter=lambda r: r["file"] == "user_api.py")
            _CLIENT_SINK_ADDED = True
        self.host = host or USER_SERVER_HOST
        self.port = port or USER_SERVER_HOST_PORT
        self.token: str | None = None
        self.conn, self.file = connect_to_server(self.host, self.port)
        self.username: str | None = None
        self.local_mgr: LocalGameManager | None = None
        self._watch_threads = []
        self._stop_event = threading.Event()
        logger.info(f"UserClient connected to {self.host}:{self.port}")

    def close(self):
        self._stop_event.set()
        for t in self._watch_threads:
            t.join(timeout=0.2)
        try:
            self.file.close()
        finally:
            self.conn.close()
        logger.info("UserClient connection closed")

    def _ensure_local_mgr(self, username: str) -> LocalGameManager:
        if self.local_mgr is None or self.username != username:
            self.local_mgr = LocalGameManager(username)
            self.username = username
        return self.local_mgr

    def register(self, username: str, password: str) -> Message:
        logger.info(f"register user={username}")
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_REGISTER_PLAYER, {"username": username, "password": password})
        if resp.status == "ok" and resp.payload.get("session_token"):
            self.token = resp.payload["session_token"]
            self.username = username
            self.local_mgr = LocalGameManager(username)
        return resp

    def login(self, username: str, password: str) -> Message:
        logger.info(f"login user={username}")
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGIN_PLAYER, {"username": username, "password": password})
        if resp.status == "ok" and resp.payload.get("session_token"):
            self.token = resp.payload["session_token"]
            self.username = username
            self.local_mgr = LocalGameManager(username)
        return resp

    def logout(self):
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGOUT_PLAYER, {"token": self.token})
        return resp

    def list_games(self) -> Message:
        resp = send_request(self.conn, self.file, self.token, GAME_LIST_GAME, {"role": "PLAYER"})
        return resp

    def list_players(self):
        resp = send_request(self.conn, self.file, self.token, USER_LIST, {"role": "player"})
        return resp

    def watch_rooms(self, interval: float = 3.0, callback=None):
        """
        Start a background poller that fetches rooms and online players periodically.
        Callback signature: callback({"rooms": [...], "players": [...]})
        """
        def loop():
            while not self._stop_event.is_set():
                try:
                    rooms_resp = self.list_rooms()
                    players_resp = self.list_players()
                    payload = {
                        "rooms": rooms_resp.payload.get("rooms", []) if rooms_resp.status == "ok" else [],
                        "players": players_resp.payload.get("players", []) if players_resp.status == "ok" else [],
                    }
                    if callback:
                        callback(payload)
                    logger.debug(f"watch_rooms callback fired with {len(payload['rooms'])} rooms and {len(payload['players'])} players")
                except Exception as exc:
                    logger.exception(f"watch_rooms loop error: {exc}")
                time.sleep(interval)

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        self._watch_threads.append(t)
        logger.info(f"watch_rooms started with interval={interval}")

    def get_game_details(self, game_name: str):
        resp = send_request(self.conn, self.file, self.token, GAME_GET_DETAILS, {"game_name": game_name})
        return resp

    def list_rooms(self):
        return send_request(self.conn, self.file, self.token, LOBBY_LIST_ROOMS, {})

    def get_room(self, room_id: int):
        payload = {"room_id": room_id}
        return send_request(self.conn, self.file, self.token, ROOM_GET, payload)
    def create_room(self, username: str, game_name: str, room_name: str | None = None):
        payload = {"username": username, "game_name": game_name, "room_name": room_name}
        return send_request(self.conn, self.file, self.token, LOBBY_CREATE_ROOM, payload)

    def join_room(self, username: str, room_id: int):
        payload = {"username": username, "room_id": room_id}
        return send_request(self.conn, self.file, self.token, LOBBY_JOIN_ROOM, payload)

    def set_ready(self, username: str, room_id: int, ready: bool = True):
        payload = {"username": username, "room_id": room_id, "ready": ready}
        return send_request(self.conn, self.file, self.token, ROOM_READY, payload)

    def leave_room(self, username: str, room_id: int):
        payload = {"username": username, "room_id": room_id}
        return send_request(self.conn, self.file, self.token, LOBBY_LEAVE_ROOM, payload)

    def list_author_review(self, author: str):
        payload = {"author": author}
        return send_request(self.conn, self.file, self.token, REVIEW_SEARCH_AUTHOR, payload)

    def list_game_review(self, game_name: str):
        payload = {"game_name": game_name}
        return send_request(self.conn, self.file, self.token, REVIEW_SEARCH_GAME, payload)

    def check_review_eligibility(self, author: str, game_name: str, version: str | None = None):
        payload = {"author": author, "game_name": game_name}
        if version is not None:
            payload["version"] = version
        return send_request(self.conn, self.file, self.token, REVIEW_ELIGIBILITY_CHECK, payload)

    def delete_review(self, author: str, game_name: str, content: str, version: str | None = None):
        payload = {"author": author, "game_name": game_name, "content": content}
        if version is not None:
            payload["version"] = version
        return send_request(self.conn, self.file, self.token, REVIEW_DELETE, payload)

    def add_review(self, author: str, game_name: str, content: str, score: int, version: str | None = None):
        payload = {"author": author, "game_name": game_name, "content": content, "score": score}
        if version is not None:
            payload["version"] = version
        return send_request(self.conn, self.file, self.token, REVIEW_ADD, payload)

    def edit_review(self, author, game_name, old_content: str, new_content: str, score: int, version: str | None = None):
        payload = {
            "author": author,
            "game_name": game_name,
            "old_content": old_content,
            "new_content": new_content,
            "score": score,
        }
        if version is not None:
            payload["version"] = version
        return send_request(self.conn, self.file, self.token, REVIEW_EDIT, payload)

    def _launch_local_client(self, username: str, host: str, port: int, token: str, game_name: str, version: str):
        mgr = self._ensure_local_mgr(username)
        manifest = mgr.load_manifest(str(game_name), str(version))
        manifest_path = mgr._manifest_path(str(game_name), str(version))
        client_cfg = manifest["client"]

        ctx = {
            "host": host,
            "port": port,
            "token": token,
            "player_name": username,
        }
        cmd = shlex.split(client_cfg["command"].format(**ctx))
        workdir = (manifest_path.parent / client_cfg.get("working_dir", ".")).resolve()
        env = os.environ.copy()
        env.update({k: str(v).format(**ctx) for k, v in client_cfg.get("env", {}).items()})
        try:
            logger.info(f"launching local client for {game_name} v{version} user={username} cmd={cmd} cwd={workdir}")
            subprocess.Popen(cmd, cwd=workdir, env=env)
        except Exception as e:
            logger.exception(f"Failed to launch local client: {e}")
            raise RuntimeError(f"Failed to launch local client: {e}")

    def start_game(self, room_id, game_name: str, username: str = "", ):
        """
        Ask the server to start the room and then launch the local game client using the downloaded manifest.
        """
        payload = {"room_id": room_id}
        #Check game version
        try:
            self.validate_game(username, game_name)
        except Exception as exc:
            logger.exception(f"local validation failed before GAME_START for room {room_id}: {exc}")
            return Message(type="LOCAL.LAUNCH", status="error", code=1, message=str(exc))
        resp = send_request(self.conn, self.file, self.token, GAME_START, payload)
        if resp.status != "ok":
            return resp
        launch = resp.payload["launch"] or {}
        # Expect server to return host/port/token/game_name/version
        host = launch.get("host") or USER_SERVER_HOST
        port = launch.get("port")
        token = launch.get("token")
        game_name = launch.get("game_name") or (launch.get("metadata") or {}).get("game_name")
        version = launch.get("version") or (launch.get("metadata") or {}).get("version")
        if not all([port, token, game_name, version]):
            raise ValueError("GAME_START missing launch details (host/port/token/game/version)")

        try:
            self._launch_local_client(username, host, int(port), str(token), str(game_name), str(version))
            logger.info(f"started local client for room {room_id} on port {port}")
        except Exception as exc:
            return Message(type="LOCAL.LAUNCH", status="error", code=3, message=str(exc))
        return resp

    def launch_started_game(self, room_id: int, username: str):
        """
        For non-host players: fetch room info and launch the client if the game is already started.
        """
        room_resp = self.get_room(room_id)
        if room_resp.status != "ok":
            return Message(type="LOCAL.LAUNCH", status="error", code=1, message=room_resp.message or "room fetch failed")
        room = room_resp.payload or {}
        status = room.get("status")
        port = room.get("port")
        token = room.get("token")
        metadata = room.get("metadata") or {}
        game_name = metadata.get("game_name")
        version = metadata.get("version")
        if status != "IN_GAME" or not all([port, token, game_name, version]):
            return Message(type="LOCAL.LAUNCH", status="error", code=2, message="Game not started or missing launch info")
        # ensure local version
        try:
            self.validate_game(username, game_name)
            self._launch_local_client(username, USER_SERVER_HOST, int(port), str(token), str(game_name), str(version))
            logger.info(f"joined running game room {room_id} user={username} port={port}")
            return Message(type="LOCAL.LAUNCH", status="ok", code=0, payload={"room_id": room_id})
        except Exception as exc:
            logger.exception(f"failed to launch running game for room {room_id}: {exc}")
            return Message(type="LOCAL.LAUNCH", status="error", code=3, message=str(exc))

    def download_game(self, username: str, game_name: str):
        if not game_name:
            raise ValueError("game_name required")
        mgr = self._ensure_local_mgr(username)
        dwzd = DownloadWizard(username)
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
        logger.info(f"download_game begin user={username} game={game_name} version={expected['version']} download_id={download_id}")
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

        result = dwzd.finalise_download(download_id)
        end_resp = send_request(self.conn, self.file, self.token, GAME_DOWNLOAD_END, {"download_id": download_id})
        # Tell caller about local install path/manifest.
        payload = {"path": result.get("path"), "manifest": result.get("manifest")}
        logger.info(f"download_game complete user={username} game={game_name} version={expected['version']}")
        return Message(type="LOCAL.DOWNLOAD", status="ok", code=0, payload=payload, message=end_resp.message)

    def list_local_games(self, username: str):
        mgr = self._ensure_local_mgr(username)
        return mgr.list_downloaded_games()

    def update_game(self, username: str, game_name: str, require_installed: bool = False):
        """
        Download latest version of a game if local copy is missing or outdated.
        """
        mgr = self._ensure_local_mgr(username)
        try:
            details = self.get_game_details(game_name)
            if details.status != "ok":
                return details
            latest_version = str((details.payload.get("game") or {}).get("version", ""))
            local_versions = mgr.list_versions(game_name)
            if require_installed and not local_versions:
                return Message(
                    type="LOCAL.UPDATE",
                    status="error",
                    code=1,
                    message="Game not installed locally. Download it first.",
                )
            if latest_version and latest_version in local_versions:
                return Message(
                    type="LOCAL.UPDATE",
                    status="ok",
                    code=0,
                    message=f"{game_name} already at latest ({latest_version})",
                    payload={"version": latest_version},
                )
            dl_resp = self.download_game(username, game_name)
            return dl_resp
        except Exception as e:
            return Message(type="LOCAL.UPDATE", status="error", code=1, message=str(e))

    def delete_game(self, username: str, game_name: str):
        mgr = self._ensure_local_mgr(username)
        removed = mgr.delete_game(game_name)
        if removed:
            return Message(type="LOCAL.DELETE", status="ok", code=0, payload={"game_name": game_name})
        return Message(type="LOCAL.DELETE", status="error", code=1, message="game not found locally")

    def validate_game(self, username: str, game_name: str):
        resp = send_request(self.conn, self.file, self.token, GAME_GET_DETAILS, {"game_name": game_name})
        if resp.status != "ok":
            raise ValueError(f"Game details not valid: {resp.message}")
        payload = resp.payload or {}
        game = payload.get("game") or {}
        latest_ver = str(game.get("version", ""))
        mgr = self._ensure_local_mgr(username)
        versions = mgr.list_versions(game_name)
        user_ver = versions[-1] if versions else ""
        if not latest_ver:
            raise ValueError("Game version not found / Game deleted.")
        if latest_ver and latest_ver != user_ver:
            print("[Notice: Your current game is outdated. Update will commence shortly.]")
            logger.info(f"auto-updating outdated game for user={username} game={game_name} local={user_ver} latest={latest_ver}")
            self.update_game(username, game_name)



def get_client() -> UserClient:
    return UserClient()
