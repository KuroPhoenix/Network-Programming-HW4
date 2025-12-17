import base64
import json
import shlex
import tarfile
from io import BytesIO
from pathlib import Path
from loguru import logger
from typing import Any
from shared.logger import ensure_global_logger, log_dir

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
    GAME_DELETE_GAME,
    Message, USER_LIST,
)


class DevClient:
    """
    Developer-side networking wrapper. Connects to the dev server and sends Message envelopes.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        ensure_global_logger()
        logger.add(log_dir() / "dev_client.log", rotation="1 MB", level="INFO")
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

    def _validate_game_dir(self, game_name: str):
        """
        Basic sanity checks before upload: manifest present, working dirs exist,
        and referenced command targets are on disk.
        """
        base_dir = Path(__file__).resolve().parent.parent / "games" / game_name
        manifest_path = base_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"manifest missing for game: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"failed to read manifest: {exc}") from exc

        def check_side(side: str):
            info = manifest.get(side) or {}
            working_dir = info.get("working_dir", ".")
            work_path = (base_dir / working_dir).resolve()
            if not work_path.exists():
                raise ValueError(f"{side} working_dir not found: {work_path}")
            if not work_path.is_dir():
                raise ValueError(f"{side} working_dir is not a directory: {work_path}")
            cmd = info.get("command", "")
            tokens = shlex.split(cmd) if cmd else []
            candidates = []
            for tok in tokens:
                if "{" in tok or "}" in tok:
                    continue
                if tok.startswith("-"):
                    continue
                if tok in {"python", "python3", "bash", "sh", "node", "java"}:
                    continue
                if "/" in tok or tok.startswith(".") or tok.endswith((".py", ".js", ".sh", ".exe", ".out", ".bin", ".jar", ".rb", ".pl")):
                    candidates.append(tok)
            for cand in candidates:
                cand_path = Path(cand)
                if not cand_path.is_absolute():
                    cand_path = work_path / cand_path
                if cand_path.exists():
                    return
            if candidates:
                raise ValueError(f"{side} command target not found: {', '.join(candidates)} (cwd {work_path})")
            # No obvious target; at least ensure the working dir has some files.
            has_files = any(p.is_file() for p in work_path.iterdir())
            if not has_files:
                raise ValueError(f"{side} working_dir has no files: {work_path}")

        check_side("server")
        check_side("client")

    def uploadGame(self, username: str, payload: dict[str, Any]):
        self._validate_game_dir(payload["game_name"])
        # Begin upload
        data = self._pack_game(payload["game_name"])
        size_bytes = len(data)
        checksum = __import__("hashlib").sha256(data).hexdigest()
        begin_payload = {
            "game_name": payload["game_name"],
            "type": payload["game_type"],
            "version": payload.get("version", "0"),
            "description": payload.get("description", ""),
            "max_players": payload.get("max_players", 0),
            "size_bytes": size_bytes,
            "checksum": checksum,
        }
        resp = send_request(self.conn, self.file, self.token, GAME_UPLOAD_BEGIN, begin_payload)
        if resp.status != "ok":
            raise ValueError(f"Upload begin failed: {resp.message}")
        upload_id = resp.payload.get("upload_id")
        if not upload_id:
            raise ValueError("Upload begin missing upload_id")
        chunk_size = int(resp.payload.get("chunk_size", 64 * 1024))

        # Stream chunks
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

    def deleteGame(self, username: str, game_name: str):
        payload = {"username": username, "game_name": game_name}
        return send_request(self.conn, self.file, self.token, GAME_DELETE_GAME, payload)

    def logout(self, username: str):
        payload = {"token": self.token}
        if username:
            payload["username"] = username
        resp = send_request(self.conn, self.file, self.token, ACCOUNT_LOGOUT_DEVELOPER, payload)
        return resp

    def list_players(self):
        resp = send_request(self.conn, self.file, self.token, USER_LIST, {"role": "developer"})
        return resp
