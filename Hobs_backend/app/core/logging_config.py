# app/core/logging_config.py
import os
import logging
from logging.config import dictConfig


def setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO")
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            # INF-5: inject request_id into every log record automatically
            "correlation": {
                "()": "app.core.request_context.CorrelationFilter",
            },
        },
        "formatters": {
            "default": {
                # request_id appears in every line — grep-friendly in production
                "format": "%(asctime)s [%(request_id)s] %(name)s %(levelname)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class":     "logging.StreamHandler",
                "formatter": "default",
                "stream":    "ext://sys.stdout",
                "filters":   ["correlation"],
            },
        },
        "root": {
            "handlers": ["console"],
            "level":    level,
        },
    })
