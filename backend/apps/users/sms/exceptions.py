class SmsVerificationError(Exception):
    """Base class for safe, non-sensitive SMS verification failures."""


class SmsServiceUnavailable(SmsVerificationError):
    pass


class SmsRateLimited(SmsVerificationError):
    pass
