from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path


def _repo_root() -> Path:
    # backend/app/core/logging.py -> parents: core(0), app(1), backend(2), repo(3)
    return Path(__file__).resolve().parents[3]


def _level_from_env(name: str, default: str = "INFO") -> str:
    val = os.getenv(name, default).upper().strip()
    return val if val in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else default


def setup_logging() -> None:
    """
    Configure file loggers:
      logs/addons.log
      logs/api.log
      logs/core.log
      logs/system.log

    Per-file log levels via env:
      SYNTHIA_LOG_ADDONS_LEVEL
      SYNTHIA_LOG_API_LEVEL
      SYNTHIA_LOG_CORE_LEVEL
      SYNTHIA_LOG_SYSTEM_LEVEL
    """
    logs_dir = _repo_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            },
        },
        "handlers": {
            "addons_file": {
                "class": "logging.FileHandler",
                "formatter": "standard",
                "filename": str(logs_dir / "addons.log"),
                "mode": "a",
            },
            "api_file": {
                "class": "logging.FileHandler",
                "formatter": "standard",
                "filename": str(logs_dir / "api.log"),
                "mode": "a",
            },
            "core_file": {
                "class": "logging.FileHandler",
                "formatter": "standard",
                "filename": str(logs_dir / "core.log"),
                "mode": "a",
            },
            "system_file": {
                "class": "logging.FileHandler",
                "formatter": "standard",
                "filename": str(logs_dir / "system.log"),
                "mode": "a",
            },
        },
        "loggers": {
            "synthia.addons": {
                "handlers": ["addons_file"],
                "level": _level_from_env("SYNTHIA_LOG_ADDONS_LEVEL", "INFO"),
                "propagate": False,
            },
            "synthia.api": {
                "handlers": ["api_file"],
                "level": _level_from_env("SYNTHIA_LOG_API_LEVEL", "INFO"),
                "propagate": False,
            },
            "synthia.core": {
                "handlers": ["core_file"],
                "level": _level_from_env("SYNTHIA_LOG_CORE_LEVEL", "INFO"),
                "propagate": False,
            },
            "synthia.system": {
                "handlers": ["system_file"],
                "level": _level_from_env("SYNTHIA_LOG_SYSTEM_LEVEL", "INFO"),
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(config)
