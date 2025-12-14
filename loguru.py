"""
Lightweight stub of the loguru logger to allow running without the external dependency.
Provides the subset of methods used in this project.
"""
import logging


class _StubLogger:
    def __init__(self):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        self._logger = logging.getLogger("loguru_stub")

    def add(self, *args, **kwargs):
        # Ignore handler configuration in the stub.
        return None

    def info(self, msg: str, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._logger.debug(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        self._logger.exception(msg, *args, **kwargs)


logger = _StubLogger()

