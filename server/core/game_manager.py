from pathlib import Path
import sqlite3
import bcrypt
import secrets
import json
from loguru import logger
show_entries = "author, game_name, version, type, description, max_players, game_folder"
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
                    description TEXT,
                    max_players INTEGER,
                    game_folder TEXT NOT NULL,
                    metadata_file TEXT NOT NULL,
                    PRIMARY KEY (author, game_name, version, type)
                )
                """
            )
        logger.debug(f"Game schema ensured at {self.db_path}")

    def list_games(self, username, role):
        """
        Bonus to be implemented: Sort by download count
        :param username:
        :param role:
        :return:
        """
        with self._conn_db() as conn:
            if role == "DEVELOPER":
                cur = conn.execute(
                    "SELECT * FROM games WHERE author=?",
                    (username, ),
                )
            elif role == "PLAYER":
                cur = conn.execute(
                    f"SELECT {show_entries} FROM games",
                )
            else:
                return []
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return rows

    def create_game(self, username: str, game_name: str, type: str, version: str, paths: dict):
        """
        Persist a finalized upload by inserting/updating the game record with paths.
        """
        logger.info(f"user {username} has requested createGame with game {game_name}.")
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT version FROM games WHERE author=? AND game_name=? AND type=? ORDER BY version DESC LIMIT 1",
                (username, game_name, type),
            )
            rows = cur.fetchone()
            current_version = rows[0] if rows else None
            if current_version is None:
                # metadata may not exist yet; create fresh record
                new_version = version
                conn.execute(
                    "INSERT INTO games(author, game_name, version, type, description, max_players, game_folder, metadata_file) VALUES(?,?,?,?,?,?,?,?)",
                    (username, game_name, new_version, type, paths.get("description", ""), int(paths.get("max_players", 0) or 0), paths["path"], json.dumps(paths["manifest"]),),
                )
            else:
                # update existing metadata row for this version if it matches, else insert
                new_version = version
                if str(new_version) == str(current_version):
                    conn.execute(
                        "UPDATE games SET game_folder=?, metadata_file=?, description=?, max_players=? WHERE author=? AND game_name=? AND type=? AND version=?",
                        (paths["path"], json.dumps(paths["manifest"]), paths.get("description", ""), int(paths.get("max_players", 0) or 0), username, game_name, type, new_version,),
                    )
                else:
                    conn.execute(
                        "INSERT INTO games(author, game_name, version, type, description, max_players, game_folder, metadata_file) VALUES(?,?,?,?,?,?,?,?)",
                        (username, game_name, new_version, type, paths.get("description", ""), int(paths.get("max_players", 0) or 0), paths["path"], json.dumps(paths["manifest"]),),
                    )
            logger.info(
                f"Game {game_name} (Author: {username}, Version: {version}, Type: {type}) stored at {paths['path']}"
            )

    def create_metadata(self, username: str, game_name: str, type: str, description: str, max_players: int):
        """
        Usage: Devs uploads their store-ready game metadate (exclusive path), either as an update or as a new product
        :param max_players:
        :param description:
        :param username:
        :param game_name:
        :param type:
        :return:
        """
        logger.info(f"user {username} has requested createMetadata with game_name {game_name}, type {type}.")
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
                "INSERT INTO games(author, game_name, version, type, description, max_players, game_folder, metadata_file) VALUES(?,?,?,?,?,?,?,?)",
                (username, game_name, new_version, type, description, max_players, "", ""),
            )
            logger.info(f"added {new_version} version to game {game_name} (type {type})")
            return {
                "author": username,
                "game_name": game_name,
                "version": new_version,
                "type": type,
                "description": description,
                "max_players": max_players,
            }

    def get_game(self, game_name: str):
        with self._conn_db() as conn:
            cur = conn.execute(
                f"SELECT {show_entries} FROM games WHERE game_name=? ORDER BY version DESC LIMIT 1",
                (game_name,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))
