from pathlib import Path
import sqlite3
import bcrypt
import secrets
from loguru import logger
from shared.logger import ensure_global_logger, log_dir

# Module-specific error logging plus shared workflow log
LOG_DIR = log_dir()
ensure_global_logger()
logger.add(LOG_DIR / "auth_errors.log", rotation="1 MB", level="ERROR", filter=lambda r: r["file"] == "auth.py")


class Authenticator:
    """
    Handles developer/player registration and login against a single auth DB.
    Table layout: users(username, role, password_hash) with unique(username, role).
    Tracks in-memory session tokens to detect duplicate logins.
    """

    def __init__(self):
        base = Path(__file__).resolve().parent.parent / "data"
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / "auth.db"
        self._init_schema()
        # In-memory session tracking: (username, role) -> token and reverse.
        self.sessions = {}
        self.token_index = {}

    def _conn_db(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_schema(self):
        with self._conn_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    password_hash BLOB NOT NULL,
                    PRIMARY KEY (username, role)
                )
                """
            )
        logger.debug(f"Auth schema ensured at {self.db_path}")

    def register(self, username, password, role):
        """
        Register a new user for a given role. Returns a session token.
        Raises ValueError if the username/role already exists.
        """
        pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT 1 FROM users WHERE username=? AND role=?",
                (username, role),
            )
            if cur.fetchone():
                logger.info(f"Register failed: duplicate username '{username}' role '{role}'")
                raise ValueError("username exists")
            conn.execute(
                "INSERT INTO users(username, role, password_hash) VALUES(?,?,?)",
                (username, role, pwd_hash),
            )
        token = secrets.token_hex(16)
        key = (username, role)
        self.sessions[key] = token
        self.token_index[token] = key
        logger.info(f"Registered user '{username}' with role '{role}'")
        return token

    def login(self, username, password, role):
        """
        Authenticate a user and role. Returns a session token on success; raises ValueError on bad
        credentials or duplicate login.
        """
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT password_hash FROM users WHERE username=? AND role=?",
                (username, role),
            )
            row = cur.fetchone()
            if not row or not bcrypt.checkpw(password.encode(), row[0]):
                logger.info(f"Login failed: bad credentials for '{username}' role '{role}'")
                raise ValueError("bad credentials")

        key = (username, role)
        if key in self.sessions:
            logger.info(f"Login failed: duplicate session for '{username}' role '{role}'")
            raise ValueError("duplicate login")

        token = secrets.token_hex(16)
        self.sessions[key] = token
        self.token_index[token] = key
        logger.info(f"Login success for '{username}' role '{role}'")
        return token

    def logout(self, token):
        """
        Invalidate a session token.
        """
        key = self.token_index.pop(token, None)
        if key:
            self.sessions.pop(key, None)
            logger.info(f"Logout success for '{key[0]}' role '{key[1]}'")
            return True
        logger.info("Logout called with unknown token")
        return False

    def validate(self, token: str, role: str | None = None) -> tuple[str, str]:
        """
        Validate that a session token exists (and optionally matches the expected role).
        Returns (username, role) on success; raises ValueError on failure.
        """
        key = self.token_index.get(token)
        if not key:
            raise ValueError("invalid token")
        if role and key[1] != role:
            raise ValueError("invalid token role")
        return key

    def list_online_players(self, role: str | None = None) -> list[str]:
        """
        Return a list of usernames with active sessions (optionally filtered by role).
        """
        players: list[str] = []
        for username, r in self.sessions.keys():
            if role and r != role:
                continue
            players.append(username)
        return players
