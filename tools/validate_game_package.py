#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ALLOWED_PLACEHOLDERS = {
    "host",
    "port",
    "room_id",
    "match_id",
    "client_token",
    "report_token",
    "client_token_path",
    "report_token_path",
    "player_name",
    "player_count",
    "players_json",
    "players_csv",
    "players_json_path",
    "bind_host",
    "report_host",
    "report_port",
    "platform_protocol_version",
}

FORBIDDEN_CMD_PLACEHOLDERS = {"client_token", "report_token"}


def _extract_placeholders(text: str) -> list[str]:
    return re.findall(r"\{([^{}]+)\}", text)


def _is_allowed_placeholder(name: str) -> bool:
    key = name.lower()
    if key in ALLOWED_PLACEHOLDERS:
        return True
    if re.fullmatch(r"p\d+", key):
        return True
    return False


def _alloc_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _render(template: str, ctx: dict[str, Any]) -> str:
    return template.format(**ctx)


def _build_env(base_env: dict[str, Any], ctx: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({k: str(v) for k, v in ctx.items()})
    for key, value in base_env.items():
        try:
            env[key] = str(value).format(**ctx)
        except Exception:
            env[key] = str(value)
    return env


def validate_manifest(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for field in ("game_name", "version", "type", "max_players"):
        if field not in manifest:
            errors.append(f"missing required field: {field}")

    server = manifest.get("server") or {}
    client = manifest.get("client") or {}
    if not server.get("command"):
        errors.append("missing server.command")
    if not client.get("command"):
        errors.append("missing client.command")

    health = manifest.get("healthcheck") or {}
    if "tcp_port" not in health:
        errors.append("missing healthcheck.tcp_port")
    if "timeout_sec" not in health:
        errors.append("missing healthcheck.timeout_sec")

    for section_name, section in ("server", server), ("client", client):
        cmd = section.get("command") or ""
        for placeholder in _extract_placeholders(cmd):
            if not _is_allowed_placeholder(placeholder):
                errors.append(f"{section_name}.command uses unknown placeholder: {{{placeholder}}}")
            if placeholder.lower() in FORBIDDEN_CMD_PLACEHOLDERS:
                errors.append(f"{section_name}.command passes token via args: {{{placeholder}}}")
        env = section.get("env") or {}
        for key, value in env.items():
            for placeholder in _extract_placeholders(str(value)):
                if not _is_allowed_placeholder(placeholder):
                    errors.append(f"{section_name}.env[{key}] uses unknown placeholder: {{{placeholder}}}")

    return errors, warnings


def _report_server(messages: list[dict], host: str, port: int, stop_event: threading.Event):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(5)
        sock.settimeout(0.5)
        while not stop_event.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    f = conn.makefile("r")
                except Exception:
                    continue
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    messages.append(msg)


def smoke_test(manifest: dict[str, Any], game_dir: Path) -> list[str]:
    errors: list[str] = []
    host = "127.0.0.1"
    port = _alloc_port()
    report_port = _alloc_port()
    room_id = 1
    match_id = uuid.uuid4().hex
    client_token = uuid.uuid4().hex
    report_token = uuid.uuid4().hex
    players = ["Player1", "Player2"]

    temp_dir = Path(tempfile.mkdtemp(prefix=f"validate_{match_id}_"))
    players_json_path = temp_dir / "players.json"
    client_token_path = temp_dir / "client_token"
    report_token_path = temp_dir / "report_token"
    try:
        players_json_path.write_text(json.dumps(players), encoding="utf-8")
        client_token_path.write_text(client_token, encoding="utf-8")
        report_token_path.write_text(report_token, encoding="utf-8")
    except Exception as exc:
        errors.append(f"failed to write temp files: {exc}")
        return errors

    ctx = {
        "host": host,
        "port": port,
        "room_id": room_id,
        "match_id": match_id,
        "client_token": client_token,
        "report_token": report_token,
        "client_token_path": str(client_token_path),
        "report_token_path": str(report_token_path),
        "player_name": players[0],
        "player_count": len(players),
        "players_json": json.dumps(players),
        "players_csv": ",".join(players),
        "players_json_path": str(players_json_path),
        "bind_host": host,
        "report_host": host,
        "report_port": report_port,
        "platform_protocol_version": 1,
    }
    for idx, name in enumerate(players, start=1):
        ctx[f"p{idx}"] = name

    server = manifest.get("server") or {}
    cmd = _render(server.get("command", ""), ctx)
    env = _build_env(server.get("env") or {}, ctx)
    workdir = (game_dir / server.get("working_dir", ".")).resolve()

    messages: list[dict] = []
    stop_event = threading.Event()
    report_thread = threading.Thread(target=_report_server, args=(messages, host, report_port, stop_event), daemon=True)
    report_thread.start()

    proc = None
    try:
        proc = subprocess.Popen(shlex.split(cmd), cwd=workdir, env=env)
        deadline = time.time() + float((manifest.get("healthcheck") or {}).get("timeout_sec", 5) or 5)
        started = False
        while time.time() < deadline:
            for msg in list(messages):
                if msg.get("status") == "STARTED" and msg.get("match_id") == match_id:
                    started = True
                    break
            if started:
                break
            time.sleep(0.1)
        if not started:
            errors.append("smoke: did not receive STARTED report in time")
        else:
            try:
                with socket.create_connection((host, port), timeout=2) as conn:
                    hello = {
                        "room_id": room_id,
                        "match_id": match_id,
                        "player_name": players[0],
                        "client_token": client_token,
                        "client_protocol_version": 1,
                    }
                    conn.sendall((json.dumps(hello) + "\n").encode("utf-8"))
                    conn.settimeout(2)
                    resp = conn.recv(4096)
                    if not resp:
                        errors.append("smoke: no handshake response")
                    else:
                        try:
                            payload = json.loads(resp.decode("utf-8").splitlines()[0])
                            if not payload.get("ok"):
                                errors.append("smoke: handshake rejected")
                        except Exception:
                            errors.append("smoke: invalid handshake response")
            except Exception as exc:
                errors.append(f"smoke: handshake failed: {exc}")
    finally:
        stop_event.set()
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        report_thread.join(timeout=1)
        try:
            for path in (players_json_path, client_token_path, report_token_path):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            temp_dir.rmdir()
        except Exception:
            pass

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a game package manifest.")
    parser.add_argument("path", help="Path to game directory or manifest.json")
    parser.add_argument("--smoke", action="store_true", help="Run a lightweight spawn/handshake test")
    args = parser.parse_args()

    path = Path(args.path)
    if path.is_dir():
        manifest_path = path / "manifest.json"
    else:
        manifest_path = path
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}")
        return 2

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to parse manifest: {exc}")
        return 2

    errors, warnings = validate_manifest(manifest)
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"- {w}")
    if errors:
        print("Errors:")
        for e in errors:
            print(f"- {e}")
        return 1

    if args.smoke:
        smoke_errors = smoke_test(manifest, manifest_path.parent)
        if smoke_errors:
            print("Smoke test errors:")
            for e in smoke_errors:
                print(f"- {e}")
            return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
