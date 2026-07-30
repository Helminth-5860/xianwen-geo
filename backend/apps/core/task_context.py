from uuid import uuid4

from .context import get_request_id
from .request_ids import validate_request_id


def correlation_headers(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, str]:
    resolved_request_id = validate_request_id(request_id) or get_request_id()
    resolved_correlation_id = validate_request_id(correlation_id)
    if not resolved_correlation_id:
        resolved_correlation_id = resolved_request_id or str(uuid4())

    headers = {"correlation_id": resolved_correlation_id}
    if resolved_request_id:
        headers["request_id"] = resolved_request_id
    return headers
