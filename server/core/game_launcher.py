from __future__ import annotations
import json, shlex, subprocess, socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from loguru import logger
from server.core.config import USER_SERVER_HOST, USER_SERVER_HOST_PORT

# Module-specific logging
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.add(LOG_DIR / "game_launcher_errors.log", rotation="1 MB", level="ERROR", filter=lambda r: r["file"] == "game_launcher.py")

@dataclass
class LaunchResult:
    room_id: int
    port: int
    token: str
    proc: subprocess.Popen


class GameLauncher:
    def __init__(self, base: Optional[Path] = None):
        self.base = base or (Path(__file__).resolve().parent.parent / "cloudGames")
        self._running: dict[int, LaunchResult] = {}
        self._reserved: set[int] = set()

    def _alloc_port(self) -> int:
        """
        Ask the OS for an available TCP port and reserve it so we don't reuse it while running.
        """
        for _ in range(20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("0.0.0.0", 0))
                port = s.getsockname()[1]
            if port not in self._reserved:
                self._reserved.add(port)
                return port
        raise RuntimeError("unable to allocate a free port")

    def _release_port(self, port: int):
        self._reserved.discard(port)

    def _load_manifest(self, game_name: str, version: str) -> dict:
        mpath = self.base / game_name / str(version) / "manifest.json"
        if not mpath.exists():
            raise ValueError(f"manifest not found at {mpath}")
        return json.loads(mpath.read_text(encoding="utf-8"))

    def _render_cmd(self, template: str, context: dict) -> list[str]:
        rendered = template.format(**context)
        return shlex.split(rendered)

    def launch_room(self, room_id: int, host: str, game: dict, players: list[str]) -> LaunchResult:
        """
        game: {'game_name':..., 'version':..., ...}
        players: list of usernames in room order (p1 = players[0], p2 = players[1], ...)
        """
        if room_id in self._running:
            raise ValueError("room already running")
        manifest = self._load_manifest(game["game_name"], game["version"])
        port = self._alloc_port()
        token = f"room{room_id:06d}"

        ctx = {
            "host": host,
            "port": port,
            "room_id": room_id,
            "token": token,
            "player_name": players[0] if players else "",
            "p1": players[0] if len(players) > 0 else "",
            "p2": players[1] if len(players) > 1 else "",
            "report_host": USER_SERVER_HOST,
            "report_port": USER_SERVER_HOST_PORT,
            "report_token": token,
        }

        server_cfg = manifest["server"]
        server_cmd = self._render_cmd(server_cfg["command"], ctx)
        workdir = (self.base / game["game_name"] / str(game["version"]) / server_cfg.get("working_dir", ".")).resolve()
        env = {**server_cfg.get("env", {}), **{k: str(v) for k, v in ctx.items()}}
        logger.info(f"Launching room {room_id} server: {server_cmd} (cwd={workdir})")

        try:
            proc = subprocess.Popen(server_cmd, cwd=workdir, env={**env, **dict(__import__('os').environ)})
            self._running[room_id] = LaunchResult(room_id, port, token, proc)
            return self._running[room_id]
        except Exception:
            # free the port on failure to launch
            self._release_port(port)
            raise

    def stop_room(self, room_id: int):
        res = self._running.pop(room_id, None)
        if res and res.proc.poll() is None:
            res.proc.terminate()
        if res:
            self._release_port(res.port)

        return True

    def describe(self, room_id: int) -> Optional[LaunchResult]:
        return self._running.get(room_id)



