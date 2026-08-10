from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_subject_schema_postgresql_suite_is_wired_into_docker_job():
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["docker"]["steps"]
    assert any(
        step.get("name") == "Run PostgreSQL/Redis subject schema tests"
        and step.get("run") == "bash scripts/test-subject-schema.sh"
        for step in steps
    )
    shell_script = (REPO_ROOT / "scripts" / "test-subject-schema.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts" / "test-subject-schema.ps1").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "docker-compose.subject-schema.yml").read_text(encoding="utf-8")
    assert "subject-schema-tests" in shell_script
    assert "subject-schema-tests" in powershell_script
    assert "tests/test_subject_schema_postgres.py" in compose
    assert "down --volumes --remove-orphans" in shell_script
    assert "down --volumes --remove-orphans" in powershell_script
    assert "openssl rand -hex 32" in shell_script
    assert "[guid]::NewGuid()" in powershell_script
    suite = (REPO_ROOT / "backend" / "tests" / "test_subject_schema_postgres.py").read_text(
        encoding="utf-8"
    )
    required = (
        "test_catalog_rows_reject_raw_sql_delete",
        "test_machine_semantics_reject_raw_sql_updates",
        "test_common_custom_key_conflict_is_rejected_at_commit",
        "test_active_schema_cannot_lose_unique_required_official_name",
        "test_two_concurrent_field_updates_serialize_on_schema_version",
        "test_schema_mutation_and_audit_event_roll_back_together",
    )
    for test_name in required:
        assert f"def {test_name}" in suite


def test_subject_schema_document_freezes_snapshot_and_safe_rollback_boundaries():
    document = (REPO_ROOT / "docs" / "28-SUBJECT-TYPES-DYNAMIC-FIELDS.md").read_text(
        encoding="utf-8"
    )
    seed_migration = (
        REPO_ROOT
        / "backend"
        / "apps"
        / "subjects"
        / "migrations"
        / "0002_seed_builtin_subject_catalog.py"
    ).read_text(encoding="utf-8")
    assert "schema_version" in document
    assert "canonical" in document
    assert "snapshot" in document
    assert "digest" in document
    assert "不创建 Subject、SubjectVersion" in document
    assert "migrations.RunPython.noop" in seed_migration
