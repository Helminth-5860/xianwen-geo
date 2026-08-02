class QuotaError(Exception):
    code = "QUOTA_STATE_CONFLICT"


class QuotaSnapshotInvalid(QuotaError):
    code = "QUOTA_SNAPSHOT_INVALID"


class QuotaInsufficient(QuotaError):
    code = "QUOTA_INSUFFICIENT"


class QuotaStateConflict(QuotaError):
    code = "QUOTA_STATE_CONFLICT"


class QuotaVersionConflict(QuotaError):
    code = "QUOTA_VERSION_CONFLICT"


class QuotaHoldStateConflict(QuotaError):
    code = "QUOTA_HOLD_STATE_CONFLICT"


class QuotaBusinessAlreadyHeld(QuotaError):
    code = "QUOTA_BUSINESS_ALREADY_HELD"


class QuotaIdempotencyRequired(QuotaError):
    code = "IDEMPOTENCY_KEY_REQUIRED"


class QuotaIdempotencyConflict(QuotaError):
    code = "IDEMPOTENCY_CONFLICT"


class QuotaSubscriptionUnavailable(QuotaError):
    code = "PLAN_EXPIRED"
