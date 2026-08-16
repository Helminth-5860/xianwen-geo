class QuestionBankError(Exception):
    code = "QUESTION_BANK_VALUES_INVALID"
    permanent = True


class QuestionBankValuesInvalid(QuestionBankError):
    code = "QUESTION_BANK_VALUES_INVALID"


class QuestionBankVersionConflict(QuestionBankError):
    code = "QUESTION_BANK_VERSION_CONFLICT"


class QuestionBankInputConflict(QuestionBankError):
    code = "QUESTION_BANK_INPUT_CONFLICT"


class QuestionBankVersionNoChanges(QuestionBankError):
    code = "QUESTION_BANK_VERSION_NO_CHANGES"


class QuestionGenerationInProgress(QuestionBankError):
    code = "QUESTION_GENERATION_IN_PROGRESS"


class QuestionGenerationIdempotencyConflict(QuestionBankError):
    code = "QUESTION_GENERATION_IDEMPOTENCY_CONFLICT"


class QuestionGenerationRegenerationConfirmationRequired(QuestionBankError):
    code = "QUESTION_GENERATION_REGENERATION_CONFIRMATION_REQUIRED"


class QuestionGenerationInvalidResponse(QuestionBankError):
    code = "QUESTION_GENERATION_INVALID_RESPONSE"


class QuestionGenerationProviderUnavailable(QuestionBankError):
    code = "QUESTION_GENERATION_PROVIDER_UNAVAILABLE"


class QuestionGenerationProviderError(QuestionBankError):
    def __init__(self, code, *, permanent):
        super().__init__(code)
        self.code = code
        self.permanent = permanent


class QuestionGenerationUnexpectedError(Exception):
    def __init__(self, *, job_id, generation):
        super().__init__("Unexpected question generation error")
        self.job_id = job_id
        self.generation = generation
