import threading

from loguru import logger
from server.core.auth import Authenticator
from server.core.handlers.auth_handler import register_player, login_player
from server.core.protocol import ACCOUNT_REGISTER_PLAYER, ACCOUNT_LOGIN_PLAYER
from server.util.net import create_listener, recv_json_lines, send_json, serve
import user.config.user_config as cfg
from server.core.protocol import Message, message_to_dict


class user_server:
    def __init__(self):

        # importing cfg file
        logger.remove()
        logger.add("user_server.log", rotation="1 MB", level="INFO", mode="w")
        self.host = cfg.HOST_IP
        self.port = cfg.HOST_PORT

        # setting up auth
        self.auth = Authenticator()

    def start_server(self):
        """
        Start the user server and listen for incoming connections, then accepts connections.
        :return:
        """
        sock = create_listener(self.host, self.port)
        logger.info(f"user server listening on {self.host}:{self.port}")
        serve(sock, self.handle_client)

    def handle_client(self, conn, addr):
        logger.info(f"user client connected: {addr}")
        handlers = {
            ACCOUNT_REGISTER_PLAYER: register_player,
            ACCOUNT_LOGIN_PLAYER: login_player,
        }
        with (conn):
            for msg in recv_json_lines(conn):
                mtype = msg.get("type")
                payload = msg.get("payload", {}) or {}
                handler = handlers.get(mtype)
                try:
                    if not handler:
                        reply = Message(type=mtype or "", status="error", code=100, message="UNKNOWN_TYPE")
                    else:
                        data = handler(payload, self.auth)
                        reply = Message(
                            type=mtype or "",
                            status=data.get("status"),
                            code=data.get("code"),
                            message=data.get("message"),
                            payload=data.get("payload", {}),
                        )
                except ValueError as e:
                    code = 104 if "REGISTER" in (mtype or "") else 101
                    reply = Message(type=mtype or "", status="error", code=code, message=str(e))
                except Exception as e:
                    logger.exception("handler error")
                    reply = Message(type=mtype or "", status="error", code=199, message=str(e))
                send_json(conn, message_to_dict(reply))
        logger.info(f"user client disconnected: {addr}")



if __name__ == "__main__":
    server = user_server()
    server.start_server()

