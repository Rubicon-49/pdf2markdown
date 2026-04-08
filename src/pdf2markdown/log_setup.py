"""
log_setup.py — Logging configuration for pdf2markdown.

Call ``setup_logging(project_root)`` once at application startup.
All other modules should obtain their logger with ``logging.getLogger(__name__)``.
"""

import logging
import logging.handlers
from pathlib import Path

_LOG_FILE = "pdf2markdown.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3
_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(project_root: Path, level: int = logging.INFO) -> None:
    """Configure the root logger with a stream handler and a rotating file handler.

    Should be called once at application startup before any loggers are used.
    Log files are written to ``<project_root>/logs/pdf2markdown.log`` and
    rotated at 5 MB with up to 3 backups kept.

    Args:
        project_root: Absolute path to the project root, used to resolve the
            ``logs/`` directory.
        level: Minimum log level for the root logger. Defaults to
            ``logging.INFO``.
    """
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
