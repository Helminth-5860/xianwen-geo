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


class StrategyError(Exception):
    code = "STRATEGY_STATE_CONFLICT"


class StrategyValuesInvalid(StrategyError):
    code = "STRATEGY_VALUES_INVALID"


class StrategyInProgress(StrategyError):
    code = "STRATEGY_IN_PROGRESS"


class StrategyRegenerationConfirmationRequired(StrategyError):
    code = "STRATEGY_REGENERATION_CONFIRMATION_REQUIRED"


class StrategyIdempotencyConflict(StrategyError):
    code = "STRATEGY_IDEMPOTENCY_CONFLICT"


class StrategyProviderUnavailable(StrategyError):
    code = "STRATEGY_PROVIDER_UNAVAILABLE"


class StrategyInvalidResponse(StrategyError):
    code = "STRATEGY_INVALID_RESPONSE"


class StrategyNoteVersionConflict(StrategyError):
    code = "STRATEGY_NOTE_VERSION_CONFLICT"


class AssistantError(Exception):
    code = "ASSISTANT_STATE_CONFLICT"


class AssistantValuesInvalid(AssistantError):
    code = "ASSISTANT_VALUES_INVALID"


class AssistantScopeRefused(AssistantError):
    code = "ASSISTANT_SCOPE_REFUSED"


class AssistantSecurityRefused(AssistantError):
    code = "ASSISTANT_SECURITY_REFUSED"


class AssistantIdempotencyConflict(AssistantError):
    code = "ASSISTANT_IDEMPOTENCY_CONFLICT"


class AssistantReplay(AssistantError):
    code = "ASSISTANT_IDEMPOTENCY_REPLAY"


class AssistantProviderUnavailable(AssistantError):
    code = "ASSISTANT_PROVIDER_UNAVAILABLE"


class AssistantInvalidResponse(AssistantError):
    code = "ASSISTANT_INVALID_RESPONSE"
