class GeoDetectionError(Exception):
    code = "GEO_DETECTION_STATE_CONFLICT"


class GeoDetectionValuesInvalid(GeoDetectionError):
    code = "GEO_DETECTION_VALUES_INVALID"


class GeoDetectionInputConflict(GeoDetectionError):
    code = "GEO_DETECTION_INPUT_CONFLICT"


class GeoDetectionIdempotencyConflict(GeoDetectionError):
    code = "GEO_DETECTION_IDEMPOTENCY_CONFLICT"


class GeoDetectionConcurrencyLimit(GeoDetectionError):
    code = "GEO_DETECTION_CONCURRENCY_LIMIT"


class GeoDetectionStateConflict(GeoDetectionError):
    code = "GEO_DETECTION_STATE_CONFLICT"


class GeoDetectionProviderUnavailable(GeoDetectionError):
    code = "GEO_DETECTION_PROVIDER_UNAVAILABLE"
