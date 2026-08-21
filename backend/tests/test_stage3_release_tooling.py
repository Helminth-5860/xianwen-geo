from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_scripts_are_guarded_and_do_not_embed_secrets():
    required = (
        "scripts/release-preflight.ps1",
        "scripts/release-preflight.sh",
        "scripts/sync-release-source.ps1",
        "scripts/sync-release-source.sh",
        "scripts/rollback-preflight.ps1",
        "scripts/rollback-preflight.sh",
        "scripts/publish-deployed-sha.ps1",
        "scripts/publish-deployed-sha.sh",
        "scripts/verify-backup.ps1",
        "scripts/verify-backup.sh",
    )
    for relative in required:
        content = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert any(
            marker in content
            for marker in ("EXPECTED_SHA", "ExpectedSha", "CURRENT_SHA", "CurrentSha")
        )
        assert "status --porcelain" in content
        assert "reset --hard" not in content
        assert "git add ." not in content
        assert "Authorization" not in content
        assert "API_KEY" not in content


def test_release_scripts_freeze_fast_forward_rollback_and_atomic_marker_guards():
    sync = (REPO_ROOT / "scripts/sync-release-source.sh").read_text(encoding="utf-8")
    rollback = (REPO_ROOT / "scripts/rollback-preflight.sh").read_text(encoding="utf-8")
    marker = (REPO_ROOT / "scripts/publish-deployed-sha.sh").read_text(encoding="utf-8")

    assert "pull --ff-only origin develop" in sync
    assert "merge-base --is-ancestor" in rollback
    assert "ROLLBACK_MIGRATION_REVIEW_REQUIRED" in rollback
    assert 'pg_restore_bin" --list' in rollback
    assert "manage.py release_readiness" in marker
    assert "mktemp" in marker and "mv -f" in marker
    assert 'rollout_performed":false' in marker

    verifier = (
        REPO_ROOT / "backend/apps/operations/management/commands/verify_backup_artifact.py"
    ).read_text(encoding="utf-8")
    assert "restore_verified_at=None" in verifier
    assert "restore_verified=false" in verifier


def test_stage3_contract_freezes_code_external_boundary_and_safe_summary():
    document = (REPO_ROOT / "docs/58-STAGE3-RELEASE-HARDENING-UAT-WAVE.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "CODE_ONLY",
        "EXTERNAL_GATE",
        "NOT_READY",
        "exact SHA",
        "provider_request_id",
        "不得输出 prompt",
        "不得执行真实部署",
    ):
        assert phrase in document
