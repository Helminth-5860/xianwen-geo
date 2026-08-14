class SubjectEnrichmentError(Exception):
    code = "SUBJECT_ENRICHMENT_STATE_CONFLICT"
    permanent = True


class SubjectEnrichmentStateConflict(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_STATE_CONFLICT"


class SubjectEnrichmentVersionConflict(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_VERSION_CONFLICT"


class SubjectEnrichmentIdempotencyRequired(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_IDEMPOTENCY_KEY_REQUIRED"


class SubjectEnrichmentIdempotencyConflict(SubjectEnrichmentError):
    code = "IDEMPOTENCY_CONFLICT"


class SubjectEnrichmentSourceInvalid(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_SOURCE_INVALID"


class SubjectEnrichmentTargetInvalid(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_TARGET_INVALID"


class SubjectEnrichmentInputTooLarge(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_INPUT_TOO_LARGE"


class SubjectEnrichmentProviderUnavailable(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_PROVIDER_UNAVAILABLE"
    permanent = False


class SubjectEnrichmentRateLimited(SubjectEnrichmentError):
    code = "RATE_LIMITED"
    permanent = False


class SubjectEnrichmentTemporarilyUnavailable(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_TEMPORARILY_UNAVAILABLE"
    permanent = False


class SubjectEnrichmentInvalidResponse(SubjectEnrichmentError):
    code = "SUBJECT_ENRICHMENT_INVALID_RESPONSE"


class SubjectEnrichmentProviderError(SubjectEnrichmentError):
    def __init__(self, code: str, *, permanent: bool):
        self.code = code
        self.permanent = permanent
        super().__init__(code)


class SubjectEnrichmentUnexpectedError(Exception):
    def __init__(self, *, job_id, generation):
        self.job_id = job_id
        self.generation = generation
        super().__init__(str(job_id))
