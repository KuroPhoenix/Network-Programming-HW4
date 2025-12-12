from pathlib import Path
from loguru import logger

# Central logging helpers to fan logs into a shared file under logs/ while
# letting modules keep their own specialized sinks.
_global_sink_id: int | None = None


def log_dir() -> Path:
    base = Path(__file__).resolve().parent.parent / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def ensure_global_logger() -> int:
    """
    Add a global log sink if it hasn't been added yet. Returns the sink id.
    """
    global _global_sink_id
    if _global_sink_id is None:
        _global_sink_id = logger.add(log_dir() / "global.log", rotation="10 MB", level="INFO")
    return _global_sink_id
