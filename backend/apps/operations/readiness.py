from __future__ import annotations

from dataclasses import asdict, dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.ai.models import (
    AICapabilityRuntimeConfig,
    APICredential,
    APICredentialCapabilityBinding,
)

from .models import BackupRecord, ReleaseEvidence


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    status: str
    required: bool
    code: str
    safe_summary: dict


def _check(key: str, ready: bool, code: str, safe_summary=None, *, required=True):
    return ReadinessCheck(
        key=key,
        status="READY" if ready else "NOT_READY",
        required=required,
        code="READY" if ready else code,
        safe_summary=safe_summary or {},
    )


def _database_check() -> ReadinessCheck:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            ready = cursor.fetchone() == (1,)
    except Exception:
        ready = False
    return _check("database", ready, "DATABASE_UNAVAILABLE")


def _cache_check() -> ReadinessCheck:
    try:
        # A readiness read must never mutate a production cache. A successful
        # miss still proves that the configured cache backend is reachable.
        cache.get("release-readiness:connectivity-check:never-written")
        ready = True
    except Exception:
        ready = False
    return _check("redis", ready, "REDIS_UNAVAILABLE")


def _migration_check() -> ReadinessCheck:
    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        ready = not pending
        count = len(pending)
    except Exception:
        ready = False
        count = -1
    return _check(
        "migrations",
        ready,
        "MIGRATIONS_PENDING_OR_UNAVAILABLE",
        {"pending_count": count},
    )


def _storage_check() -> ReadinessCheck:
    provider = settings.FILE_STORAGE_PROVIDER
    required = ("S3_ENDPOINT_URL", "S3_REGION", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
    configured = (
        provider == "s3"
        and settings.FILE_SCANNER_PROVIDER == "clamav"
        and bool(settings.CLAMAV_HOST)
        and all(bool(getattr(settings, name, "")) for name in required)
    )
    return _check(
        "private_storage",
        configured,
        "PRIVATE_STORAGE_NOT_CONFIGURED",
        {
            "provider": provider,
            "scanner": settings.FILE_SCANNER_PROVIDER,
            "private_required": True,
        },
    )


def _sms_check() -> ReadinessCheck:
    required = (
        "SMS_REGION",
        "SMS_APP_ID",
        "SMS_SECRET_ID",
        "SMS_SECRET_KEY",
        "SMS_SIGN_NAME",
        "SMS_TEMPLATE_REGISTER",
        "SMS_TEMPLATE_LOGIN",
        "SMS_TEMPLATE_SECURITY",
    )
    ready = (
        settings.SMS_PROVIDER == "tencent"
        and settings.ENABLE_REAL_SMS
        and all(bool(getattr(settings, name, "")) for name in required)
    )
    return _check(
        "sms",
        ready,
        "TENCENT_SMS_NOT_CONFIGURED",
        {"provider": settings.SMS_PROVIDER, "real_send_enabled": settings.ENABLE_REAL_SMS},
    )


def _credential_check() -> ReadinessCheck:
    environment = settings.API_CREDENTIAL_ENVIRONMENT
    active = APICredential.objects.filter(environment=environment, status="active")
    bound = APICredentialCapabilityBinding.objects.filter(environment=environment, enabled=True)
    ready = active.exists() and bound.exists()
    return _check(
        "provider_credentials",
        ready,
        "PROVIDER_CREDENTIALS_NOT_BOUND",
        {
            "environment": environment,
            "active_provider_count": active.values("provider_id").distinct().count(),
            "enabled_binding_count": bound.count(),
        },
    )


def _runtime_check() -> ReadinessCheck:
    enabled = AICapabilityRuntimeConfig.objects.filter(enabled=True, paused=False).exclude(
        provider_model_id=""
    )
    capabilities = sorted(enabled.values_list("capability", flat=True).distinct())
    required_capabilities = {"text_generation", "image_generation"}
    ready = required_capabilities.issubset(set(capabilities))
    return _check(
        "capability_runtime",
        ready,
        "CAPABILITY_RUNTIME_NOT_READY",
        {
            "enabled_capabilities": capabilities,
            "required_capabilities": sorted(required_capabilities),
        },
    )


def _worker_check() -> ReadinessCheck:
    expected = tuple(settings.RELEASE_EXPECTED_WORKER_QUEUES)
    observed = []
    try:
        for queue in expected:
            if cache.get(f"worker-heartbeat:{queue}"):
                observed.append(queue)
    except Exception:
        observed = []
    ready = set(observed) == set(expected)
    return _check(
        "workers",
        ready,
        "WORKER_HEARTBEATS_MISSING",
        {"expected_queues": list(expected), "observed_queues": observed},
    )


def _backup_check() -> ReadinessCheck:
    latest = BackupRecord.objects.filter(
        status=BackupRecord.Status.VERIFIED,
        encrypted=True,
        restore_verified_at__isnull=False,
    ).first()
    return _check(
        "backup_recovery",
        latest is not None,
        "VERIFIED_BACKUP_RESTORE_MISSING",
        {"latest_verified_at": latest.restore_verified_at if latest else None},
    )


def _external_evidence_check() -> ReadinessCheck:
    expected = tuple(settings.RELEASE_EXPECTED_EXTERNAL_EVIDENCE)
    deploy_sha = getattr(settings, "RELEASE_DEPLOY_SHA", "")
    sha_valid = len(deploy_sha) == 40 and all(
        character in "0123456789abcdef" for character in deploy_sha
    )
    observed: list[str] = []
    if sha_valid:
        observed = sorted(
            set(
                ReleaseEvidence.objects.filter(
                    environment=settings.API_CREDENTIAL_ENVIRONMENT,
                    evidence_key__in=expected,
                    deploy_sha=deploy_sha,
                    expires_at__gt=timezone.now(),
                ).values_list("evidence_key", flat=True)
            )
        )
    ready = sha_valid and set(observed) == set(expected)
    return _check(
        "external_gate_evidence",
        ready,
        "EXTERNAL_GATE_EVIDENCE_MISSING",
        {
            "environment": settings.API_CREDENTIAL_ENVIRONMENT,
            "deploy_sha_configured": sha_valid,
            "expected_keys": list(expected),
            "observed_keys": observed,
        },
    )


def release_readiness_report() -> dict:
    checks = (
        _database_check(),
        _cache_check(),
        _migration_check(),
        _storage_check(),
        _sms_check(),
        _credential_check(),
        _runtime_check(),
        _worker_check(),
        _backup_check(),
        _external_evidence_check(),
    )
    ready = all(item.status == "READY" for item in checks if item.required)
    return {
        "status": "READY" if ready else "NOT_READY",
        "generated_at": timezone.now(),
        "environment": settings.APP_ENV,
        "checks": [asdict(item) for item in checks],
        "secrets_included": False,
    }
