import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DEFAULT_SERVER_HOST: str = os.getenv("SERVER_HOST", "140.113.17.11")

DEV_SERVER_HOST_IP: str = os.getenv("DEV_SERVER_HOST_IP", DEFAULT_SERVER_HOST)
DEV_SERVER_BIND_HOST: str = os.getenv("DEV_SERVER_BIND_HOST", "0.0.0.0")
# Use a different port from the user server to avoid conflicts.
DEV_SERVER_HOST_PORT: int = _env_int("DEV_SERVER_HOST_PORT", 16533)

USER_SERVER_HOST: str = os.getenv("USER_SERVER_HOST", DEFAULT_SERVER_HOST)
USER_SERVER_BIND_HOST: str = os.getenv("USER_SERVER_BIND_HOST", "0.0.0.0")
USER_SERVER_HOST_PORT: int = _env_int("USER_SERVER_HOST_PORT", 16534)

if USER_SERVER_HOST_PORT == DEV_SERVER_HOST_PORT:
    USER_SERVER_HOST_PORT = DEV_SERVER_HOST_PORT + 1

# Control-plane protocol version (match plan.md)
PLATFORM_PROTOCOL_VERSION: int = int(os.getenv("PLATFORM_PROTOCOL_VERSION", "1"))
