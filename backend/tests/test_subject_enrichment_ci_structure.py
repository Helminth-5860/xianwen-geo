from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_subject_enrichment_compose_runs_migration_worker_and_tests_separately():
    compose = yaml.safe_load(
        (ROOT / "docker-compose.subject-enrichment.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    assert {
        "subject-enrichment-migrate",
        "subject-enrichment-worker",
        "subject-enrichment-tests",
    } <= set(services)
    assert any("ai_content" in item for item in services["subject-enrichment-worker"]["command"])
    assert (
        "tests/test_subject_enrichment_postgres.py"
        in services["subject-enrichment-tests"]["command"]
    )
    assert "-q" not in services["subject-enrichment-tests"]["command"]


def test_subject_enrichment_scripts_stage_migrate_worker_tests_and_cleanup():
    shell = (ROOT / "scripts/test-subject-enrichment.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts/test-subject-enrichment.ps1").read_text(encoding="utf-8")
    for content in (shell, powershell):
        assert "subject-enrichment-migrate" in content
        assert "subject-enrichment-worker" in content
        assert "subject-enrichment-tests" in content
        assert content.index("subject-enrichment-migrate") < content.rindex(
            "subject-enrichment-tests"
        )
        assert "down --volumes --remove-orphans" in content
    assert "trap cleanup EXIT" in shell
    assert "finally" in powershell


def test_celery_autodiscovery_and_ai_content_route_are_explicit():
    tasks = (ROOT / "backend/apps/subjects/tasks.py").read_text(encoding="utf-8")
    settings = (ROOT / "backend/config/django_settings/base.py").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "execute_enrichment_task" in tasks
    assert '"subjects.execute_enrichment": {"queue": "ai_content"}' in settings
    assert '"--queues=system_tasks,ai_content"' in compose


def test_ci_runs_dedicated_subject_enrichment_suite():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "Run PostgreSQL/Redis subject enrichment Mock flow tests" in workflow
    assert "bash scripts/test-subject-enrichment.sh" in workflow


def test_subject_enrichment_postgresql_guards_are_vendor_gated():
    migration = (
        ROOT / "backend/apps/subjects/migrations/0013_subject_enrichment_postgresql_guards.py"
    ).read_text(encoding="utf-8")
    assert 'schema_editor.connection.vendor == "postgresql"' in migration
    assert "migrations.RunPython(install_guards, remove_guards)" in migration
    assert "migrations.RunSQL(FORWARD, REVERSE)" not in migration
    assert "%I" not in migration
