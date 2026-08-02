from django.conf import settings
from django.core.checks import Error, register

from .catalog import QUOTA_BY_KEY, QUOTA_CATALOG


@register()
def quota_checks(app_configs, **kwargs):
    errors = []
    if len(QUOTA_BY_KEY) != len(QUOTA_CATALOG):
        errors.append(Error("额度目录 key 必须唯一。", id="quotas.E001"))
    key = getattr(settings, "QUOTA_IDEMPOTENCY_HMAC_KEY", "")
    if len(key) < 32:
        errors.append(Error("额度幂等 HMAC Key 长度不足。", id="quotas.E002"))
    return errors
