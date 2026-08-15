class KeywordGenerationError(Exception):
    code = "KEYWORD_GENERATION_STATE_CONFLICT"
    permanent = True


class KeywordGenerationStateConflict(KeywordGenerationError):
    pass


class KeywordGenerationInProgress(KeywordGenerationError):
    code = "KEYWORD_GENERATION_IN_PROGRESS"


class KeywordGenerationRegenerationConfirmationRequired(KeywordGenerationError):
    code = "KEYWORD_REGENERATION_CONFIRMATION_REQUIRED"


class KeywordGenerationVersionConflict(KeywordGenerationError):
    code = "KEYWORD_VERSION_CONFLICT"


class KeywordGenerationSubjectVersionConflict(KeywordGenerationError):
    code = "KEYWORD_SUBJECT_VERSION_CONFLICT"


class KeywordGenerationLimitExceeded(KeywordGenerationError):
    code = "KEYWORD_GENERATION_LIMIT_EXCEEDED"


class KeywordGenerationConfigInvalid(KeywordGenerationError):
    code = "KEYWORD_GENERATION_CONFIG_INVALID"


class KeywordGenerationIdempotencyRequired(KeywordGenerationError):
    code = "KEYWORD_GENERATION_IDEMPOTENCY_KEY_REQUIRED"


class KeywordGenerationIdempotencyConflict(KeywordGenerationError):
    code = "IDEMPOTENCY_CONFLICT"


class KeywordGenerationProviderUnavailable(KeywordGenerationError):
    code = "KEYWORD_GENERATION_PROVIDER_UNAVAILABLE"
    permanent = False


class KeywordGenerationInvalidResponse(KeywordGenerationError):
    code = "KEYWORD_GENERATION_INVALID_RESPONSE"


class KeywordGenerationProviderError(KeywordGenerationError):
    def __init__(self, code: str, *, permanent: bool):
        self.code = code
        self.permanent = permanent
        super().__init__(code)


class KeywordGenerationUnexpectedError(Exception):
    def __init__(self, *, job_id, generation):
        self.job_id = job_id
        self.generation = generation
        super().__init__(str(job_id))
