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
    assert "tests/test_subject_drafts_postgres.py" in compose
    assert "tests/test_subject_versions_postgres.py" in compose
    assert "tests/test_subject_risk_postgres.py" in compose
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
    draft_suite = (REPO_ROOT / "backend" / "tests" / "test_subject_drafts_postgres.py").read_text(
        encoding="utf-8"
    )
    draft_required = (
        "test_no_plan_concurrent_second_draft_allows_exactly_one",
        "test_valid_subscription_does_not_limit_draft_count",
        "test_active_limit_concurrent_last_slot_allows_exactly_one",
        "test_subscription_and_trial_creation_recheck_target_subject_limit",
        "test_immediate_plan_change_preview_and_execution_recheck_target_limit",
        "test_scheduled_renewal_future_cap_blocks_activation_and_cancel_restores_current_cap",
        "test_subject_activation_and_scheduled_renewal_cancel_race_is_safe",
        "test_scheduled_renewal_subject_reconciliation_is_recoverable",
        "test_scheduled_renewal_and_subject_activation_race_is_serialized",
    )
    for test_name in draft_required:
        assert f"def {test_name}" in draft_suite
    version_suite = (
        REPO_ROOT / "backend" / "tests" / "test_subject_versions_postgres.py"
    ).read_text(encoding="utf-8")
    version_required = (
        "test_concurrent_first_commit_is_exactly_once_and_strictly_starts_at_one",
        "test_raw_sql_rejects_gap_schema_mismatch_and_non_max_current_pointer",
        "test_deferred_chain_requires_official_name_current_max_and_bound_event",
        "test_version_name_product_and_event_evidence_is_immutable_by_raw_sql",
        "test_name_role_type_guard_rejects_invalid_machine_semantics",
        "test_commit_failure_injection_rolls_back_every_formal_fact",
        "test_migration_preflight_refuses_to_invent_semantics_for_existing_versions",
    )
    for test_name in version_required:
        assert f"def {test_name}" in version_suite
    guard_migration = (
        REPO_ROOT
        / "backend"
        / "apps"
        / "subjects"
        / "migrations"
        / "0007_subject_version_postgresql_guards.py"
    ).read_text(encoding="utf-8")
    assert "BEFORE INSERT OR UPDATE OR DELETE ON subject_names" in guard_migration
    assert "BEFORE INSERT OR UPDATE OR DELETE ON subject_products" in guard_migration
    assert "OLD.status = 'archived' AND NEW.draft_values" in guard_migration
    assert guard_migration.count("CREATE OR REPLACE FUNCTION subjects_guard_subject()") == 2


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


def test_subject_drafts_document_and_frontend_freeze_historical_schema_boundary():
    document = (REPO_ROOT / "docs" / "29-SUBJECT-DRAFTS-ACTIVE-LIMITS.md").read_text(
        encoding="utf-8"
    )
    detail_page = (REPO_ROOT / "frontend" / "app" / "subjects" / "[id]" / "page.tsx").read_text(
        encoding="utf-8"
    )
    migration = (
        REPO_ROOT
        / "backend"
        / "apps"
        / "subjects"
        / "migrations"
        / "0005_subject_data_postgresql_guards.py"
    ).read_text(encoding="utf-8")
    for value in (
        "no production write path for `SubjectVersion`",
        "canonical schema snapshot",
        "SUBJECT_LIMIT_RECONCILIATION_REQUIRED",
        "Reversing 0004 drops all XW-0202 subject-domain tables",
    ):
        assert value in document
    assert "subject.form_schema.fields" in detail_page
    assert "getSubjectFormSchema" not in detail_page
    assert "subjects_guard_subject" in migration
    assert "subjects_assert_context" in migration
