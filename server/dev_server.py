import threading

from loguru import logger
from server.core.auth import Authenticator
from server.core.game_manager import GameManager
from server.core.handlers.auth_handler import register_developer, login_developer, logout_developer
from server.core.handlers.game_handler import list_game, upload_metadata, upload_begin, upload_end, upload_chunk
from server.core.protocol import ACCOUNT_REGISTER_DEVELOPER, ACCOUNT_LOGIN_DEVELOPER, Message, message_to_dict, \
    GAME_LIST_GAME, GAME_UPLOAD_METADATA, ACCOUNT_LOGOUT_DEVELOPER, GAME_UPLOAD_END, GAME_UPLOAD_BEGIN, GAME_UPLOAD_CHUNK
from server.core.storage_manager import StorageManager
from server.util.net import create_listener, recv_json_lines, send_json, serve
from server.util.validator import require_token
import server.core.config as cfg
class DevServer:
    def __init__(self):

        # importing cfg file
        logger.remove()
        logger.add("dev_server.log", rotation="1 MB", level="INFO", mode="w")

        self.host = cfg.DEV_SERVER_HOST_IP
        self.port = cfg.DEV_SERVER_HOST_PORT

        # setting up modules
        self.auth = Authenticator()
        self.gmgr = GameManager()
        self.smgr = StorageManager()

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
            ACCOUNT_REGISTER_DEVELOPER: lambda p: register_developer(p, self.auth),
            ACCOUNT_LOGIN_DEVELOPER: lambda p: login_developer(p, self.auth),
            ACCOUNT_LOGOUT_DEVELOPER: lambda p: logout_developer(p, self.auth),
            GAME_LIST_GAME: lambda p: list_game(p, self.gmgr),
            GAME_UPLOAD_METADATA: lambda p: upload_metadata(p, self.gmgr),
            GAME_UPLOAD_BEGIN: lambda p: upload_begin(p, self.gmgr, self.smgr),
            GAME_UPLOAD_CHUNK: lambda p: upload_chunk(p, self.smgr),
            GAME_UPLOAD_END: lambda p: upload_end(p, self.gmgr, self.smgr),
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
                        if mtype not in {ACCOUNT_REGISTER_DEVELOPER, ACCOUNT_LOGIN_DEVELOPER}:
                            require_token(self.auth, msg.get("token"), role="developer")
                        data = handler(payload)
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
