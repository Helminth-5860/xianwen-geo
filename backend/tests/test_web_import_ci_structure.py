from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docker_job_runs_isolated_web_import_worker_suite():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["docker"]["steps"]
    assert any(step.get("run") == "bash scripts/test-web-import.sh" for step in steps)
    shell = (REPO_ROOT / "scripts/test-web-import.sh").read_text(encoding="utf-8")
    powershell = (REPO_ROOT / "scripts/test-web-import.ps1").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker-compose.web-import.yml").read_text(encoding="utf-8")
    for content in (shell, powershell):
        assert "xianwen-web-import-test" in content
        assert "--volumes" in content
        assert "--remove-orphans" in content
        assert "--abort-on-container-exit" not in content
        assert "--exit-code-from" not in content
        assert "web-import-migrate" in content
        assert "web-import-tests" in content
        assert content.index("web-import-migrate") < content.rindex("web-import-tests")
    assert "up -d --wait --wait-timeout 60 postgres redis web-lab" in shell
    assert "up -d --wait --wait-timeout 60 postgres redis web-lab" in powershell
    assert "run --rm web-import-migrate" in shell
    assert "run --rm --no-deps web-import-tests" in shell
    assert "run --rm web-import-migrate" in powershell
    assert "run --rm --no-deps web-import-tests" in powershell
    assert "trap cleanup EXIT" in shell
    assert "finally {" in powershell
    assert 'Assert-LastExitCode "Web import migrations failed."' in powershell
    assert 'Assert-LastExitCode "PostgreSQL/Redis/web_fetch worker tests failed."' in powershell
    assert "internal: true" in compose
    assert "--queues=web_fetch" in compose
    assert "--reuse-db" in compose
    assert "tests/test_web_sources_postgres.py" in compose
    assert '"-q"' not in compose.split("web-import-tests:", 1)[1]
    assert 'command: ["python", "/site/server.py"]' in compose
    assert 'WEB_IMPORT_TOTAL_TIMEOUT_SECONDS: "2"' in compose


def test_web_fetch_has_no_production_mock_or_public_proxy_escape():
    production = (REPO_ROOT / "backend/config/django_settings/production.py").read_text(
        encoding="utf-8"
    )
    transport = (REPO_ROOT / "backend/apps/web_sources/http_transport.py").read_text(
        encoding="utf-8"
    )
    assert 'WEB_IMPORT_ENABLED", False' in production
    assert "WEB_IMPORT_TEST_ALLOWED_CIDRS = ()" in production
    assert "urllib.request" not in transport
    assert "requests" not in transport
    assert "proxy" not in transport.lower()
    assert "class _DeadlineRawIO" in transport
    assert "recv_into" in transport
    assert "_remaining_timeout" in transport


def test_all_compose_test_scripts_supply_web_import_hmac_key():
    test_scripts = sorted((REPO_ROOT / "scripts").glob("test-*.ps1")) + sorted(
        (REPO_ROOT / "scripts").glob("test-*.sh")
    )
    assert test_scripts
    missing = [
        path.name
        for path in test_scripts
        if "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY" not in path.read_text(encoding="utf-8")
    ]
    assert missing == []


def test_production_and_test_web_fetch_workers_are_isolated_and_bounded():
    for filename in ("docker-compose.yml", "docker-compose.web-import.yml"):
        compose = (REPO_ROOT / filename).read_text(encoding="utf-8")
        expected_service = (
            "web-fetch-worker:" if filename == "docker-compose.yml" else "web-fetch-test-worker:"
        )
        assert expected_service in compose
        assert "--queues=web_fetch" in compose
        assert "--concurrency=1" in compose
        assert "--prefetch-multiplier=1" in compose
        assert "--time-limit=45" in compose
        assert "privileged: false" in compose
        assert "read_only: true" in compose
        assert "/tmp:rw,noexec,nosuid,nodev,size=64m" in compose
        assert "cap_drop: [ALL]" in compose
        assert 'security_opt: ["no-new-privileges:true"]' in compose
        assert "pids_limit: 128" in compose
