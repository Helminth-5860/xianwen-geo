class KeywordError(Exception):
    code = "KEYWORD_STATE_CONFLICT"


class KeywordStateConflict(KeywordError):
    pass


class KeywordVersionConflict(KeywordError):
    code = "KEYWORD_VERSION_CONFLICT"


class KeywordSubjectVersionConflict(KeywordError):
    code = "KEYWORD_SUBJECT_VERSION_CONFLICT"


class KeywordValuesInvalid(KeywordError):
    code = "KEYWORD_VALUES_INVALID"


class KeywordVersionNoChanges(KeywordError):
    code = "KEYWORD_VERSION_NO_CHANGES"


class KeywordPlanRequired(KeywordError):
    code = "PLAN_REQUIRED"


class KeywordAccountUnavailable(KeywordError):
    code = "ACCOUNT_UNAVAILABLE"
