from __future__ import annotations

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def project_root() -> Path:
    return Path(os.getenv("TOOL_WORKSPACE_ROOT", Path.cwd())).resolve()


def log_path() -> Path:
    return project_root() / ".logs" / "deepseek-chat.log"


def setup_logging() -> Path:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("deepseek_chat")
    root.setLevel(logging.INFO)
    if not any(isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(path) for handler in root.handlers):
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    return path


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"deepseek_chat.{name}")
