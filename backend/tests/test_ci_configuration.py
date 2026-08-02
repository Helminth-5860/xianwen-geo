import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_ACTIONS = {
    "actions/checkout": "de0fac2e4500dabe0009e67214ff5f5447ce83dd",
    "actions/setup-python": "a309ff8b426b58ec0e2a45f0f869d46889d02405",
    "actions/setup-node": "48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e",
    "gitleaks/gitleaks-action": "ff98106e4c7b2bc287b24eaf42907196329070c7",
}


def load_workflow() -> dict:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_ci_triggers_permissions_concurrency_and_parallel_jobs():
    workflow = load_workflow()

    assert workflow["on"]["pull_request"]["branches"] == ["develop"]
    assert workflow["on"]["push"]["branches"] == ["develop"]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["security"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": "true",
    }
    assert set(workflow["jobs"]) == {"backend", "frontend", "security", "docker"}
    security_runs = {
        step.get("run") for step in workflow["jobs"]["security"]["steps"] if "run" in step
    }
    assert "bash scripts/check.sh gitleaks" in security_runs
    security_step_names = [step["name"] for step in workflow["jobs"]["security"]["steps"]]
    assert security_step_names.index(
        "Scan complete history with reproducible Gitleaks CLI"
    ) < security_step_names.index("Scan complete Git history with Gitleaks")
    for job in workflow["jobs"].values():
        assert "needs" not in job
        assert "continue-on-error" not in json.dumps(job)


def test_actions_are_allowlisted_and_pinned_to_full_commit_shas():
    workflow = load_workflow()
    action_steps = [
        step for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step
    ]

    for step in action_steps:
        action, revision = step["uses"].split("@", maxsplit=1)
        assert action in EXPECTED_ACTIONS
        assert FULL_SHA.fullmatch(revision)
        assert revision == EXPECTED_ACTIONS[action]

    checkout_steps = [step for step in action_steps if step["uses"].startswith("actions/checkout@")]
    assert checkout_steps
    assert all(step["with"]["fetch-depth"] == "0" for step in checkout_steps)


def test_runtime_versions_have_single_sources_of_truth():
    workflow = load_workflow()
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    node_version = (REPO_ROOT / "frontend" / ".nvmrc").read_text(encoding="utf-8").strip()
    dockerfile = (REPO_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert node_version == "24.18.0"
    assert package["engines"]["node"] == node_version
    assert f"node:{node_version}-" in dockerfile

    setup_node_steps = [
        step
        for step in workflow["jobs"]["frontend"]["steps"]
        if step.get("uses", "").startswith("actions/setup-node@")
    ]
    assert setup_node_steps[0]["with"]["node-version-file"] == "frontend/.nvmrc"


def test_ci_dependencies_and_local_scripts_cover_required_gates():
    runtime_requirements = (REPO_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    dev_requirements = (REPO_ROOT / "backend" / "requirements-dev.txt").read_text(encoding="utf-8")
    shell_checks = (REPO_ROOT / "scripts" / "check.sh").read_text(encoding="utf-8")
    powershell_checks = (REPO_ROOT / "scripts" / "check.ps1").read_text(encoding="utf-8")

    for dependency in ("mypy==", "django-stubs==", "djangorestframework-stubs==", "pip-audit=="):
        assert dependency in dev_requirements
        assert dependency not in runtime_requirements

    required_commands = (
        "ruff check",
        "ruff format --check",
        "mypy",
        "manage.py check",
        "makemigrations --check --dry-run",
        "pytest",
        "openapi_spec_validator",
        "pip_audit",
        "npm run lint",
        "npm run format:check",
        "npm run typecheck",
        "npm test",
        "npm run build",
        "npm audit",
        "gitleaks",
        "actionlint",
        "docker compose",
    )
    for command in required_commands:
        assert command in shell_checks
        assert command in powershell_checks


def test_compose_application_services_keep_build_targets():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    for service in ("api", "celery", "frontend"):
        assert "build" in compose["services"][service]


def test_compose_gate_builds_only_application_services():
    shell_checks = (REPO_ROOT / "scripts" / "check.sh").read_text(encoding="utf-8")

    assert "build api celery frontend" in shell_checks
    assert "docker compose up" not in shell_checks
    assert "docker compose push" not in shell_checks


def test_docker_job_runs_reproducible_postgresql_rbac_suite():
    workflow = load_workflow()
    docker_steps = workflow["jobs"]["docker"]["steps"]
    runs = [step.get("run") for step in docker_steps]
    names = [step["name"] for step in docker_steps]

    assert "Run PostgreSQL RBAC tests" in names
    assert "bash scripts/test-postgres-rbac.sh" in runs
    script = (REPO_ROOT / "scripts" / "test-postgres-rbac.sh").read_text(encoding="utf-8")
    assert "--profile rbac-test" in script
    assert "run --rm --build rbac-tests" in script
    assert "down --volumes --remove-orphans" in script
    powershell_script = (REPO_ROOT / "scripts" / "test-postgres-rbac.ps1").read_text(
        encoding="utf-8"
    )
    core_command = (
        "docker compose --project-name xianwen-rbac-test --profile rbac-test "
        "run --rm --build rbac-tests"
    )
    assert core_command in " ".join(script.replace("\\\n", "").split())
    assert core_command in " ".join(powershell_script.split())


def test_docker_job_runs_reproducible_postgresql_redis_admin_security_suite():
    workflow = load_workflow()
    docker_steps = workflow["jobs"]["docker"]["steps"]
    runs = [step.get("run") for step in docker_steps]
    names = [step["name"] for step in docker_steps]

    assert "Run PostgreSQL/Redis administrator security tests" in names
    assert "bash scripts/test-admin-security.sh" in runs
    shell_script = (REPO_ROOT / "scripts" / "test-admin-security.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts" / "test-admin-security.ps1").read_text(
        encoding="utf-8"
    )
    core_command = (
        "docker compose --project-name xianwen-admin-security-test "
        "--profile admin-security-test run --rm --build admin-security-tests"
    )
    assert "tests/test_admin_security_postgres.py" in (REPO_ROOT / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert core_command in " ".join(shell_script.replace("\\\n", "").split())
    assert core_command in " ".join(powershell_script.split())
    assert "down --volumes --remove-orphans" in shell_script
    assert "down --volumes --remove-orphans" in powershell_script


def test_docker_job_runs_reproducible_postgresql_redis_risk_approval_suite():
    workflow = load_workflow()
    docker_steps = workflow["jobs"]["docker"]["steps"]
    runs = [step.get("run") for step in docker_steps]
    names = [step["name"] for step in docker_steps]

    assert "Run PostgreSQL/Redis high-risk approval tests" in names
    assert "bash scripts/test-risk-approval.sh" in runs
    shell_script = (REPO_ROOT / "scripts" / "test-risk-approval.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts" / "test-risk-approval.ps1").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    core_command = (
        "docker compose --project-name xianwen-risk-approval-test "
        "--profile risk-approval-test run --rm --build risk-approval-tests"
    )
    assert "tests/test_risk_approval_postgres.py" in compose
    assert core_command in " ".join(shell_script.replace(chr(92) + chr(10), "").split())
    assert core_command in " ".join(powershell_script.split())
    assert "down --volumes --remove-orphans" in shell_script
    assert "down --volumes --remove-orphans" in powershell_script


def test_risk_approval_remote_suite_keeps_expiration_and_approver_regressions():
    suite = (REPO_ROOT / "backend" / "tests" / "test_risk_approval_postgres.py").read_text(
        encoding="utf-8"
    )
    required_tests = (
        "test_postgresql_approve_expire_race_has_exactly_one_terminal_winner",
        "test_postgresql_policy_change_marks_pending_request_stale_with_one_audit",
        "test_postgresql_disabled_or_locked_approver_cannot_win_pending_request",
        "test_postgresql_concurrent_expiration_writes_exactly_one_audit_event",
        "test_postgresql_expiration_audit_failure_rolls_back_to_pending",
    )
    for test_name in required_tests:
        assert f"def {test_name}" in suite

    workflow = load_workflow()
    docker_steps = workflow["jobs"]["docker"]["steps"]
    assert any(
        step.get("name") == "Run PostgreSQL/Redis high-risk approval tests"
        and step.get("run") == "bash scripts/test-risk-approval.sh"
        for step in docker_steps
    )
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert (
        '["python", "-m", "pytest", "tests/test_risk_approval_postgres.py", '
        '"--ds=config.settings", "-q", "-p", "no:cacheprovider"]'
    ) in compose


def test_docker_job_runs_reproducible_postgresql_plans_suite():
    workflow = load_workflow()
    docker_steps = workflow["jobs"]["docker"]["steps"]
    assert any(
        step.get("name") == "Run PostgreSQL plans and immutable versions tests"
        and step.get("run") == "bash scripts/test-plans.sh"
        for step in docker_steps
    )
    shell_script = (REPO_ROOT / "scripts" / "test-plans.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts" / "test-plans.ps1").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    core_command = (
        "docker compose --project-name xianwen-plans-test "
        "--profile plans-test run --rm --build plans-tests"
    )
    assert "tests/test_plans_postgres.py" in compose
    assert core_command in " ".join(shell_script.replace(chr(92) + chr(10), "").split())
    assert core_command in " ".join(powershell_script.split())
    assert "down --volumes --remove-orphans" in shell_script
    assert "down --volumes --remove-orphans" in powershell_script
    assert "openssl rand -hex 32" in shell_script
    assert "[guid]::NewGuid()" in powershell_script
    suite = (REPO_ROOT / "backend" / "tests" / "test_plans_postgres.py").read_text(encoding="utf-8")

    assert suite.count("def test_postgresql_") == 8
    assert 'profiles: ["plans-test"]' in compose


def test_docker_job_runs_reproducible_postgresql_plan_application_suite():
    workflow = load_workflow()
    docker_steps = workflow["jobs"]["docker"]["steps"]
    assert any(
        step.get("name") == "Run PostgreSQL plan application concurrency tests"
        and step.get("run") == "bash scripts/test-plan-applications.sh"
        for step in docker_steps
    )
    shell_script = (REPO_ROOT / "scripts" / "test-plan-applications.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts" / "test-plan-applications.ps1").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    core_command = (
        "docker compose --project-name xianwen-plan-application-test "
        "--profile plan-application-test run --rm --build plan-application-tests"
    )
    assert "tests/test_plan_applications_postgres.py" in compose
    assert core_command in " ".join(shell_script.replace(chr(92) + chr(10), "").split())
    assert core_command in " ".join(powershell_script.split())
    assert "down --volumes --remove-orphans" in shell_script
    assert "down --volumes --remove-orphans" in powershell_script
    assert "openssl rand -hex 32" in shell_script and "[guid]::NewGuid()" in powershell_script
    assert 'profiles: ["plan-application-test"]' in compose
    suite = (REPO_ROOT / "backend" / "tests" / "test_plan_applications_postgres.py").read_text(
        encoding="utf-8"
    )
    assert suite.count("def test_postgresql_") >= 9


def test_docker_job_runs_reproducible_postgresql_subscription_suite():
    workflow = load_workflow()
    docker_steps = workflow["jobs"]["docker"]["steps"]
    assert any(
        step.get("name") == "Run PostgreSQL/Redis subscription concurrency and guard tests"
        and step.get("run") == "bash scripts/test-subscriptions.sh"
        for step in docker_steps
    )
    shell_script = (REPO_ROOT / "scripts" / "test-subscriptions.sh").read_text(encoding="utf-8")
    powershell_script = (REPO_ROOT / "scripts" / "test-subscriptions.ps1").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    core_command = (
        "docker compose --project-name xianwen-subscription-test "
        "--profile subscription-test run --rm --build subscription-tests"
    )
    assert "tests/test_subscriptions_postgres.py" in compose
    assert core_command in " ".join(shell_script.replace(chr(92) + chr(10), "").split())
    assert core_command in " ".join(powershell_script.split())
    assert "down --volumes --remove-orphans" in shell_script
    assert "down --volumes --remove-orphans" in powershell_script
    assert "openssl rand -hex 32" in shell_script
    assert "[guid]::NewGuid()" in powershell_script
    assert 'profiles: ["subscription-test"]' in compose
    suite = (REPO_ROOT / "backend" / "tests" / "test_subscriptions_postgres.py").read_text(
        encoding="utf-8"
    )
    evidence_suite = (
        REPO_ROOT / "backend" / "tests" / "test_subscriptions_postgres_evidence.py"
    ).read_text(encoding="utf-8")
    assert suite.count("def test_postgresql_") == 7
    assert evidence_suite.count("def test_postgresql_") == 10
    assert "tests/test_subscriptions_postgres_evidence.py" in compose
