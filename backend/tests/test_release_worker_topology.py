import re
from pathlib import Path

import yaml
from django.conf import settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _compose_worker_queues() -> tuple[set[str], dict[str, dict]]:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    queues: set[str] = set()
    for service in services.values():
        for argument in service.get("command", ()):  # Commands are frozen as argv lists.
            if isinstance(argument, str) and argument.startswith("--queues="):
                queues.update(argument.removeprefix("--queues=").split(","))
    return queues, services


def _literal_application_queues() -> set[str]:
    pattern = re.compile(r"queue\s*=\s*['\"]([a-z0-9_]+)['\"]")
    queues: set[str] = set()
    for source in (REPO_ROOT / "backend" / "apps").rglob("*.py"):
        queues.update(pattern.findall(source.read_text(encoding="utf-8")))
    return queues


def test_every_production_queue_has_a_canonical_compose_consumer():
    configured_routes = {
        settings.CELERY_TASK_DEFAULT_QUEUE,
        *(route["queue"] for route in settings.CELERY_TASK_ROUTES.values()),
    }
    production_queues = configured_routes | _literal_application_queues()
    consumer_queues, _ = _compose_worker_queues()

    assert production_queues == {
        "system_tasks",
        "ai_content",
        "geo_detection",
        "image_generation",
        "file_processing",
        "web_fetch",
    }
    assert set(settings.CELERY_PRODUCTION_QUEUES) == production_queues
    assert set(settings.RELEASE_EXPECTED_WORKER_QUEUES) == production_queues
    assert production_queues <= consumer_queues
    assert "geo_scoring" not in production_queues | consumer_queues


def test_file_processing_worker_is_dedicated_hardened_and_unpublished():
    _, services = _compose_worker_queues()
    worker = services["file-processing-worker"]

    assert worker["extends"] == {"service": "celery"}
    assert "--queues=file_processing" in worker["command"]
    assert worker["restart"] == "unless-stopped"
    assert worker["user"] == "app"
    assert worker["read_only"] is True
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in worker
    assert {
        "FILE_IDEMPOTENCY_HMAC_KEY",
        "FILE_STORAGE_PROVIDER",
        "FILE_SCANNER_PROVIDER",
        "FILE_ALLOWED_APP_ORIGINS",
        "S3_ENDPOINT_URL",
        "S3_REGION",
        "S3_BUCKET",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "CLAMAV_HOST",
    } <= set(worker["environment"])


def test_file_saga_overlay_does_not_duplicate_worker_security_options():
    base = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load((REPO_ROOT / "docker-compose.files.yml").read_text(encoding="utf-8"))
    base_options = set(base["services"]["file-processing-worker"].get("security_opt", ()))
    overlay_options = set(overlay["services"]["file-processing-worker"].get("security_opt", ()))

    assert base_options == {"no-new-privileges:true"}
    assert base_options.isdisjoint(overlay_options)
