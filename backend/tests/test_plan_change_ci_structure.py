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
    assert suite.count("def test_postgresql_") == 8
