class QuestionCatalogError(Exception):
    code = "QUESTION_CATALOG_STATE_CONFLICT"


class QuestionCatalogVersionConflict(QuestionCatalogError):
    code = "QUESTION_CATALOG_VERSION_CONFLICT"


class QuestionCatalogDuplicate(QuestionCatalogError):
    code = "QUESTION_CATALOG_DUPLICATE"


class QuestionCatalogValuesInvalid(QuestionCatalogError):
    code = "QUESTION_CATALOG_VALUES_INVALID"


class QuestionCatalogStateConflict(QuestionCatalogError):
    code = "QUESTION_CATALOG_STATE_CONFLICT"
