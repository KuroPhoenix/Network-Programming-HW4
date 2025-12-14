from pathlib import Path
import sqlite3
import bcrypt
import secrets
import json
from loguru import logger
from shared.logger import ensure_global_logger, log_dir

# Module-specific error logging plus shared workflow log
LOG_DIR = log_dir()
ensure_global_logger()
logger.add(LOG_DIR / "game_manager_errors.log", rotation="1 MB", level="ERROR", filter=lambda r: r["file"] == "game_manager.py")
show_entries = "author, game_name, version, type, description, avg_score, review_count, max_players, game_folder"
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
                    version TEXT,
                    type TEXT NOT NULL,
                    description TEXT,
                    avg_score FLOAT DEFAULT 0,
                    review_count INTEGER DEFAULT 0,
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
        role_norm = (role or "").upper()
        with self._conn_db() as conn:
            if role_norm == "DEVELOPER":
                cur = conn.execute(
                    "SELECT * FROM games WHERE author=?",
                    (username, ),
                )
            elif role_norm == "PLAYER":
                cur = conn.execute(
                    f"SELECT {show_entries} FROM games",
                )
            else:
                return []
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return rows

    def apply_score_delta(self, game_name: str, delta_score: float, delta_count: int):
        """
        Adjust average score/review count for a game by applying a delta.
        delta_count should be +1 on add, -1 on delete, 0 on edit; delta_score is the
        score difference (e.g., +new_score on add, -old_score on delete, new-old on edit).
        """
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT avg_score, review_count, author FROM games WHERE game_name=? ORDER BY version DESC LIMIT 1",
                (game_name,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"game {game_name} not found for score update")
            avg_score, count, author = row
            count = count or 0
            new_count = count + delta_count
            if new_count < 0:
                new_count = 0
            if new_count == 0:
                new_avg = 0
            else:
                new_avg = (avg_score * count + delta_score) / new_count
            conn.execute(
                "UPDATE games SET avg_score=?, review_count=? WHERE author=? AND game_name=?",
                (new_avg, new_count, author, game_name),
            )


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

    def delete_game(self, username: str, game_name: str) -> tuple[list[str], int]:
        """
        Delete all versions of a game owned by `username`.
        Returns (game_folder paths, number of DB rows deleted) for storage/cleanup.
        """
        logger.info(f"user {username} has requested deleteGame with game {game_name}.")
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT game_folder FROM games WHERE author=? AND game_name=?",
                (username, game_name),
            )
            rows = cur.fetchall()
            if not rows:
                raise ValueError("game not found or not owned by user")
            folders = [row[0] for row in rows if row and row[0]]
            deleted_rows = len(rows)
            conn.execute(
                "DELETE FROM games WHERE author=? AND game_name=?",
                (username, game_name),
            )
        logger.info(f"Deleted game {game_name} for author {username} from DB.")
        # Deduplicate while preserving order
        return list(dict.fromkeys(folders)), deleted_rows

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
                new_version = int(rows[0]) + 1
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
