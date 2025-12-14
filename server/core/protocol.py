from dataclasses import dataclass, field, asdict
from typing import Any, Literal

# Namespaced message types to keep dispatch organized by domain.
ACCOUNT_REGISTER_PLAYER = "ACCOUNT.REGISTER_PLAYER"
ACCOUNT_LOGIN_PLAYER = "ACCOUNT.LOGIN_PLAYER"
ACCOUNT_LOGOUT_PLAYER = "ACCOUNT.LOGOUT_PLAYER"
ACCOUNT_REGISTER_DEVELOPER = "ACCOUNT.REGISTER_DEVELOPER"
ACCOUNT_LOGIN_DEVELOPER = "ACCOUNT.LOGIN_DEVELOPER"
ACCOUNT_LOGOUT_DEVELOPER = "ACCOUNT.LOGOUT_DEVELOPER"
GAME_LIST_GAME = "GAME.LIST"
GAME_UPLOAD_METADATA = "GAME.UPLOAD_METADATA"
GAME_UPLOAD_GAME = "GAME.UPLOAD_GAME"
GAME_GET_DETAILS = "GAME.GET_DETAILS"
GAME_UPLOAD_BEGIN = "GAME.UPLOAD_BEGIN"
GAME_UPLOAD_CHUNK = "GAME.UPLOAD_CHUNK"
GAME_UPLOAD_END = "GAME.UPLOAD_END"
GAME_DOWNLOAD_BEGIN = "GAME.DOWNLOAD_BEGIN"
GAME_DOWNLOAD_CHUNK = "GAME.DOWNLOAD_CHUNK"
GAME_DOWNLOAD_END = "GAME.DOWNLOAD_END"
GAME_DOWNLOAD_GAME = "GAME.DOWNLOAD_GAME"
GAME_LATEST_VERSION = "GAME.LATEST_VERSION"
GAME_REPORT = "GAME.REPORT"
GAME_DELETE_GAME = "GAME.DELETE"
LOBBY_LIST_ROOMS = "LOBBY.LIST_ROOMS"
LOBBY_CREATE_ROOM = "LOBBY.CREATE_ROOM"
LOBBY_JOIN_ROOM = "LOBBY.JOIN_ROOM"
LOBBY_LEAVE_ROOM = "LOBBY.LEAVE_ROOM"
USER_LIST = "USER.LIST"
ROOM_LIST = "ROOM.LIST"
ROOM_GET = "ROOM.GET"
ROOM_CREATE = "ROOM.CREATE"
ROOM_JOIN = "ROOM.JOIN"
ROOM_LEAVE = "ROOM.LEAVE"
ROOM_READY = "ROOM.READY"
GAME_START = "GAME.START"
REVIEW_ADD = "REVIEW.ADD"
REVIEW_SEARCH_GAME = "REVIEW.SEARCH_GAME"
REVIEW_SEARCH_AUTHOR = "REVIEW.SEARCH_AUTHOR"
REVIEW_DELETE = "REVIEW.DELETE"
REVIEW_EDIT = "REVIEW.EDIT"
REVIEW_ELIGIBILITY_CHECK = "REVIEW.ELIGIBILITY_CHECK"

@dataclass(frozen=True)
class Message:
    """
    :param type: Message intent
    :param payload: Message payload, varies by message type. It carries values and data essential for function inputs
    :param token: Session/auth token echoed on requests after login
    :param request_id: Correlate responses to requests (Async)
    :param status: Resp. Specific; either "ok" or "error"
    :param code: Message explanation key for status
    :param message: Optional human-readable text for errors/logging
    """
    type: str  # e.g. "LOGIN", "LIST_GAMES", "LOGIN_RESPONSE"
    payload: dict[str, Any] = field(default_factory=dict)
    token: str | None = None
    request_id: str | None = None
    status: Literal["ok", "error"] | None = None  # None for requests
    code: int | None = None  # None for requests
    message: str | None = None


def message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize Message dataclass to a plain dict for JSON transport."""
    return asdict(msg)


def message_from_dict(data: dict[str, Any]) -> Message:
    """Construct a Message from a dict, supplying defaults for missing fields."""
    return Message(
        type=data.get("type", ""),
        payload=data.get("payload") or {},
        token=data.get("token"),
        request_id=data.get("request_id"),
        status=data.get("status"),
        code=data.get("code"),
        message=data.get("message"),
    )

@dataclass(frozen=True)
class AccountReq:
    """
    Unified account request for register/login flows.
    :param intent: "register" or "login"
    :param username: account name
    :param password: secret
    :param role: "player" or "developer"
    :param request_id: optional correlation id
    """
    intent: Literal["register", "login"]
    username: str
    password: str
    role: str
    request_id: str | None = None


@dataclass(frozen=True)
class AccountResp:
    """
    Unified account response envelope data.
    :param status: "ok" or "error"
    :param code: numeric code
    :param message: optional human-readable text
    :param payload: additional data (e.g., session_token)
    :param session_token: issued on success
    """
    status: Literal["ok", "error"]
    code: int
    session_token: str
    message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class GameReq:
    """
    Unified game request for developer_cli -> developer_api <-> developer_server <-> game.
    :param intent: "create" or "list
    :param username: account name
    :session_token: Session/auth token echoed on requests after login
    :param request_id: correlate responses to requests (Async)
    """
    intent: Literal["create", "list"]
    username: str
    session_token: str
    request_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class GameResp:
    """
    Unified game response envelope data.
    :param status: "ok" or "error"
    :param code: numeric code
    :param message: optional human-readable text
    :param payload: additional data (e.g., session_token)
    :param session_token: issued on success
    """
    status: Literal["ok", "error"]
    code: int
    message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
