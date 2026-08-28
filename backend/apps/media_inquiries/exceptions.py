class PaidMediaBusinessError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class PaidMediaInputInvalid(PaidMediaBusinessError):
    def __init__(
        self,
        code: str = "PAID_MEDIA_INPUT_INVALID",
        message: str = "媒体服务申请参数不正确。",
    ) -> None:
        super().__init__(code, message, status=422)


class PaidMediaCatalogUnavailable(PaidMediaBusinessError):
    def __init__(self) -> None:
        super().__init__(
            "PAID_MEDIA_CATALOG_UNAVAILABLE",
            "媒体服务目录暂时不可用，请稍后重试。",
            status=503,
        )


class PaidMediaVersionConflict(PaidMediaBusinessError):
    def __init__(self) -> None:
        super().__init__(
            "PAID_MEDIA_VERSION_CONFLICT",
            "申请记录已发生变化，请刷新后重试。",
            status=409,
        )


class PaidMediaStateConflict(PaidMediaBusinessError):
    def __init__(self, message: str = "当前申请状态不允许执行此操作。") -> None:
        super().__init__("PAID_MEDIA_STATE_CONFLICT", message, status=409)
