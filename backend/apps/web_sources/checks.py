from django.conf import settings
from django.core.checks import Error, register


@register()
def web_source_checks(app_configs, **kwargs):
    errors = []
    if len(getattr(settings, "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY", "")) < 32:
        errors.append(Error("The web import HMAC key is too weak.", id="web_sources.E001"))
    if settings.WEB_IMPORT_MAX_RESPONSE_BYTES <= 0:
        errors.append(
            Error("The web import response limit must be positive.", id="web_sources.E002")
        )
    if settings.WEB_IMPORT_MAX_REDIRECTS < 0 or settings.WEB_IMPORT_MAX_REDIRECTS > 10:
        errors.append(Error("The web import redirect limit is invalid.", id="web_sources.E003"))
    if settings.WEB_IMPORT_ENABLED and not settings.WEB_IMPORT_NETWORK_POLICY_ENFORCED:
        errors.append(
            Error(
                "Enabled web import requires an enforced egress network policy.",
                id="web_sources.E004",
            )
        )
    return errors
