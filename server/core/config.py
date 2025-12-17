import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DEV_SERVER_HOST_IP: str = os.getenv("DEV_SERVER_HOST_IP", "127.0.0.1")
# Use a different port from the user server to avoid conflicts.
DEV_SERVER_HOST_PORT: int = _env_int("DEV_SERVER_HOST_PORT", 16533)

USER_SERVER_HOST: str = os.getenv("USER_SERVER_HOST", "127.0.0.1")
USER_SERVER_BIND_HOST: str = os.getenv("USER_SERVER_BIND_HOST", "0.0.0.0")
USER_SERVER_HOST_PORT: int = _env_int("USER_SERVER_HOST_PORT", 16534)

# Control-plane protocol version (match plan.md)
PLATFORM_PROTOCOL_VERSION: int = int(os.getenv("PLATFORM_PROTOCOL_VERSION", "1"))
