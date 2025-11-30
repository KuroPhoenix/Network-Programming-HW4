import json
import socket
from typing import Any, Tuple
from loguru import logger
from server.core.protocol import Message, message_to_dict, message_from_dict


def connect_to_server(host: str, port: int, timeout: float = 5.0) -> Tuple[socket.socket, any]:
    logger.info(f"connecting to {host}:{port}")
    sock = socket.create_connection((host, port), timeout=timeout)
    return sock, sock.makefile("r")


def send_message(sock: socket.socket, msg_dict: dict[str, Any]) -> None:
    """Send a Message (as dict) over the socket using newline-delimited JSON."""
    sock.sendall((json.dumps(msg_dict) + "\n").encode("utf-8"))


def recv_message(file_obj) -> dict[str, Any]:
    """Receive a single Message (as dict) from a file-like object."""
    line = file_obj.readline()
    if not line:
        raise ConnectionError("Server closed connection")
    return json.loads(line)


def send_request(sock: socket.socket, file_obj, token: str | None, mtype: str, payload: dict[str, Any],
                 request_id: str | None = None) -> Message:
    msg = Message(type=mtype, payload=payload, token=token, request_id=request_id)
    send_message(sock, message_to_dict(msg))
    raw = recv_message(file_obj)
    return message_from_dict(raw)





