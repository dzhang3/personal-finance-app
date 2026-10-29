"""Structured logging: logfmt output with a per-job correlation context (decisions 023-025).

Usage:
    import logging
    from app.logging_utils import log_event
    logger = logging.getLogger(__name__)

    log_event(logger, "page_upserted", added=100, modified=3)
    log_event(logger, "fetch_failed", level=logging.WARNING, error_code="RATE_LIMIT_EXCEEDED")

Inside run_job, every line automatically carries job_id, attempt, item_id and
kind (set once by job_context), so no function needs those passed in.

Output (one line per event):
    2026-10-15T21:40:02-0400 INFO app.views job_id=7 attempt=2 item_id=1 kind=sync event=page_upserted added=100
"""
import contextvars
import json
import logging
from contextlib import contextmanager

# Holds the current job's fields. contextvars (not a global) so each thread or
# async task sees its own value, and nested contexts restore cleanly.
_context = contextvars.ContextVar("log_context", default={})

# Never written to logs, whatever a caller passes (access tokens above all).
REDACTED_KEYS = ("token", "secret", "password")


@contextmanager
def job_context(**fields):
    """Attach fields to every log line emitted inside this block."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def log_event(logger, event, level=logging.INFO, exc_info=None, **fields):
    """Log one structured event: a snake_case event name plus key=value fields."""
    logger.log(level, event, exc_info=exc_info, extra={"fields": fields})


class ContextFilter(logging.Filter):
    """Copies the current job context onto each record so the formatter can print it."""

    def filter(self, record):
        record.context = _context.get()
        return True


class LogfmtFormatter(logging.Formatter):
    """time LEVEL logger [context fields] event=<message> [event fields] (+ traceback)."""

    def format(self, record):
        fields = {
            **getattr(record, "context", {}),
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        parts = [
            self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            record.levelname,
            record.name,
        ]
        parts += [f"{key}={_format_value(key, value)}" for key, value in fields.items()]
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _format_value(key, value):
    if any(word in key.lower() for word in REDACTED_KEYS):
        return "[redacted]"
    text = "null" if value is None else str(value)
    # Quote anything that would break key=value parsing.
    if text == "" or any(ch in text for ch in ' ="'):
        return json.dumps(text)
    return text
