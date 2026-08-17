class AIModelConfigError(Exception):
    code = "AI_MODEL_CONFIG_INVALID"


class AIModelConfigVersionConflict(AIModelConfigError):
    code = "AI_MODEL_CONFIG_VERSION_CONFLICT"


class AIModelConfigStateConflict(AIModelConfigError):
    code = "AI_MODEL_CONFIG_STATE_CONFLICT"


class AIModelConfigValuesInvalid(AIModelConfigError):
    code = "AI_MODEL_CONFIG_INVALID"
