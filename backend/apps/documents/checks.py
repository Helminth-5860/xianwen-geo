from django.conf import settings
from django.core.checks import Error, register


@register()
def document_checks(app_configs, **kwargs):
    errors = []
    if len(getattr(settings, "FILE_IDEMPOTENCY_HMAC_KEY", "")) < 32:
        errors.append(Error("The file idempotency HMAC key is too weak.", id="documents.E001"))
    if settings.FILE_UPLOAD_MAX_BYTES <= 0:
        errors.append(Error("The file upload limit must be positive.", id="documents.E002"))
    if settings.FILE_STORAGE_PROVIDER not in {"s3", "mock", "unavailable"}:
        errors.append(Error("The configured file provider is invalid.", id="documents.E003"))
    if settings.FILE_SCANNER_PROVIDER not in {"mock", "unavailable"}:
        errors.append(Error("The configured file provider is invalid.", id="documents.E004"))
    return errors
