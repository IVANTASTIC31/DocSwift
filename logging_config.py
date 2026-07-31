from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from project_store import default_database_path


LOG_NAME = "docswift.log"


def default_log_directory() -> Path:
    return default_database_path().parent / "logs"


def default_log_path() -> Path:
    return default_log_directory() / LOG_NAME


def configure_logging(log_path: str | Path | None = None) -> Path:
    """Configure one UTF-8 rotating application log for GUI and worker errors."""
    path = Path(log_path) if log_path is not None else default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == path.resolve()
        for handler in root.handlers
    ):
        handler = RotatingFileHandler(
            path,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | "
                "%(threadName)s | %(message)s"
            )
        )
        root.addHandler(handler)
    return path


def install_exception_hook() -> None:
    previous_hook = sys.excepthook

    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("docswift.crash").critical(
            "未捕获异常",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        previous_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception
