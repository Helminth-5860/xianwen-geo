class DistillationError(Exception):
    code = "DISTILLATION_STATE_CONFLICT"


class DistillationInProgress(DistillationError):
    code = "DISTILLATION_IN_PROGRESS"


class DistillationRegenerationConfirmationRequired(DistillationError):
    code = "DISTILLATION_REGENERATION_CONFIRMATION_REQUIRED"


class DistillationVersionConflict(DistillationError):
    code = "DISTILLATION_VERSION_CONFLICT"


class DistillationKeywordVersionConflict(DistillationError):
    code = "DISTILLATION_KEYWORD_VERSION_CONFLICT"


class DistillationValuesInvalid(DistillationError):
    code = "DISTILLATION_VALUES_INVALID"


class DistillationVersionNoChanges(DistillationError):
    code = "DISTILLATION_VERSION_NO_CHANGES"


class DistillationIdempotencyRequired(DistillationError):
    code = "DISTILLATION_IDEMPOTENCY_KEY_REQUIRED"


class DistillationIdempotencyConflict(DistillationError):
    code = "IDEMPOTENCY_CONFLICT"


class DistillationProviderUnavailable(DistillationError):
    code = "DISTILLATION_PROVIDER_UNAVAILABLE"
    permanent = True


class DistillationInvalidResponse(DistillationError):
    code = "DISTILLATION_INVALID_RESPONSE"
    permanent = True


class DistillationProviderError(DistillationError):
    def __init__(self, code: str, *, permanent: bool):
        self.code = code
        self.permanent = permanent
        super().__init__(code)


class DistillationUnexpectedError(Exception):
    def __init__(self, *, job_id, generation):
        self.job_id = job_id
        self.generation = generation
        super().__init__("Unexpected distillation worker error.")
