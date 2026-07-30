from pathlib import Path

import yaml


def test_compose_keeps_backend_and_frontend_environments_independent():
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    services = compose["services"]
    api_environment = services["api"]["environment"]
    celery_environment = services["celery"]["environment"]
    frontend = services["frontend"]

    assert api_environment["SECURE_SSL_REDIRECT"] == "${SECURE_SSL_REDIRECT:-false}"
    assert celery_environment["SECURE_SSL_REDIRECT"] == "${SECURE_SSL_REDIRECT:-false}"
    assert "CSRF_TRUSTED_ORIGINS" in celery_environment
    assert "CORS_ALLOWED_ORIGINS" in celery_environment
    assert frontend["build"]["args"]["NEXT_PUBLIC_APP_ENV"] == "${NEXT_PUBLIC_APP_ENV:-local}"
    assert frontend["environment"]["NEXT_PUBLIC_APP_ENV"] == "${NEXT_PUBLIC_APP_ENV:-local}"


def test_backend_image_normalizes_shell_scripts_and_has_writable_home():
    dockerfile_path = Path(__file__).resolve().parents[1] / "Dockerfile"
    dockerfile = dockerfile_path.read_text(encoding="utf-8")

    assert "HOME=/home/app" in dockerfile
    assert "--home /home/app" in dockerfile
    assert "sed -i 's/\\r$//'" in dockerfile
