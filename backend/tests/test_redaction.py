import io
import json
import logging

from apps.core.context import request_id_context
from apps.core.logging import JsonFormatter, RequestContextFilter
from apps.core.redaction import REDACTED, redact_sensitive_data


def test_nested_sensitive_values_are_redacted_without_changing_business_code():
    value = {
        "Authorization": "Bearer private",
        "profile": {
            "Password_Confirm": "secret-password",
            "error": {"code": "VALIDATION_ERROR"},
        },
        "items": [
            {"api_key": "provider-key"},
            ({"SMS-Code": "123456"}, {"normal": "visible"}),
        ],
    }

    redacted = redact_sensitive_data(value)

    assert redacted["Authorization"] == REDACTED
    assert redacted["profile"]["Password_Confirm"] == REDACTED
    assert redacted["profile"]["error"]["code"] == "VALIDATION_ERROR"
    assert redacted["items"][0]["api_key"] == REDACTED
    assert redacted["items"][1][0]["SMS-Code"] == REDACTED
    assert redacted["items"][1][1]["normal"] == "visible"


def test_structured_log_filter_removes_password_token_and_sms_code():
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("tests.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    with request_id_context("24c5291c-9172-49e5-a970-d3a41426dff3"):
        logger.info(
            "安全日志",
            extra={
                "context": {
                    "password": "test-password-value",
                    "access_token": "test-token-value",
                    "sms_code": "928314",
                    "error": {"code": "VALIDATION_ERROR"},
                }
            },
        )

    log_line = output.getvalue()
    payload = json.loads(log_line)
    assert "test-password-value" not in log_line
    assert "test-token-value" not in log_line
    assert "928314" not in log_line
    assert payload["context"]["password"] == REDACTED
    assert payload["context"]["access_token"] == REDACTED
    assert payload["context"]["sms_code"] == REDACTED
    assert payload["context"]["error"]["code"] == "VALIDATION_ERROR"
