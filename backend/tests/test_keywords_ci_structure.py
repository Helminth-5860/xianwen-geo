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
    assert "tests/test_keyword_generation_postgres.py" in command
    assert "tests/test_distillation_postgres.py" in command
    assert "-q" not in command


def test_keyword_scripts_cleanup_and_ci_step_exist():
    shell = (ROOT / "scripts/test-keywords.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts/test-keywords.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "trap cleanup EXIT" in shell
    assert "finally" in powershell
    assert "down --volumes --remove-orphans" in shell
    assert "down --volumes --remove-orphans" in powershell
    assert "Run PostgreSQL keyword model, editor, AI generation, and distillation tests" in workflow
    assert "bash scripts/test-keywords.sh" in workflow


def test_keyword_guard_migration_is_vendor_gated_and_avoids_dynamic_percent_identifiers():
    migration = (ROOT / "backend/apps/keywords/migrations/0002_postgresql_guards.py").read_text(
        encoding="utf-8"
    )
    assert 'schema_editor.connection.vendor == "postgresql"' in migration
    assert "migrations.RunPython(install_guards, remove_guards)" in migration
    assert "%I" not in migration


def test_xw0302_routes_runtime_and_guards_are_wired():
    urls = (ROOT / "backend/apps/keywords/urls.py").read_text(encoding="utf-8")
    generation_services = (ROOT / "backend/apps/keywords/generation_services.py").read_text(
        encoding="utf-8"
    )
    generation_tasks = (ROOT / "backend/apps/keywords/generation_tasks.py").read_text(
        encoding="utf-8"
    )
    keyword_guards = (
        ROOT / "backend/apps/keywords/migrations/0005_keyword_generation_postgresql_guards.py"
    ).read_text(encoding="utf-8")
    quota_guards = (
        ROOT / "backend/apps/quotas/migrations/0012_subject_cycle_postgresql_guards.py"
    ).read_text(encoding="utf-8")
    assert "keywords/generate" in urls
    assert "create_keyword_generation_job" in generation_services
    assert "keywords.execute_generation" in generation_tasks
    assert "keywords_generation_job_guard" in keyword_guards
    assert "previous_row.subject_id" in quota_guards


def test_xw0303_routes_runtime_schedule_and_guards_are_wired():
    urls = (ROOT / "backend/apps/keywords/urls.py").read_text(encoding="utf-8")
    services = (ROOT / "backend/apps/keywords/distillation_services.py").read_text(encoding="utf-8")
    tasks = (ROOT / "backend/apps/keywords/distillation_tasks.py").read_text(encoding="utf-8")
    settings = (ROOT / "backend/config/django_settings/base.py").read_text(encoding="utf-8")
    guards = (
        ROOT / "backend/apps/keywords/migrations/0007_distillation_postgresql_guards.py"
    ).read_text(encoding="utf-8")
    assert "distillations/draft" in urls
    assert "distillations/confirm" in urls
    assert "create_distillation_job" in services
    assert "keywords.execute_distillation" in tasks
    assert '"task": "keywords.dispatch_distillation_jobs"' in settings
    assert '"keywords.execute_distillation": {"queue": "ai_content"}' in settings
    assert "keywords_distillation_job_guard" in guards
    assert "keywords_assert_distillation_set" in guards
    assert 'schema_editor.connection.vendor == "postgresql"' in guards
