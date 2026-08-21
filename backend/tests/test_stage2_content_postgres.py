from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction

from apps.ai.runtime import get_runtime_snapshot
from apps.articles.models import ArticleGenerationResult
from apps.articles.services import create_generation_job, execute_generation_job
from apps.geo.models import ReportShareAccessLog
from apps.geo.sharing import close_report_share, create_report_share
from apps.users.models import User
from tests.test_stage2_content_distribution import (
    _article_setup,
    _ArticleAdapter,
    _body,
)
from tests.test_stage2_content_distribution import (
    stage2_facts as stage2_facts_factory,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL-specific Stage 2 evidence requires PostgreSQL.",
    ),
]


@pytest.fixture
def postgres_stage2_facts(monkeypatch):
    return stage2_facts_factory.__wrapped__(monkeypatch)


def _assert_database_rejects(sql, params):
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


def test_stage2_tables_and_guards_are_installed():
    expected_tables = {
        "article_types",
        "article_template_versions",
        "article_source_packs",
        "article_source_items",
        "articles",
        "article_outlines",
        "article_generation_jobs",
        "article_generation_results",
        "article_quality_checks",
        "article_moderation_reviews",
        "article_exports",
        "publishing_channels",
        "channel_template_versions",
        "channel_adaptations",
        "publication_link_checks",
        "subject_white_label_configs",
        "report_shares",
        "report_share_access_logs",
    }
    expected_triggers = {
        "article_template_versions_immutable",
        "channel_template_versions_immutable",
        "article_generation_results_immutable",
        "article_quality_checks_immutable",
        "article_moderation_reviews_immutable",
        "article_exports_immutable",
        "publication_link_checks_immutable",
        "article_source_packs_guard",
        "article_source_items_guard",
        "article_generation_jobs_guard",
        "articles_ai_original_guard",
        "report_shares_guard",
        "report_share_access_logs_guard",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename = ANY(%s)",
            [sorted(expected_tables)],
        )
        tables = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        triggers = {row[0] for row in cursor.fetchall()}
    assert tables == expected_tables
    assert expected_triggers.issubset(triggers)


def test_article_and_source_evidence_reject_raw_mutation(postgres_stage2_facts):
    user, _, _, pack, item, article = _article_setup(postgres_stage2_facts)
    runtime = get_runtime_snapshot(model_key="deepseek", require_available=True)
    adapter = _ArticleAdapter(_body(item.pk))
    with patch("apps.articles.services._runtime", return_value=(runtime, adapter)):
        job, _ = create_generation_job(
            user=user,
            article_id=article.pk,
            operation="body",
            idempotency_key="stage2-postgres-evidence-0001",
            request_id=uuid.uuid4(),
        )
        assert execute_generation_job(job_id=job.pk) == {"status": "succeeded"}
    result = ArticleGenerationResult.objects.get(job=job)

    _assert_database_rejects(
        "UPDATE article_generation_results SET output_digest = %s WHERE id = %s",
        ["0" * 64, result.pk],
    )
    _assert_database_rejects(
        "UPDATE article_source_packs SET snapshot_digest = %s WHERE id = %s",
        ["0" * 64, pack.pk],
    )
    _assert_database_rejects(
        "UPDATE article_source_items SET excerpt = %s WHERE id = %s",
        ["tampered", item.pk],
    )
    _assert_database_rejects(
        "UPDATE article_generation_jobs SET provider_model_id = %s WHERE id = %s",
        ["tampered-model", job.pk],
    )
    _assert_database_rejects(
        "UPDATE articles SET ai_original_content = %s WHERE id = %s",
        ["tampered", article.pk],
    )


def test_report_share_snapshot_close_and_access_log_are_database_guarded(
    postgres_stage2_facts,
):
    user, _, _, _, _, _, report = postgres_stage2_facts
    share, _ = create_report_share(
        user=user,
        report_id=report.pk,
        password="Stage2-Postgres-Password!",
        expires_in_days=5,
    )
    log = ReportShareAccessLog.objects.create(
        share=share,
        ip_digest="a" * 64,
        user_agent="postgres-test",
        result="success",
    )
    _assert_database_rejects(
        "UPDATE report_shares SET report_snapshot_digest = %s WHERE id = %s",
        ["0" * 64, share.pk],
    )
    _assert_database_rejects(
        "UPDATE report_share_access_logs SET result = %s WHERE id = %s",
        ["tampered", log.pk],
    )
    close_report_share(user=user, share_id=share.pk)
    _assert_database_rejects(
        "UPDATE report_shares SET closed_at = NULL WHERE id = %s",
        [share.pk],
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_article_idempotency_creates_one_job_and_one_hold(postgres_stage2_facts):
    user, _, _, _, _, article = _article_setup(postgres_stage2_facts)
    runtime = get_runtime_snapshot(model_key="deepseek", require_available=True)
    adapter = _ArticleAdapter({"outline": "unused"})
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        local_user = User.objects.get(pk=user.pk)
        barrier.wait(timeout=10)
        try:
            with patch("apps.articles.services._runtime", return_value=(runtime, adapter)):
                job, created = create_generation_job(
                    user=local_user,
                    article_id=article.pk,
                    operation="body",
                    idempotency_key="stage2-concurrent-body-0001",
                    request_id=uuid.uuid4(),
                )
            return job.pk, created, job.quota_hold_id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: worker(), range(2)))
    assert len({row[0] for row in rows}) == 1
    assert sorted(row[1] for row in rows) == [False, True]
    assert len({row[2] for row in rows}) == 1
