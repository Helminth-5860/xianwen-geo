class VideoBusinessError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class VideoInputInvalid(VideoBusinessError):
    def __init__(self, code: str = "VIDEO_INPUT_INVALID", message: str = "视频生成参数不正确。"):
        super().__init__(code, message, status=422)


class VideoServiceUnavailable(VideoBusinessError):
    def __init__(
        self,
        code: str = "VIDEO_SERVICE_UNAVAILABLE",
        message: str = "视频生成服务暂时不可用，请稍后重试。",
    ) -> None:
        super().__init__(code, message, status=503)


class VideoVersionConflict(VideoBusinessError):
    def __init__(self) -> None:
        super().__init__(
            "VIDEO_VERSION_CONFLICT",
            "视频记录已发生变化，请刷新后重试。",
            status=409,
        )
