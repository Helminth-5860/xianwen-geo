class FileBusinessError(Exception):
    code = "FILE_STATE_CONFLICT"


class FileIdempotencyKeyRequired(FileBusinessError):
    code = "FILE_IDEMPOTENCY_KEY_REQUIRED"


class FileIdempotencyConflict(FileBusinessError):
    code = "IDEMPOTENCY_CONFLICT"


class FileStateConflict(FileBusinessError):
    code = "FILE_STATE_CONFLICT"


class FileVersionConflict(FileBusinessError):
    code = "FILE_VERSION_CONFLICT"


class FileTypeNotAllowed(FileBusinessError):
    code = "FILE_TYPE_NOT_ALLOWED"


class FileSizeInvalid(FileBusinessError):
    code = "FILE_SIZE_INVALID"


class FileContentInvalid(FileBusinessError):
    code = "FILE_CONTENT_INVALID"


class FileSecurityRejected(FileBusinessError):
    code = "FILE_SECURITY_REJECTED"


class FileStorageUnavailable(FileBusinessError):
    code = "FILE_STORAGE_UNAVAILABLE"
