from pathlib import Path
import sqlite3
from loguru import logger

# Module-specific error logging
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.add(LOG_DIR / "review_manager_errors.log", rotation="1 MB", level="ERROR", filter=lambda r: r["file"] == "review_manager.py")
show_entries = "author, game_name, version, type, description, max_players, game_folder"

class ReviewManager:
    def __init__(self):
        base = Path(__file__).resolve().parent.parent / "data"
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / "reviews.db"
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
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    author TEXT NOT NULL,
                    game_name TEXT NOT NULL,
                    content TEXT,
                    score INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
        logger.debug(f"Review schema ensured at {self.db_path}")

    def _validate_score(self, score: int | None):
        if score is None:
            raise ValueError("score required")
        if not isinstance(score, int) or score < 1 or score > 5:
            raise ValueError("score must be an integer between 1 and 5")

    def get_review_score(self, author: str, game_name: str, content: str) -> int | None:
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT score FROM reviews WHERE author=? AND game_name=? AND content=?",
                (author, game_name, content),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def add_review(self, author: str, game_name: str, content: str, score: int):
        self._validate_score(score)
        with self._conn_db() as conn:
            conn.execute(
                "INSERT INTO reviews (author, game_name, content, score) VALUES (?, ?, ?, ?)",
                    (author, game_name, content, score)
            )
        logger.info(f"Added review {author} | {game_name}: {content} to review_manager.db")
        return score

    def list_game_reviews(self, game_name: str):
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT author, content, score FROM reviews WHERE game_name = ?",
                (game_name,)
            )
            logger.info(f"Listed reviews for {game_name}")
            rows = cur.fetchall()
            return [{"author": a, "game_name": game_name, "content": c, "score": s} for a, c, s in rows]

    def list_author_reviews(self, author: str):
        with self._conn_db() as conn:
            cur = conn.execute(
                "SELECT game_name, content, score FROM reviews WHERE author = ?",
                (author,)
            )
            rows = cur.fetchall()
            logger.info(f"Listed reviews for {author}")
            return [{"author": author, "game_name": g, "content": c, "score": s} for g, c, s in rows]

    def delete_author_review(self, author: str, game_name: str, content: str):
        score = self.get_review_score(author, game_name, content)
        with self._conn_db() as conn:
            conn.execute(
                "DELETE FROM reviews WHERE author = ? AND game_name = ? AND content = ?",
                (author, game_name, content)
            )
            logger.info(f"Deleted review {author} | {game_name}: {content}")
        return score

    def edit_review(self, author: str, game_name: str, old_content: str, new_content: str, new_score: int):
        self._validate_score(new_score)
        logger.info(f"Editing review {author} | {game_name}: {old_content} to {new_content}")
        old_score = self.get_review_score(author, game_name, old_content)
        if old_score is None:
            raise ValueError("review not found for edit")
        with self._conn_db() as conn:
            conn.execute(
                "UPDATE reviews SET content = ?, score = ? WHERE author = ? AND game_name = ? AND content = ?",
                (new_content, new_score, author, game_name, old_content),
            )
        return old_score, new_score




