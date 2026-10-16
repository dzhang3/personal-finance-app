import logging

from app.logging_utils import ContextFilter, LogfmtFormatter, job_context, log_event


def render(event, level=logging.INFO, **fields):
    """Run one event through the real filter + formatter and return the line."""
    lines = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    handler = Capture()
    handler.addFilter(ContextFilter())
    handler.setFormatter(LogfmtFormatter())
    logger = logging.getLogger("app.test_logging")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        log_event(logger, event, level=level, **fields)
    finally:
        logger.removeHandler(handler)
    return lines[0]


def test_context_fields_appear_on_every_line_inside_the_block():
    with job_context(job_id=7, attempt=2):
        line = render("page_upserted", added=100)
    assert "job_id=7 attempt=2 event=page_upserted added=100" in line


def test_context_is_gone_after_the_block():
    with job_context(job_id=7):
        pass
    assert "job_id" not in render("worker_idle")


def test_nested_context_adds_and_then_restores():
    with job_context(worker="w1"):
        with job_context(job_id=7):
            inner = render("inner")
        outer = render("outer")
    assert "worker=w1 job_id=7" in inner
    assert "worker=w1" in outer and "job_id" not in outer


def test_secrets_are_redacted_whatever_the_caller_passes():
    line = render("oops", access_token="access-sandbox-abc", plaid_secret="s3cr3t")
    assert "access-sandbox-abc" not in line and "s3cr3t" not in line
    assert "access_token=[redacted]" in line


def test_values_with_spaces_or_quotes_are_quoted():
    line = render("job_failed", error='Rate limit "exceeded"', code=None)
    assert 'error="Rate limit \\"exceeded\\""' in line
    assert "code=null" in line
