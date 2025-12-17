import threading

from loguru import logger
from server.core.auth import Authenticator
from server.core.game_manager import GameManager
from server.core.handlers.auth_handler import register_developer, login_developer, logout_developer
from server.core.handlers.game_handler import list_game, upload_metadata, upload_begin, upload_end, upload_chunk, delete_game
from server.core.handlers.lobby_handler import list_players
from server.core.protocol import ACCOUNT_REGISTER_DEVELOPER, ACCOUNT_LOGIN_DEVELOPER, Message, message_to_dict, \
    GAME_LIST_GAME, GAME_UPLOAD_METADATA, ACCOUNT_LOGOUT_DEVELOPER, GAME_UPLOAD_END, GAME_UPLOAD_BEGIN, \
    GAME_UPLOAD_CHUNK, GAME_DELETE_GAME, USER_LIST
from server.core.storage_manager import StorageManager
from server.util.net import create_listener, recv_json_lines, send_json, serve
from server.util.validator import require_token
import server.core.config as cfg
from server.core.review_manager import ReviewManager
from shared.logger import ensure_global_logger, log_dir

class DevServer:
    def __init__(self):

        # importing cfg file
        LOG_DIR = log_dir()
        log_file_path = LOG_DIR / "dev_server.log"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(log_file_path, 'w'):
                pass
            logger.info(f"Log file '{log_file_path}' cleared successfully.")
        except IOError as e:
            logger.error(f"Error clearing log file: {e}")

        # Re-add the log file handler if needed (e.g. at the start of your application)
        ensure_global_logger()
        logger.add(log_file_path, rotation="500 MB")

        self.host = cfg.DEV_SERVER_HOST_IP
        self.bind_host = cfg.DEV_SERVER_BIND_HOST
        self.port = cfg.DEV_SERVER_HOST_PORT

        # setting up modules
        self.auth = Authenticator()
        self.gmgr = GameManager()
        self.smgr = StorageManager()
        self.reviewMgr = ReviewManager()

    def start_server(self):
        """
        Start the dev server and listen for incoming connections, then accepts connections.
        :return:
        """
        sock = create_listener(self.bind_host, self.port)
        logger.info(f"Dev server listening on {self.bind_host}:{self.port}")
        try:
            serve(sock, self.handle_client)
        except KeyboardInterrupt:
            logger.info("Dev server shutting down by KeyboardInterrupt")
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def handle_client(self, conn, addr):
        logger.info(f"dev client connected: {addr}")
        try:
            conn.settimeout(300)
        except Exception:
            pass
        handlers = {
            ACCOUNT_REGISTER_DEVELOPER: lambda p: register_developer(p, self.auth),
            ACCOUNT_LOGIN_DEVELOPER: lambda p: login_developer(p, self.auth),
            ACCOUNT_LOGOUT_DEVELOPER: lambda p: logout_developer(p, self.auth),
            GAME_LIST_GAME: lambda p: list_game(p, self.gmgr),
            GAME_UPLOAD_METADATA: lambda p: upload_metadata(p, self.gmgr),
            GAME_UPLOAD_BEGIN: lambda p: upload_begin(p, self.smgr),
            GAME_UPLOAD_CHUNK: lambda p: upload_chunk(p, self.smgr),
            GAME_UPLOAD_END: lambda p: upload_end(p, self.gmgr, self.smgr),
            GAME_DELETE_GAME: lambda p: delete_game(p, self.gmgr, self.smgr, self.reviewMgr),
            USER_LIST: lambda p: list_players(p, self.auth),
        }
        current_token: str | None = None
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
                            username, role = self.auth.validate(msg.get("token"), role="developer")
                            payload["username"] = username
                            payload["author"] = username
                            payload["role"] = role
                            current_token = msg.get("token") or current_token
                        data = handler(payload)
                        if mtype in {ACCOUNT_REGISTER_DEVELOPER, ACCOUNT_LOGIN_DEVELOPER} and data.get("status") == "ok":
                            current_token = (data.get("payload") or {}).get("session_token", current_token)
                        reply = Message(
                            type=mtype or "",
                            status=data.get("status"),
                            code=data.get("code"),
                            message=data.get("message"),
                            payload=data.get("payload", {}),
                        )
                except ValueError as e:
                    code = 104 if "REGISTER" in (mtype or "") else 101
                    logger.warning(f"handler value error type={mtype} payload_keys={list(payload.keys())} err={e}")
                    reply = Message(type=mtype or "", status="error", code=code, message=str(e))
                except Exception as e:
                    logger.exception("handler error")
                    reply = Message(type=mtype or "", status="error", code=199, message=str(e))
                send_json(conn, message_to_dict(reply))
        if current_token:
            self.auth.logout(current_token)
        logger.info(f"dev client disconnected: {addr}")



if __name__ == "__main__":
    server = DevServer()
    server.start_server()
