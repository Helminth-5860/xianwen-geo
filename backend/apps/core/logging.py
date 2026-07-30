import json
import logging
from datetime import UTC, datetime
from typing import Any

from .context import get_request_id
from .redaction import redact_sensitive_data

LOG_RECORD_STANDARD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id() or "-"

        if isinstance(record.msg, (dict, list, tuple)):
            record.msg = redact_sensitive_data(record.msg)
        if isinstance(record.args, (dict, list, tuple)):
            record.args = redact_sensitive_data(record.args)

        for key, value in tuple(vars(record).items()):
            if key not in LOG_RECORD_STANDARD_FIELDS:
                setattr(record, key, redact_sensitive_data({key: value})[key])
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        for key, value in vars(record).items():
            if key not in LOG_RECORD_STANDARD_FIELDS and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
            payload.setdefault("exception_type", type(record.exc_info[1]).__name__)

        return json.dumps(
            redact_sensitive_data(payload),
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )


def build_logging_config(environment: str) -> dict:
    if environment == "production":
        formatter = {"()": "apps.core.logging.JsonFormatter"}
        root_level = "INFO"
        handler_class = "logging.StreamHandler"
    elif environment == "test":
        formatter = {"format": "%(levelname)s %(name)s %(message)s"}
        root_level = "WARNING"
        handler_class = "logging.NullHandler"
    else:
        formatter = {
            "format": ("%(asctime)s %(levelname)s %(name)s [request_id=%(request_id)s] %(message)s")
        }
        root_level = "INFO"
        handler_class = "logging.StreamHandler"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {"()": "apps.core.logging.RequestContextFilter"},
        },
        "formatters": {"default": formatter},
        "handlers": {
            "console": {
                "class": handler_class,
                "filters": ["request_context"],
                "formatter": "default",
            }
        },
        "root": {"handlers": ["console"], "level": root_level},
        "loggers": {
            "xianwen.request": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "xianwen.api": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
