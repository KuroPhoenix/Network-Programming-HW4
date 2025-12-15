from __future__ import annotations
import json, shlex, subprocess, socket, time, os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from loguru import logger
from server.core.config import USER_SERVER_HOST, USER_SERVER_HOST_PORT
from shared.logger import ensure_global_logger, log_dir

# Module-specific logging
LOG_DIR = log_dir()
ensure_global_logger()
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
        for attempt in range(20):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("0.0.0.0", 0))
                    port = s.getsockname()[1]
            except OSError as exc:
                logger.warning(f"port allocation attempt {attempt + 1}/20 failed: {exc}")
                continue
            if port not in self._reserved:
                self._reserved.add(port)
                logger.debug(f"reserved port {port} (attempt {attempt + 1})")
                return port
            logger.debug(f"port {port} already reserved, retrying (attempt {attempt + 1})")
        raise RuntimeError("unable to allocate a free port after 20 attempts")

    def _release_port(self, port: int):
        logger.debug(f"releasing port {port}")
        self._reserved.discard(port)

    def _load_manifest(self, game_name: str, version: str) -> dict:
        mpath = self.base / game_name / str(version) / "manifest.json"
        if not mpath.exists():
            raise ValueError(f"manifest not found at {mpath}")
        try:
            return json.loads(mpath.read_text(encoding="utf-8"))
        except Exception as exc:  # ensure invalid JSON is surfaced with context
            logger.error(f"failed to read manifest at {mpath}: {exc}")
            raise ValueError(f"manifest unreadable at {mpath}") from exc

    def _render_cmd(self, template: str, context: dict) -> list[str]:
        try:
            rendered = template.format(**context)
        except Exception as exc:
            logger.error(f"failed to render launch command from template {template}: {exc}")
            raise
        return shlex.split(rendered)

    def _wait_for_process_start(self, proc: subprocess.Popen, timeout: float = 5.0) -> None:
        """
        Detect early-exit failures shortly after spawn so we can fail fast and release resources.
        """
        start = time.time()
        while time.time() - start < timeout:
            code = proc.poll()
            if code is not None:
                raise RuntimeError(f"game server exited immediately with code {code}")
            time.sleep(0.1)

    def _build_env(self, base_env: dict, context: dict) -> dict:
        env = os.environ.copy()
        env.update({k: str(v) for k, v in context.items()})
        for key, value in base_env.items():
            try:
                env[key] = str(value).format(**context)
            except Exception as exc:
                logger.warning(f"failed to format env var {key} with context; using raw value. err={exc}")
                env[key] = str(value)
        return env

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
        env = self._build_env(server_cfg.get("env", {}), ctx)
        logger.info(f"Launching room {room_id} server: {server_cmd} (cwd={workdir}, token={token}, players={players})")

        try:
            proc = subprocess.Popen(server_cmd, cwd=workdir, env=env)
            self._running[room_id] = LaunchResult(room_id, port, token, proc)
            startup_timeout = float(server_cfg.get("startup_timeout", 5) or 5)
            try:
                self._wait_for_process_start(proc, timeout=startup_timeout)
            except Exception:
                logger.exception(f"room {room_id} server appears unhealthy right after launch; terminating.")
                self.stop_room(room_id)
                raise
            logger.info(f"room {room_id} server started (pid={proc.pid}, port={port})")
            return self._running[room_id]
        except Exception:
            # free the port on failure to launch
            logger.exception(f"failed to launch room {room_id}")
            self._release_port(port)
            raise

    def stop_room(self, room_id: int):
        res = self._running.pop(room_id, None)
        if not res:
            logger.debug(f"stop_room called for non-running room {room_id}")
            return False
        try:
            if res.proc.poll() is None:
                logger.info(f"terminating room {room_id} server pid={res.proc.pid}")
                res.proc.terminate()
                try:
                    res.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"room {room_id} server did not terminate gracefully; killing pid={res.proc.pid}")
                    res.proc.kill()
                    try:
                        res.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.error(f"room {room_id} server stubbornly refused to exit after kill")
            else:
                logger.info(f"room {room_id} server already exited with code {res.proc.returncode}")
        except Exception:
            logger.exception(f"error while stopping room {room_id}")
        finally:
            self._release_port(res.port)
        return True

    def describe(self, room_id: int) -> Optional[LaunchResult]:
        return self._running.get(room_id)



