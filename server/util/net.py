import socket, json, threading
from typing import Tuple
from loguru import logger

def create_listener(host: str, port: int, *, backlog: int = 5, reuse_addr: bool = True) -> socket.socket:
    """
    :param host: IP address of the server
    :param port: TCP port of the server
    :param backlog: max number of pending connection attempts the kernel will queue before it starts refusing new ones.
    :param reuse_addr: SO_REUSEADDR lets you bind to a (host, port) that’s in TIME_WAIT instead of waiting for it to expire. It’s commonly set on servers so a restart can rebind immediately.
    :return:
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if reuse_addr:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(backlog)
    logger.info(f"listening on {host}:{port}")
    return s


def recv_json_lines(conn):
    """
    reads JSON lines from a socket connection
    :param conn:
    :return:
    """
    with conn.makefile("r") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception as e:
                logger.warning(f"failed to parse JSON line; closing connection: {e}")
                break


def send_json(conn, obj):
    """
    sends JSON object to a socket connection
    :param conn:
    :param obj:
    :return:
    """
    try:
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))
    except Exception as e:
        logger.warning(f"failed to send JSON; closing connection soon: {e}")


def serve(sock: socket.socket, handler):
    """
    accepts connections from a socket connection and processes them
    :param sock:
    :param handler: Function pointer
    :return:
    """
    while True:
        try:
            conn, addr = sock.accept()
        except Exception as e:
            logger.error(f"accept failed: {e}")
            continue
        threading.Thread(target=handler, args=(conn, addr), daemon=True).start()
