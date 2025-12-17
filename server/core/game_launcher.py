from __future__ import annotations
import json, shlex, subprocess, socket, time, os, tempfile, signal
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from loguru import logger
from server.core.config import USER_SERVER_HOST, USER_SERVER_HOST_PORT, USER_SERVER_BIND_HOST, PLATFORM_PROTOCOL_VERSION
from shared.logger import ensure_global_logger, log_dir

# Module-specific logging
LOG_DIR = log_dir()
ensure_global_logger()
logger.add(LOG_DIR / "game_launcher_errors.log", rotation="1 MB", level="ERROR", filter=lambda r: r["file"] == "game_launcher.py")

@dataclass
class LaunchResult:
    room_id: int
    port: int
    match_id: str
    client_token: str
    report_token: str
    proc: subprocess.Popen
    temp_dir: Optional[Path] = None
    startup_timeout: float = 5.0


class GameLauncher:
    def __init__(self, base: Optional[Path] = None):
        self.base = base or (Path(__file__).resolve().parent.parent / "cloudGames")
        self.tmp_base = Path(__file__).resolve().parent.parent / "tmp_matches"
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

    def _wait_for_tcp_ready(self, hosts: list[str], port: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        hosts = [h for h in hosts if h and h != "0.0.0.0"]
        if not hosts:
            return False
        while time.time() < deadline:
            for host in hosts:
                try:
                    with socket.create_connection((host, port), timeout=0.3):
                        return True
                except OSError:
                    continue
            time.sleep(0.1)
        return False

    def _diagnostic_healthcheck(self, manifest: dict, ctx: dict, port: int) -> None:
        health = manifest.get("healthcheck") or {}
        host_tmpl = health.get("host")
        hc_host = None
        if host_tmpl:
            try:
                hc_host = str(host_tmpl).format(**ctx)
            except Exception as exc:
                logger.warning(f"failed to format healthcheck.host; ignoring. err={exc}")
        port_tmpl = health.get("tcp_port")
        hc_port = port
        if port_tmpl:
            try:
                hc_port = int(str(port_tmpl).format(**ctx))
            except Exception as exc:
                logger.warning(f"failed to format healthcheck.tcp_port; using port {port}. err={exc}")
                hc_port = port
        timeout = float(health.get("timeout_sec", 5) or 5)
        targets = ["127.0.0.1"]
        if hc_host and hc_host not in targets:
            targets.append(hc_host)
        advertised = ctx.get("host")
        if advertised and advertised not in targets and advertised != "0.0.0.0":
            targets.append(advertised)
        ok = self._wait_for_tcp_ready(targets, hc_port, timeout)
        if ok:
            logger.info(f"healthcheck ok for port={hc_port} targets={targets}")
        else:
            logger.warning(f"healthcheck failed for port={hc_port} targets={targets} within {timeout}s")

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

    def launch_room(
        self,
        room_id: int,
        host: str,
        game: dict,
        players: list[str],
        *,
        match_id: str,
        client_token: str,
        report_token: str,
        temp_dir: Optional[Path] = None,
    ) -> LaunchResult:
        """
        game: {'game_name':..., 'version':..., ...}
        players: list of usernames in room order (p1 = players[0], p2 = players[1], ...)
        """
        if room_id in self._running:
            raise ValueError("room already running")
        manifest = self._load_manifest(game["game_name"], game["version"])
        port = self._alloc_port()
        player_count = len(players)
        players_json = json.dumps(players)
        players_csv = ",".join(players)
        if temp_dir is None:
            self.tmp_base.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix=f"match_{match_id}_", dir=self.tmp_base))
        players_json_path = temp_dir / "players.json"
        client_token_path = temp_dir / "client_token"
        report_token_path = temp_dir / "report_token"
        try:
            players_json_path.write_text(players_json, encoding="utf-8")
            client_token_path.write_text(client_token, encoding="utf-8")
            report_token_path.write_text(report_token, encoding="utf-8")
            try:
                players_json_path.chmod(0o600)
                client_token_path.chmod(0o600)
                report_token_path.chmod(0o600)
            except Exception:
                logger.debug("failed to set restrictive permissions on temp files")
        except Exception:
            logger.exception("failed to write match temp files")
            raise

        ctx = {
            "host": host,
            "port": port,
            "room_id": room_id,
            "match_id": match_id,
            "client_token": client_token,
            "report_token": report_token,
            "client_token_path": str(client_token_path),
            "report_token_path": str(report_token_path),
            "player_name": players[0] if players else "",
            "player_count": player_count,
            "players_json": players_json,
            "players_csv": players_csv,
            "players_json_path": str(players_json_path),
            "bind_host": USER_SERVER_BIND_HOST,
            "report_host": USER_SERVER_HOST,
            "report_port": USER_SERVER_HOST_PORT,
            "platform_protocol_version": PLATFORM_PROTOCOL_VERSION,
            # Uppercase env-friendly keys
            "HOST": host,
            "PORT": port,
            "ROOM_ID": room_id,
            "MATCH_ID": match_id,
            "CLIENT_TOKEN": client_token,
            "REPORT_TOKEN": report_token,
            "CLIENT_TOKEN_PATH": str(client_token_path),
            "REPORT_TOKEN_PATH": str(report_token_path),
            "PLAYERS_JSON": players_json,
            "PLAYERS_CSV": players_csv,
            "PLAYERS_JSON_PATH": str(players_json_path),
            "PLAYER_COUNT": player_count,
            "BIND_HOST": USER_SERVER_BIND_HOST,
            "REPORT_HOST": USER_SERVER_HOST,
            "REPORT_PORT": USER_SERVER_HOST_PORT,
            "PLATFORM_PROTOCOL_VERSION": PLATFORM_PROTOCOL_VERSION,
        }
        for idx, name in enumerate(players, start=1):
            ctx[f"p{idx}"] = name
            ctx[f"P{idx}"] = name

        server_cfg = manifest["server"]
        server_cmd = self._render_cmd(server_cfg["command"], ctx)
        workdir = (self.base / game["game_name"] / str(game["version"]) / server_cfg.get("working_dir", ".")).resolve()
        env = self._build_env(server_cfg.get("env", {}), ctx)
        logger.info(f"Launching room {room_id} server: {server_cmd} (cwd={workdir}, match_id={match_id}, players={players})")

        try:
            popen_kwargs = {"cwd": workdir, "env": env}
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(server_cmd, **popen_kwargs)
            health_timeout = float((manifest.get("healthcheck") or {}).get("timeout_sec", 5) or 5)
            startup_timeout = float(server_cfg.get("startup_timeout", health_timeout) or health_timeout)
            self._running[room_id] = LaunchResult(room_id, port, match_id, client_token, report_token, proc, temp_dir, startup_timeout)
            try:
                self._wait_for_process_start(proc, timeout=startup_timeout)
            except Exception:
                logger.exception(f"room {room_id} server appears unhealthy right after launch; terminating.")
                self.stop_room(room_id)
                raise
            self._diagnostic_healthcheck(manifest, ctx, port)
            logger.info(f"room {room_id} server started (pid={proc.pid}, port={port})")
            return self._running[room_id]
        except Exception:
            # free the port on failure to launch
            logger.exception(f"failed to launch room {room_id}")
            self._release_port(port)
            if temp_dir:
                try:
                    for path in (temp_dir / "players.json", temp_dir / "client_token", temp_dir / "report_token"):
                        try:
                            path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    temp_dir.rmdir()
                except Exception:
                    logger.warning(f"failed to clean temp dir {temp_dir}")
            raise

    def stop_room(self, room_id: int, match_id: Optional[str] = None):
        res = self._running.get(room_id)
        if match_id and res and res.match_id != match_id:
            logger.debug(f"stop_room ignored for room {room_id} (match mismatch)")
            return False
        res = self._running.pop(room_id, None)
        if not res:
            logger.debug(f"stop_room called for non-running room {room_id}")
            return False
        try:
            if res.proc.poll() is None:
                logger.info(f"terminating room {room_id} server pid={res.proc.pid}")
                if os.name != "nt":
                    try:
                        os.killpg(res.proc.pid, signal.SIGTERM)
                    except Exception:
                        res.proc.terminate()
                else:
                    res.proc.terminate()
                try:
                    res.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"room {room_id} server did not terminate gracefully; killing pid={res.proc.pid}")
                    if os.name != "nt":
                        try:
                            os.killpg(res.proc.pid, signal.SIGKILL)
                        except Exception:
                            res.proc.kill()
                    else:
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



