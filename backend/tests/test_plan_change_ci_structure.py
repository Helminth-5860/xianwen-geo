from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docker_job_runs_reproducible_postgresql_redis_plan_change_suite():
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["docker"]["steps"]
    assert any(
        step.get("name") == "Run PostgreSQL/Redis plan change tests"
        and step.get("run") == "bash scripts/test-plan-changes.sh"
        for step in steps
    )
    shell_script = (REPO_ROOT / "scripts" / "test-plan-changes.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts" / "test-plan-changes.ps1").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "docker-compose.plan-change.yml").read_text(encoding="utf-8")
    suite = (REPO_ROOT / "backend" / "tests" / "test_plan_changes_postgres.py").read_text(
        encoding="utf-8"
    )
    check_shell = (REPO_ROOT / "scripts" / "check.sh").read_text(encoding="utf-8")
    check_powershell = (REPO_ROOT / "scripts" / "check.ps1").read_text(encoding="utf-8")
    assert check_shell.count("PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY=ci-only-plan-change") == 2
    assert check_powershell.count('PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = "ci-only-plan-change') == 1
    shared_compose_scripts = [
        "test-postgres-rbac",
        "test-admin-security",
        "test-risk-action",
        "test-plans",
        "test-plan-applications",
        "test-subscriptions",
        "test-quotas",
    ]
    for script_name in shared_compose_scripts:
        shell_entrypoint = (REPO_ROOT / "scripts" / f"{script_name}.sh").read_text(encoding="utf-8")
        powershell_entrypoint = (REPO_ROOT / "scripts" / f"{script_name}.ps1").read_text(
            encoding="utf-8"
        )
        assert "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY" in shell_entrypoint
        assert "openssl rand -hex 32" in shell_entrypoint
        assert "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY" in powershell_entrypoint
        assert "[guid]::NewGuid()" in powershell_entrypoint
    assert 'profiles: ["plan-change-test"]' in compose
    assert "tests/test_plan_changes_postgres.py" in compose
    assert "docker-compose.plan-change.yml" in shell_script
    assert "docker-compose.plan-change.yml" in powershell_script
    assert "run --rm --build plan-change-tests" in " ".join(
        shell_script.replace(chr(92) + chr(10), "").split()
    )
    assert "run --rm --build plan-change-tests" in " ".join(powershell_script.split())
    assert "down --volumes --remove-orphans" in shell_script
    assert "down --volumes --remove-orphans" in powershell_script
    assert "openssl rand -hex 32" in shell_script
    assert "[guid]::NewGuid()" in powershell_script
    assert suite.count("def test_postgresql_") == 23
    for required_test in (
        "test_postgresql_renewal_is_scheduled_without_future_facts_and_cancel_is_safe",
        "test_postgresql_change_and_cancel_idempotency_conflict_matrix",
        "test_postgresql_preview_and_concurrent_direct_submit_are_exactly_once",
        "test_postgresql_transfer_ledger_pair_is_deferred_complete_and_atomic",
        "test_postgresql_audit_failure_rolls_back_direct_plan_change",
        "test_postgresql_submission_recomputes_and_rejects_untrusted_preview_fields",
        "test_postgresql_trial_conversion_boundaries_are_server_enforced",
        "test_postgresql_http_change_and_cancel_idempotency_matrix",
        "test_postgresql_transfer_is_bound_to_change_accounts_direction_and_quota_type",
        "test_postgresql_transfer_ledger_side_failure_rolls_back_entire_change",
    ):
        assert f"def {required_test}" in suite
    transfer_guard = (
        REPO_ROOT
        / "backend"
        / "apps"
        / "quotas"
        / "migrations"
        / "0006_plan_change_transfer_ledger_guards.py"
    ).read_text(encoding="utf-8")
    assert "quotas_transfer_ledger_bound" in transfer_guard
    assert "QUOTA_TRANSFER_OUT_LEDGER_UNBOUND" in transfer_guard
    assert "QUOTA_TRANSFER_IN_LEDGER_UNBOUND" in transfer_guard
    change_guard = (
        REPO_ROOT
        / "backend"
        / "apps"
        / "quotas"
        / "migrations"
        / "0007_plan_change_transfer_change_guards.py"
    ).read_text(encoding="utf-8")
    for required_guard in (
        "change_row.from_subscription_id",
        "subscriptions WHERE source_change_id = NEW.change_id",
        "out_row.business_id <> NEW.change_id",
        "in_row.business_id <> NEW.change_id",
        "change_row.status <> 'executed'",
    ):
        assert required_guard in change_guard
