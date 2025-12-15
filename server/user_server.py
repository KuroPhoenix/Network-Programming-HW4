import threading

from loguru import logger
from server.core.auth import Authenticator
from server.core.game_manager import GameManager
from server.core.review_manager import ReviewManager
from server.core.storage_manager import StorageManager
from server.core.handlers.auth_handler import register_player, login_player, logout_player
from server.core.handlers.review_handler import list_review_game, list_review_author, delete_review, add_review, edit_review, check_review_eligibility
from server.core.handlers.game_handler import list_game, detail_game, download_begin, download_chunk, download_end, report_game, start_game, latest_version
from server.core.handlers.lobby_handler import list_rooms, create_room, join_room, leave_room, get_room, list_players, ready_room
from server.core.protocol import ACCOUNT_REGISTER_PLAYER, ACCOUNT_LOGIN_PLAYER, GAME_LIST_GAME, ACCOUNT_LOGOUT_PLAYER, \
    GAME_GET_DETAILS, GAME_DOWNLOAD_BEGIN, GAME_DOWNLOAD_CHUNK, GAME_DOWNLOAD_END, GAME_LATEST_VERSION, LOBBY_LIST_ROOMS, \
    LOBBY_CREATE_ROOM, LOBBY_JOIN_ROOM, LOBBY_LEAVE_ROOM, GAME_REPORT, GAME_START, REVIEW_SEARCH_AUTHOR, REVIEW_DELETE, \
    REVIEW_EDIT, REVIEW_SEARCH_GAME, REVIEW_ADD, ROOM_GET, USER_LIST, REVIEW_ELIGIBILITY_CHECK, ROOM_READY
from server.util.net import create_listener, recv_json_lines, send_json, serve
from server.util.validator import require_token
from server.core.config import USER_SERVER_HOST, USER_SERVER_HOST_PORT
from server.core.protocol import Message, message_to_dict
from server.core.room_genie import RoomGenie
from server.core.game_launcher import GameLauncher
from shared.logger import ensure_global_logger, log_dir

class user_server:
    def __init__(self):

        LOG_DIR = log_dir()
        log_file_path = LOG_DIR / "user_server.log"
        try:
            with open(log_file_path, 'w'):
                pass
            logger.info(f"Log file '{log_file_path}' cleared successfully.")
        except IOError as e:
            logger.error(f"Error clearing log file: {e}")

        # Re-add the log file handler if needed (e.g. at the start of your application)
        ensure_global_logger()
        logger.add(log_file_path, rotation="500 MB")
        self.host = USER_SERVER_HOST
        self.port = USER_SERVER_HOST_PORT

        # setting up auth + game/storage managers
        self.auth = Authenticator()
        self.gmgr = GameManager()
        self.smgr = StorageManager()
        self.genie = RoomGenie()
        self.gmLauncher = GameLauncher()
        self.reviewMgr = ReviewManager()
    def start_server(self):
        """
        Start the user server and listen for incoming connections, then accepts connections.
        :return:
        """
        sock = create_listener(self.host, self.port)
        logger.info(f"user server listening on {self.host}:{self.port}")
        try:
            serve(sock, self.handle_client)
        except KeyboardInterrupt:
            logger.info("User server shutting down by KeyboardInterrupt")
            self._shutdown_rooms()
        except Exception as exc:
            logger.exception(f"User server encountered fatal error: {exc}")
            self._shutdown_rooms()
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def handle_client(self, conn, addr):
        logger.info(f"user client connected: {addr}")
        try:
            conn.settimeout(300)
        except Exception:
            pass
        handlers = {
            ACCOUNT_REGISTER_PLAYER: lambda p: register_player(p, self.auth),
            ACCOUNT_LOGIN_PLAYER: lambda p: login_player(p, self.auth),
            ACCOUNT_LOGOUT_PLAYER: lambda p: logout_player(p, self.auth),
            GAME_LIST_GAME: lambda p: list_game(p, self.gmgr),
            GAME_GET_DETAILS: lambda p: detail_game(p, self.gmgr),
            GAME_DOWNLOAD_BEGIN: lambda p: download_begin(p, self.gmgr, self.smgr),
            GAME_DOWNLOAD_CHUNK: lambda p: download_chunk(p, self.smgr),
            GAME_DOWNLOAD_END: lambda p: download_end(p, self.smgr),
            GAME_LATEST_VERSION: lambda p: latest_version(p, self.gmgr, self.smgr),
            LOBBY_LIST_ROOMS: lambda p: list_rooms(self.genie),
            LOBBY_CREATE_ROOM: lambda p: create_room(p, self.gmgr, self.genie),
            LOBBY_JOIN_ROOM: lambda p: join_room(p, self.genie),
            LOBBY_LEAVE_ROOM: lambda p: leave_room(p, self.genie, self.gmLauncher),
            ROOM_READY: lambda p: ready_room(p, self.genie),
            GAME_REPORT: lambda p: report_game(p, self.genie, self.gmLauncher, self.reviewMgr),
            GAME_START: lambda p: start_game(p, self.gmLauncher, self.genie, self.gmgr),
            ROOM_GET: lambda p: get_room(p, self.genie),
            REVIEW_SEARCH_GAME: lambda p: list_review_game(p, self.reviewMgr),
            REVIEW_EDIT: lambda p: edit_review(p, self.reviewMgr, self.gmgr),
            REVIEW_DELETE: lambda p: delete_review(p, self.reviewMgr, self.gmgr),
            REVIEW_ADD: lambda p: add_review(p, self.reviewMgr, self.gmgr),
            REVIEW_SEARCH_AUTHOR: lambda p: list_review_author(p, self.reviewMgr),
            REVIEW_ELIGIBILITY_CHECK: lambda p: check_review_eligibility(p, self.reviewMgr, self.gmgr),
            USER_LIST: lambda p: list_players(p, self.auth),

        }
        no_auth_types = {ACCOUNT_REGISTER_PLAYER, ACCOUNT_LOGIN_PLAYER, GAME_REPORT}
        current_token: str | None = None
        current_username: str | None = None
        with (conn):
            try:
                for msg in recv_json_lines(conn):
                    mtype = msg.get("type")
                    payload = msg.get("payload", {}) or {}
                    try:
                        logger.info(f"recv type={mtype} user={payload.get('username') or payload.get('author')} keys={list(payload.keys())}")
                    except Exception:
                        pass
                    # Allow raw GAME.REPORT frames from game servers (no payload envelope).
                    if mtype == GAME_REPORT and not payload:
                        payload = {k: v for k, v in msg.items() if k != "type"}
                    handler = handlers.get(mtype)
                    try:
                        if not handler:
                            reply = Message(type=mtype or "", status="error", code=100, message="UNKNOWN_TYPE")
                        else:
                            if mtype not in no_auth_types:
                                require_token(self.auth, msg.get("token"), role="player")
                                username, role = self.auth.validate(msg.get("token"), role="player")
                                current_username = username
                                payload["username"] = username
                                payload["author"] = username
                                payload["role"] = role
                                current_token = msg.get("token") or current_token
                            data = handler(payload)
                            if mtype in {ACCOUNT_REGISTER_PLAYER, ACCOUNT_LOGIN_PLAYER} and data.get("status") == "ok":
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
            except Exception as loop_exc:
                logger.exception(f"unhandled error while processing client {addr}: {loop_exc}")
        if current_token or current_username:
            username = current_username
            if not username and current_token:
                try:
                    username, _ = self.auth.validate(current_token, role="player")
                except Exception:
                    username = None
            if username:
                try:
                    self.genie.remove_user_from_rooms(username, self.gmLauncher)
                except Exception as e:
                    logger.error(f"Failed to remove user {username} from rooms on disconnect: {e}")
            if current_token:
                self.auth.logout(current_token)
        logger.info(f"user client disconnected: {addr}")

    def _shutdown_rooms(self):
        """
        Stop any running game servers and clear room state.
        """
        for rid in list(self.genie.rooms.keys()):
            try:
                logger.info(f"shutting down room {rid} during server shutdown")
                self.gmLauncher.stop_room(rid)
            except Exception as exc:
                logger.error(f"Failed to stop room {rid} during shutdown: {exc}")
        self.genie.rooms.clear()



if __name__ == "__main__":
    server = user_server()
    server.start_server()
