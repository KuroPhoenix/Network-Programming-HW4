import threading

from loguru import logger
from server.core.auth import Authenticator
from server.core.handlers.auth_handler import register_developer, login_developer, logout_developer
from server.core.handlers.game_handler import list_game, upload_game
from server.core.protocol import ACCOUNT_REGISTER_DEVELOPER, ACCOUNT_LOGIN_DEVELOPER, Message, message_to_dict, \
    GAME_LIST_GAME, GAME_UPLOAD_GAME, ACCOUNT_LOGOUT_DEVELOPER
from server.util.net import create_listener, recv_json_lines, send_json, serve
import developer.dev_config.dev_config as cfg
class DevServer:
    def __init__(self):

        # importing cfg file
        logger.remove()
        logger.add("dev_server.log", rotation="1 MB", level="INFO", mode="w")

        self.host = cfg.HOST_IP
        self.port = cfg.HOST_PORT

        # setting up auth
        self.auth = Authenticator()

    def start_server(self):
        """
        Start the dev server and listen for incoming connections, then accepts connections.
        :return:
        """
        sock = create_listener(self.host, self.port)
        logger.info(f"Dev server listening on {self.host}:{self.port}")
        serve(sock, self.handle_client)

    def handle_client(self, conn, addr):
        logger.info(f"dev client connected: {addr}")
        handlers = {
            ACCOUNT_REGISTER_DEVELOPER: register_developer,
            ACCOUNT_LOGIN_DEVELOPER: login_developer,
            ACCOUNT_LOGOUT_DEVELOPER: logout_developer,
            GAME_LIST_GAME: list_game,
            GAME_UPLOAD_GAME: upload_game,
        }
        with conn:
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
        logger.info(f"dev client disconnected: {addr}")



if __name__ == "__main__":
    server = DevServer()
    server.start_server()

