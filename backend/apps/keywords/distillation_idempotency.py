import hashlib
import hmac

from django.conf import settings

from .distillation_exceptions import DistillationIdempotencyRequired
from .generation_idempotency import canonical_digest


def derive_distillation_idempotency(*, user_id, subject_id, raw_key: str) -> str:
    if not isinstance(raw_key, str) or not 16 <= len(raw_key.encode()) <= 128:
        raise DistillationIdempotencyRequired
    master = settings.DISTILLATION_IDEMPOTENCY_HMAC_KEY.encode()
    subkey = hmac.new(master, b"keyword-distillation:idempotency:v1", hashlib.sha256).digest()
    scope = f"user={user_id}|subject={subject_id}|key={raw_key}"
    return hmac.new(subkey, scope.encode(), hashlib.sha256).hexdigest()


__all__ = ["canonical_digest", "derive_distillation_idempotency"]
