import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
_FMT = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _file_handler(name: str, level: int) -> RotatingFileHandler:
    h = RotatingFileHandler(
        _LOG_DIR / name,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    h.setFormatter(_FMT)
    h.setLevel(level)
    return h


def setup_logging() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    console = logging.StreamHandler()
    console.setFormatter(_FMT)
    console.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(_file_handler("app.log", logging.INFO))
    root.addHandler(_file_handler("error.log", logging.ERROR))
    root.addHandler(console)

    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


logger = logging.getLogger("edyrix")
