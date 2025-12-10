from typing import Callable
from server.core.auth import Authenticator


def require_token(auth: Authenticator, token: str | None, role: str | None = None):
    """
    Validate a session token (and optional role). Raises ValueError on failure.
    """
    if not token:
        raise ValueError("missing token")
    auth.validate(token, role=role)
    return True


def wrap_auth(handler: Callable, auth: Authenticator, role: str | None = None):
    """
    Decorator-like helper to enforce token validation before calling the handler.
    Returns a function that takes (payload, msg) where msg is the full envelope.
    """
    def _wrapped(payload: dict, msg: dict):
        require_token(auth, msg.get("token"), role=role)
        return handler(payload)
    return _wrapped
