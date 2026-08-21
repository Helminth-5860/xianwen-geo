class ImageBusinessError(Exception):
    code = "IMAGE_STATE_CONFLICT"
    status = 409

    def __init__(self, code: str | None = None, *, status: int | None = None):
        self.code = code or self.code
        self.status = status or self.status
        super().__init__(self.code)


class ImageInputInvalid(ImageBusinessError):
    code = "IMAGE_INPUT_INVALID"
    status = 422


class ImageRuntimeUnavailable(ImageBusinessError):
    code = "IMAGE_RUNTIME_UNAVAILABLE"
    status = 503


class ImageCredentialUnavailable(ImageBusinessError):
    code = "IMAGE_CREDENTIAL_UNAVAILABLE"
    status = 503


class ImageStorageUnavailable(ImageBusinessError):
    code = "IMAGE_STORAGE_UNAVAILABLE"
    status = 503
