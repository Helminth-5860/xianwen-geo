class WebSourceError(Exception):
    code = "WEB_SOURCE_STATE_CONFLICT"
    permanent = True

    def __init__(self, *, import_id=None, generation=None):
        self.import_id = import_id
        self.generation = generation
        super().__init__(self.code)


class WebSourceUrlInvalid(WebSourceError):
    code = "WEB_SOURCE_URL_INVALID"


class WebSourceUrlNotAllowed(WebSourceError):
    code = "WEB_SOURCE_URL_NOT_ALLOWED"


class WebSourceContentUnsupported(WebSourceError):
    code = "WEB_SOURCE_CONTENT_UNSUPPORTED"


class WebSourceContentTooLarge(WebSourceError):
    code = "WEB_SOURCE_CONTENT_TOO_LARGE"


class WebSourceStateConflict(WebSourceError):
    code = "WEB_SOURCE_STATE_CONFLICT"


class WebSourceVersionConflict(WebSourceError):
    code = "WEB_SOURCE_VERSION_CONFLICT"


class WebSourceIdempotencyRequired(WebSourceError):
    code = "WEB_SOURCE_IDEMPOTENCY_KEY_REQUIRED"


class WebSourceIdempotencyConflict(WebSourceError):
    code = "IDEMPOTENCY_CONFLICT"


class WebSourceRateLimited(WebSourceError):
    code = "RATE_LIMITED"


class WebSourceUnavailable(WebSourceError):
    code = "WEB_SOURCE_TEMPORARILY_UNAVAILABLE"
    permanent = False


class WebSourceTransientError(WebSourceUnavailable):
    code = "WEB_SOURCE_FETCH_TEMPORARILY_UNAVAILABLE"


class WebSourceUnexpectedError(WebSourceUnavailable):
    code = "WEB_SOURCE_INTERNAL_ERROR"
