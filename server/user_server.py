import threading

from loguru import logger
from server.core.auth import Authenticator
from server.core.game_manager import GameManager
from server.core.storage_manager import StorageManager
from server.core.handlers.auth_handler import register_player, login_player, logout_player
from server.core.handlers.game_handler import list_game, detail_game, download_begin, download_chunk, download_end
from server.core.handlers.lobby_handler import list_rooms, create_room, join_room, leave_room
from server.core.protocol import ACCOUNT_REGISTER_PLAYER, ACCOUNT_LOGIN_PLAYER, GAME_LIST_GAME, ACCOUNT_LOGOUT_PLAYER, \
    GAME_GET_DETAILS, GAME_DOWNLOAD_BEGIN, GAME_DOWNLOAD_CHUNK, GAME_DOWNLOAD_END, LOBBY_LIST_ROOMS, \
    LOBBY_CREATE_ROOM, LOBBY_JOIN_ROOM, LOBBY_LEAVE_ROOM
from server.util.net import create_listener, recv_json_lines, send_json, serve
import user.config.user_config as cfg
from server.core.protocol import Message, message_to_dict
from server.core.room_genie import RoomGenie


class user_server:
    def __init__(self):

        # importing cfg file
        logger.remove()
        logger.add("user_server.log", rotation="1 MB", level="INFO", mode="w")
        self.host = cfg.HOST_IP
        self.port = cfg.HOST_PORT

        # setting up auth + game/storage managers
        self.auth = Authenticator()
        self.gmgr = GameManager()
        self.smgr = StorageManager()
        self.lobby = RoomGenie()

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
            ACCOUNT_REGISTER_PLAYER: lambda p: register_player(p, self.auth),
            ACCOUNT_LOGIN_PLAYER: lambda p: login_player(p, self.auth),
            ACCOUNT_LOGOUT_PLAYER: lambda p: logout_player(p, self.auth),
            GAME_LIST_GAME: lambda p: list_game(p, self.gmgr),
            GAME_GET_DETAILS: lambda p: detail_game(p, self.gmgr),
            GAME_DOWNLOAD_BEGIN: lambda p: download_begin(p, self.gmgr, self.smgr),
            GAME_DOWNLOAD_CHUNK: lambda p: download_chunk(p, self.smgr),
            GAME_DOWNLOAD_END: lambda p: download_end(p, self.smgr),
            LOBBY_LIST_ROOMS: lambda p: list_rooms(self.lobby),
            LOBBY_CREATE_ROOM: lambda p: create_room(p, self.gmgr, self.lobby),
            LOBBY_JOIN_ROOM: lambda p: join_room(p, self.lobby),
            LOBBY_LEAVE_ROOM: lambda p: leave_room(p, self.lobby),
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
        logger.info(f"user client disconnected: {addr}")



if __name__ == "__main__":
    server = user_server()
    server.start_server()

