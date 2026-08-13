from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_file_postgres_redis_minio_suite_is_required_by_docker_job():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["docker"]["steps"]
    assert any(
        step.get("name") == "Run PostgreSQL/Redis/MinIO file Saga tests"
        and step.get("run") == "bash scripts/test-files.sh"
        for step in steps
    )
    shell_script = (REPO_ROOT / "scripts/test-files.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts/test-files.ps1").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker-compose.files.yml").read_text(encoding="utf-8")
    for content in (shell_script, powershell_script):
        assert "xianwen-file-test" in content
        assert "down --volumes --remove-orphans" in content
        assert 'APP_ENV="local"' in content or '$env:APP_ENV = "local"' in content
        assert "FILE_PROCESSING_DATABASE_URL" in content
    assert "tests/test_documents_postgres.py" in compose
    assert "tests/test_documents_saga_postgres.py" in compose
    assert "MINIO_API_CORS_ALLOW_ORIGIN: http://localhost:3000" in compose
    assert "minio-init" in compose
    assert "service_completed_successfully" in compose
    assert "FILE_STORAGE_PROVIDER: s3" in compose
    assert "tests/test_document_parsing_postgres.py" in compose
    assert "--queues=file_processing" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop: [ALL]" in compose
    assert "file_processing_internal: {internal: true}" in compose
    assert "DOCUMENT_OCR_PROVIDER: mock" in compose
    assert "file-processing-worker" in compose
    assert "DATABASE_URL: ${FILE_PROCESSING_DATABASE_URL:-${DATABASE_URL}}" in compose


def test_file_suite_uses_no_production_credentials_or_cloud_endpoints():
    content = "\n".join(
        (REPO_ROOT / name).read_text(encoding="utf-8")
        for name in ("scripts/test-files.sh", "scripts/test-files.ps1", "docker-compose.files.yml")
    )
    assert "tencent" not in content.casefold()
    assert "cos." not in content.casefold()
    assert "force" + " push" not in content.casefold()
