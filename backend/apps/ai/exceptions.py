class AIModelConfigError(Exception):
    code = "AI_MODEL_CONFIG_INVALID"


class AIModelConfigVersionConflict(AIModelConfigError):
    code = "AI_MODEL_CONFIG_VERSION_CONFLICT"


class AIModelConfigStateConflict(AIModelConfigError):
    code = "AI_MODEL_CONFIG_STATE_CONFLICT"


class AIModelConfigValuesInvalid(AIModelConfigError):
    code = "AI_MODEL_CONFIG_INVALID"


class AICredentialError(Exception):
    code = "AI_CREDENTIAL_INVALID"


class AICredentialInvalid(AICredentialError):
    code = "AI_CREDENTIAL_INVALID"


class AICredentialAlreadyExists(AICredentialError):
    code = "AI_CREDENTIAL_ALREADY_EXISTS"


class AICredentialVersionConflict(AICredentialError):
    code = "AI_CREDENTIAL_VERSION_CONFLICT"


class AICredentialStateConflict(AICredentialError):
    code = "AI_CREDENTIAL_STATE_CONFLICT"


class AICredentialCryptoFailure(AICredentialError):
    code = "AI_CREDENTIAL_CRYPTO_FAILURE"
