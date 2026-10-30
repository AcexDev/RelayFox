# core/logging_config.py
import logging.config
import os

def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
            "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": "logs/app.log",
            "maxBytes": 5_000_000,   # rotate at 5 MB
            "backupCount": 3,        # keep 3 old files
        },
        },
        "root": {
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "handlers": ["console", "file"],
        },
        "loggers": {
            "httpx": {"level": "WARNING"},   # silence noisy libs
            "urllib3": {"level": "WARNING"},
        },
    })