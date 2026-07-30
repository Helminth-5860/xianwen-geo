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
