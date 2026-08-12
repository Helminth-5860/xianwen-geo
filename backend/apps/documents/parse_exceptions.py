class DocumentParseError(Exception):
    code = "DOCUMENT_PARSE_STATE_CONFLICT"
    permanent = True


class DocumentParseIdempotencyRequired(DocumentParseError):
    code = "DOCUMENT_PARSE_IDEMPOTENCY_KEY_REQUIRED"


class DocumentParseIdempotencyConflict(DocumentParseError):
    code = "IDEMPOTENCY_CONFLICT"


class DocumentParseStateConflict(DocumentParseError):
    code = "DOCUMENT_PARSE_STATE_CONFLICT"


class DocumentParseVersionConflict(DocumentParseError):
    code = "DOCUMENT_PARSE_VERSION_CONFLICT"


class DocumentParseContentInvalid(DocumentParseError):
    code = "DOCUMENT_PARSE_CONTENT_INVALID"


class DocumentParseSecurityRejected(DocumentParseError):
    code = "DOCUMENT_PARSE_SECURITY_REJECTED"


class DocumentOcrUnavailable(DocumentParseError):
    code = "DOCUMENT_OCR_UNAVAILABLE"
    permanent = False


class DocumentParseInfrastructureUnavailable(DocumentParseError):
    code = "DOCUMENT_PARSE_TEMPORARILY_UNAVAILABLE"
    permanent = False
