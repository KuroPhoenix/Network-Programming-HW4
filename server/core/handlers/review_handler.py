from server.core.review_manager import ReviewManager
from server.core.game_manager import GameManager


def list_review_author(payload: dict, reviewMgr: ReviewManager):
    key = payload.get("author")
    if key:
        reply = reviewMgr.list_author_reviews(key)
        return {"status": "ok", "code": 0, "payload": {"reviews": reply}}
    else:
        return {"status": "error", "code": 1, "payload": payload}


def list_review_game(payload: dict, reviewMgr: ReviewManager):
    game = payload.get("game_name")
    if game:
        reply = reviewMgr.list_game_reviews(game)
        return {"status": "ok", "code": 0, "payload": {"reviews": reply}}
    else:
        return {"status": "error", "code": 1, "payload": payload}


def add_review(payload: dict, reviewMgr: ReviewManager, gmMgr: GameManager):
    content = payload.get("content")
    author = payload.get("author")
    game = payload.get("game_name")
    score = payload.get("score")
    if content and author and game and score is not None:
        reviewMgr.add_review(author, game, content, int(score))
        gmMgr.apply_score_delta(game, int(score), 1)
        return {"status": "ok", "code": 0, "payload": payload}
    else:
        return {"status": "error", "code": 1, "payload": payload}


def delete_review(payload: dict, reviewMgr: ReviewManager, gmMgr: GameManager):
    content = payload.get("content")
    author = payload.get("author")
    game = payload.get("game_name")
    if content and author and game:
        deleted_score = reviewMgr.delete_author_review(author, game, content)
        if deleted_score is not None:
            gmMgr.apply_score_delta(game, -int(deleted_score), -1)
        return {"status": "ok", "code": 0, "payload": payload}
    else:
        return {"status": "error", "code": 1, "payload": payload}


def edit_review(payload: dict, reviewMgr: ReviewManager, gmMgr: GameManager):
    old_content = payload.get("old_content")
    new_content = payload.get("new_content")
    author = payload.get("author")
    game_name = payload.get("game_name")
    new_score = payload.get("score")
    if old_content and author and game_name and new_content and new_score is not None:
        old_score, new_score_val = reviewMgr.edit_review(author, game_name, old_content, new_content, int(new_score))
        delta = int(new_score_val) - int(old_score)
        if delta != 0:
            gmMgr.apply_score_delta(game_name, delta, 0)
        return {"status": "ok", "code": 0, "payload": payload}
    else:
        return {"status": "error", "code": 1, "payload": payload}
