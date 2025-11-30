from server.core.auth import Authenticator


def register_player(payload: dict, auth: Authenticator) -> dict:
    """
    Handle player registration and return a response envelope dict.
    """
    token = auth.register(payload["username"], payload["password"], "player")
    return {"status": "ok", "code": 0, "payload": {"session_token": token}}


def login_player(payload: dict, auth: Authenticator) -> dict:
    """
    Handle player login and return a response envelope dict.
    """
    token = auth.login(payload["username"], payload["password"], "player")
    return {"status": "ok", "code": 0, "payload": {"session_token": token}}


def register_developer(payload: dict, auth: Authenticator) -> dict:
    """
    Handle developer registration and return a response envelope dict.
    """
    token = auth.register(payload["username"], payload["password"], "developer")
    return {"status": "ok", "code": 0, "payload": {"session_token": token}}


def login_developer(payload: dict, auth: Authenticator) -> dict:
    """
    Handle developer login and return a response envelope dict.
    """
    token = auth.login(payload["username"], payload["password"], "developer")
    return {"status": "ok", "code": 0, "payload": {"session_token": token}}



