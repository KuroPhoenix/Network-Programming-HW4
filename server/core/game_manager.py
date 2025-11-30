from pathlib import Path
import sqlite3
import bcrypt
import secrets
from loguru import logger

class GameManager:
    def __init__(self):
        base = Path(__file__).resolve().parent.parent / "data"
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / "game.db"
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
                CREATE TABLE IF NOT EXISTS games (
                    author TEXT NOT NULL,
                    game_name TEXT NOT NULL,
                    version INTEGER,
                    type TEXT NOT NULL,
                    PRIMARY KEY (author, game_name, version, type)
                )
                """
            )
        logger.debug(f"Game schema ensured at {self.db_path}")

    def list_games(self, username):
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT * FROM games WHERE author=?",
                (username, ),
            )
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return rows

    def create_game(self, username: str, game_name: str, type: str):
        logger.info(f"user {username} has requested createGame with game_name {game_name}, type {type}.")
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT version FROM games WHERE author=? AND game_name=? AND type=? ORDER BY version DESC LIMIT 1",
                (username, game_name, type),
            )
            rows = cur.fetchone()
            new_version = 0
            if rows is not None:
                logger.info(f"game {game_name} already exists. Newest version is {rows[0]}")
                new_version = rows[0] + 1
            conn.execute(
                "INSERT INTO games(author, game_name, version, type) VALUES(?,?,?,?)",
                (username, game_name, new_version, type),
            )
            logger.info(f"added {new_version} version to game {game_name} (type {type})")
            return {"author": username, "game_name": game_name, "version": new_version, "type": type}