from uuid import UUID, uuid4

MAX_REQUEST_ID_LENGTH = 36


def validate_request_id(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > MAX_REQUEST_ID_LENGTH:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return None
    if str(parsed) != value.lower():
        return None
    return value


def new_request_id() -> str:
    return str(uuid4())


def request_id_or_new(value: object = None) -> str:
    return validate_request_id(value) or new_request_id()
