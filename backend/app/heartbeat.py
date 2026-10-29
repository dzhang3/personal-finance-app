"""Dead-man's switch: the worker pings an external monitor every loop tick (decision 031).

The monitor (healthchecks.io) alerts to Discord when pings STOP, so the alert
fires even when the worker itself is dead, frozen, or stuck inside a job. That's
the point: an alert sent by the worker can't report the worker's own death.

The ping URL contains a secret ID; it lives in the HEALTHCHECK_PING_URL env var
and is never logged.
"""
import logging
import os
import urllib.request

from app.logging_utils import log_event

logger = logging.getLogger(__name__)

PING_TIMEOUT_SECONDS = 5


def ping():
    """Tell the monitor the worker loop is alive. Never raises."""
    url = os.environ.get("HEALTHCHECK_PING_URL")
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=PING_TIMEOUT_SECONDS).close()
    except Exception as e:
        # Type only: some urllib errors include the URL in their message.
        # A failed ping isn't fatal; enough of them and the monitor alerts, which is correct.
        log_event(logger, "heartbeat_failed", level=logging.WARNING, error_type=type(e).__name__)
