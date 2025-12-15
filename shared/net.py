import json
import socket
from typing import Any, Tuple
from loguru import logger
from server.core.protocol import Message, message_to_dict, message_from_dict


def connect_to_server(host: str, port: int, timeout: float = 5.0) -> Tuple[socket.socket, any]:
    logger.info(f"connecting to {host}:{port}")
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        return sock, sock.makefile("r")
    except Exception as exc:
        logger.exception(f"failed to connect to {host}:{port}: {exc}")
        raise RuntimeError(f"failed to connect to {host}:{port}: {exc}") from exc


def send_message(sock: socket.socket, msg_dict: dict[str, Any]) -> None:
    """Send a Message (as dict) over the socket using newline-delimited JSON."""
    try:
        sock.sendall((json.dumps(msg_dict) + "\n").encode("utf-8"))
    except Exception as exc:
        logger.exception(f"Failed to send message to server: {exc}")
        raise


def recv_message(file_obj) -> dict[str, Any]:
    """Receive a single Message (as dict) from a file-like object."""
    line = file_obj.readline()
    if not line:
        logger.error("Server closed connection unexpectedly")
        raise ConnectionError("Server closed connection")
    try:
        return json.loads(line)
    except Exception as e:
        logger.warning(f"Failed to parse message from server: {e} (payload: {line!r})")
        raise


def send_request(
    sock: socket.socket,
    file_obj,
    token: str | None,
    mtype: str,
    payload: dict[str, Any],
    request_id: str | None = None,
    response_timeout: float | None = 10.0,
) -> Message:
    msg = Message(type=mtype, payload=payload, token=token, request_id=request_id)
    try:
        send_message(sock, message_to_dict(msg))
    except Exception as exc:
        return Message(type=mtype or "", status="error", code=199, message=f"send failed: {exc}")

    previous_timeout = None
    try:
        previous_timeout = sock.gettimeout()
        if response_timeout is not None:
            sock.settimeout(response_timeout)
        raw = recv_message(file_obj)
    except socket.timeout:
        logger.error(f"request {mtype} timed out after {response_timeout}s")
        return Message(type=mtype or "", status="error", code=408, message="request timed out")
    except Exception as exc:
        logger.exception(f"request {mtype} failed: {exc}")
        return Message(type=mtype or "", status="error", code=199, message=str(exc))
    finally:
        try:
            if previous_timeout is not None:
                sock.settimeout(previous_timeout)
        except Exception:
            pass

    try:
        return message_from_dict(raw)
    except Exception as exc:
        logger.exception(f"Failed to decode response for {mtype}: {exc}")
        return Message(type=mtype or "", status="error", code=199, message=str(exc))



