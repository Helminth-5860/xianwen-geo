from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_keyword_compose_is_postgresql_only_and_runs_real_pytest():
    compose = yaml.safe_load((ROOT / "docker-compose.keywords.yml").read_text(encoding="utf-8"))
    service = compose["services"]["keyword-tests"]
    assert "postgres" in service["depends_on"]
    assert "redis" not in service["depends_on"]
    command = service["command"]
    assert "tests/test_keywords_postgres.py" in command
    assert "-q" not in command


def test_keyword_scripts_cleanup_and_ci_step_exist():
    shell = (ROOT / "scripts/test-keywords.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts/test-keywords.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "trap cleanup EXIT" in shell
    assert "finally" in powershell
    assert "down --volumes --remove-orphans" in shell
    assert "down --volumes --remove-orphans" in powershell
    assert "Run PostgreSQL keyword model and editor tests" in workflow
    assert "bash scripts/test-keywords.sh" in workflow


def test_keyword_guard_migration_is_vendor_gated_and_avoids_dynamic_percent_identifiers():
    migration = (ROOT / "backend/apps/keywords/migrations/0002_postgresql_guards.py").read_text(
        encoding="utf-8"
    )
    assert 'schema_editor.connection.vendor == "postgresql"' in migration
    assert "migrations.RunPython(install_guards, remove_guards)" in migration
    assert "%I" not in migration


def test_xw0302_routes_and_runtime_are_not_implemented_by_xw0301():
    urls = (ROOT / "backend/apps/keywords/urls.py").read_text(encoding="utf-8")
    services = (ROOT / "backend/apps/keywords/services.py").read_text(encoding="utf-8")
    assert "keywords/generate" not in urls
    assert "Celery" not in services
    assert "apps.quotas" not in services
