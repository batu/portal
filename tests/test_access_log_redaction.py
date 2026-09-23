"""Operator tokens passed as ?token= must not reach uvicorn's access log."""
import logging

from gallery import server


def _access_record(path: str) -> logging.LogRecord:
    # Same shape uvicorn's httptools/h11 protocols log with.
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 200), None,
    )


def test_access_log_redacts_token_query_param():
    record = _access_record("/r/abc?view=1&token=s3cret-token&x=2")
    logger = logging.getLogger("uvicorn.access")
    assert all(f.filter(record) for f in logger.filters)
    message = record.getMessage()
    assert "s3cret-token" not in message
    assert "/r/abc?view=1&token=REDACTED&x=2" in message


def test_access_log_redaction_leaves_other_paths_alone():
    record = _access_record("/games?tokenish=1&q=token")
    for f in logging.getLogger("uvicorn.access").filters:
        f.filter(record)
    assert "/games?tokenish=1&q=token" in record.getMessage()


def test_redact_token_query_handles_first_param():
    assert server.redact_token_query("/login?token=abc") == "/login?token=REDACTED"
