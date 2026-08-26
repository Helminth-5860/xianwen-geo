from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_question_compose_runs_real_catalog_and_postgresql_guard_tests():
    compose = yaml.safe_load((ROOT / "docker-compose.questions.yml").read_text(encoding="utf-8"))
    service = compose["services"]["question-tests"]
    assert "postgres" in service["depends_on"]
    assert "redis" not in service["depends_on"]
    command = service["command"]
    assert "tests/test_question_catalog.py" in command
    assert "tests/test_question_catalog_postgres.py" in command
    assert "tests/test_question_bank.py" in command
    assert "tests/test_question_bank_postgres.py" in command
    assert "-q" not in command


def test_question_scripts_sequence_cleanup_and_ci_step_are_explicit():
    shell = (ROOT / "scripts/test-questions.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts/test-questions.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "trap cleanup EXIT" in shell
    assert "finally" in powershell
    for script in (shell, powershell):
        assert "down --volumes --remove-orphans" in script
        assert "question-migrate" in script
        assert "question-tests" in script
    assert shell.index("up -d --wait") < shell.index("run --rm question-migrate")
    assert shell.index("run --rm question-migrate") < shell.index(
        "run --rm --no-deps question-tests"
    )
    assert "Run PostgreSQL question catalog, generation, editor, quota, and guard tests" in workflow
    assert "bash scripts/test-questions.sh" in workflow


def test_question_guard_migration_is_postgresql_gated():
    migration = (
        ROOT / "backend/apps/questions/migrations/0003_postgresql_catalog_guards.py"
    ).read_text(encoding="utf-8")
    assert 'schema_editor.connection.vendor == "postgresql"' in migration
    assert "migrations.RunPython(install, reverse)" in migration
    assert "QUESTION_CATALOG_BUILTIN_DELETE_FORBIDDEN" in migration
    assert "QUESTION_CATALOG_IDENTITY_IMMUTABLE" in migration


def test_question_generation_production_and_postgresql_guards_are_explicit():
    production = (ROOT / "backend/config/django_settings/production.py").read_text(encoding="utf-8")
    base = (ROOT / "backend/config/django_settings/base.py").read_text(encoding="utf-8")
    migration = (
        ROOT / "backend/apps/questions/migrations/0005_question_bank_postgresql_guards.py"
    ).read_text(encoding="utf-8")
    openapi = (ROOT / "openapi/openapi-v1.yaml").read_text(encoding="utf-8")
    assert 'QUESTION_GENERATION_PROVIDER == "mock"' in production
    assert 'QUESTION_GENERATION_PROVIDER not in {"unavailable", "deepseek"}' in production
    assert "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY" in production
    assert "questions.dispatch_generation_jobs" in base
    assert 'schema_editor.connection.vendor == "postgresql"' in migration
    assert "QUESTION_GENERATION_JOB_TRANSITION_INVALID" in migration
    assert "QUESTION_BANK_HISTORY_IMMUTABLE" in migration
    assert "/question-banks/generate:" in openapi
    assert "/question-banks/confirm:" in openapi
