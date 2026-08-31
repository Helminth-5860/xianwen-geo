from __future__ import annotations

import json
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.ai.contracts import (
    AIAdapterDescriptor,
    AIAdapterResponse,
    AIModelCapability,
    AIModelIdentity,
    AIUsage,
)
from apps.articles.models import Article, ArticleGenerationJob
from apps.articles.video_services import (
    VIDEO_SCRIPT_CUSTOM_TYPE,
    VIDEO_SCRIPT_PROMPT_VERSION,
    VIDEO_SCRIPT_SCHEMA_VERSION,
    VIDEO_SCRIPT_WORKSPACE_VERSION,
    execute_video_generation_job,
)
from apps.negative_index.models import NegativeIndexScan
from apps.negative_index.scanner import NegativeScanPayload, run_negative_search
from apps.negative_index.services import (
    create_negative_index_scan,
    execute_negative_index_scan,
)
from apps.publishing.models import Publication, PublicationTarget
from apps.publishing.publication_state import aggregate_publication
from apps.quotas.services import freeze_quota
from apps.search_discovery.engine import AdaptiveSearchPayload
from apps.search_discovery.provider import SearchProviderError
from apps.search_discovery.subject_context import SubjectSearchContext as SharedSearchContext
from apps.source_index.models import SourceIndexScan
from apps.source_index.scanner import ScanPayload, SubjectSearchContext, run_adaptive_scan
from apps.source_index.services import create_source_index_scan, execute_source_index_scan
from apps.subjects.models import Subject, SubjectType, SubjectVersion
from apps.website_audits.crawler import CrawlResult
from apps.website_audits.models import WebsiteAudit
from apps.website_audits.services import create_website_audit, execute_website_audit
from apps.websites.models import WebsiteGenerationJob, WebsiteProject
from apps.websites.services import PAGE_KEYS, execute_generation_job
from tests.test_quotas import add_customer_quota, provision

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _catalogs():
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def _scan_facts():
    user = get_user_model().objects.create_user(
        phone="13800138991",
        password="StrongPass123!",
        nickname="扫描边界测试",
    )
    subject_type = SubjectType.objects.create(key="scan-boundary", name="企业")
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.ACTIVE,
        draft_values={},
        schema_version=1,
        schema_snapshot={},
        schema_digest="scan-boundary-digest",
    )
    return user, subject


def _billable_facts(*quota_types: str, with_version: bool = False):
    admin, user, subscription = provision(phone="13800138992")
    subject_type = SubjectType.objects.create(
        key=f"quota-boundary-{uuid.uuid4().hex}",
        name="企业",
    )
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.ACTIVE,
        draft_values={},
        schema_version=1,
        schema_snapshot={},
        schema_digest="quota-boundary-digest",
    )
    subject_version = None
    if with_version:
        subject_version = SubjectVersion.objects.create(
            subject=subject,
            version_no=1,
            field_values={"official_name": "额度验收主体"},
            schema_version=1,
            schema_snapshot={},
            schema_digest="quota-boundary-schema",
            field_values_digest="quota-boundary-values",
            semantic_digest="quota-boundary-semantic",
            official_name="额度验收主体",
            created_by=user,
        )
        Subject.objects.filter(pk=subject.pk).update(current_version=subject_version)
        subject.refresh_from_db()
    accounts = {
        quota_type: add_customer_quota(
            subscription,
            admin,
            quota_type=quota_type,
            amount=3,
        )
        for quota_type in quota_types
    }
    return admin, user, subscription, subject, subject_version, accounts


def _assert_settlement(hold, *, consumed: int, released: int):
    hold.refresh_from_db()
    assert hold.requested_amount == 1
    assert hold.consumed_amount == consumed
    assert hold.released_amount == released


class _EmptyProvider:
    top_k = 50

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def search(self, query, *, start_date=None, end_date=None):
        del query, start_date, end_date
        with self._lock:
            self.calls += 1
        return []


def test_source_index_never_exceeds_thirty_provider_requests(settings):
    user, subject = _scan_facts()
    scan = SourceIndexScan.objects.create(user=user, subject=subject)
    context = SubjectSearchContext(
        official_name="扫描边界测试主体",
        anchors=["扫描边界测试主体"],
        products=[],
        keywords=[],
        self_domains=set(),
    )
    provider = _EmptyProvider()
    settings.SOURCE_INDEX_MAX_REQUESTS = 999
    settings.SOURCE_INDEX_MIN_REQUESTS = 999
    settings.SOURCE_INDEX_SEARCH_CONCURRENCY = 3
    settings.SOURCE_INDEX_LOW_YIELD_BATCHES = 99
    settings.SOURCE_INDEX_SEARCH_BUDGET_SECONDS = 999

    with (
        patch("apps.source_index.scanner.build_subject_search_context", return_value=context),
        patch(
            "apps.source_index.scanner.build_initial_queries",
            return_value=[f"边界查询 {index}" for index in range(40)],
        ),
        patch("apps.source_index.scanner.time_module.monotonic", return_value=0.0),
        patch("apps.source_index.scanner.time_module.sleep"),
    ):
        payload = run_adaptive_scan(scan, provider=provider)

    scan.refresh_from_db()
    assert payload.provider_requests == provider.calls == 30
    assert scan.provider_request_count == 30
    assert payload.limit_reached is True


def test_negative_index_passes_a_hard_thirty_request_cap_to_adaptive_search(settings):
    user, subject = _scan_facts()
    scan = NegativeIndexScan.objects.create(user=user, subject=subject)
    context = SharedSearchContext(
        official_name="扫描边界测试主体",
        anchors=["扫描边界测试主体"],
        products=[],
        keywords=[],
        self_domains=set(),
    )
    captured = {}

    def fake_search(*, initial_queries, provider, config, progress_callback):
        del initial_queries, provider, progress_callback
        captured["max_requests"] = config.max_requests
        return AdaptiveSearchPayload(
            records={},
            hits=[],
            provider_requests=0,
            provider_errors=0,
            raw_results=0,
            query_count=0,
            limit_reached=False,
            partial=False,
        )

    settings.NEGATIVE_INDEX_MAX_REQUESTS = 999
    with (
        patch("apps.negative_index.scanner.build_subject_search_context", return_value=context),
        patch(
            "apps.negative_index.scanner.build_negative_queries",
            return_value=["扫描边界测试主体 投诉"],
        ),
        patch("apps.negative_index.scanner.run_adaptive_search", side_effect=fake_search),
    ):
        run_negative_search(scan, provider=_EmptyProvider())

    assert captured["max_requests"] == 30


def test_source_and_negative_scans_consume_on_success_and_release_on_failure():
    _, user, _, subject, _, _ = _billable_facts(
        "source_index_scans",
        "negative_index_scans",
    )
    source_context = SubjectSearchContext(
        official_name="额度验收主体",
        anchors=["额度验收主体"],
        products=[],
        keywords=[],
        self_domains=set(),
    )
    source_success = create_source_index_scan(user=user, subject_id=subject.pk)
    source_payload = ScanPayload(
        context=source_context,
        records={},
        hits=[],
        provider_requests=1,
        provider_errors=0,
        raw_results=0,
        query_count=1,
        limit_reached=False,
        partial=False,
    )
    with (
        patch("apps.source_index.services.BaiduSearchProvider"),
        patch("apps.source_index.services.run_adaptive_scan", return_value=source_payload),
    ):
        assert execute_source_index_scan(source_success.pk)["status"] == "succeeded"
    _assert_settlement(source_success.quota_hold, consumed=1, released=0)

    source_failure = create_source_index_scan(user=user, subject_id=subject.pk)
    with (
        patch("apps.source_index.services.BaiduSearchProvider"),
        patch(
            "apps.source_index.services.run_adaptive_scan",
            side_effect=SearchProviderError("SOURCE_INDEX_TEST_FAILURE"),
        ),
        pytest.raises(SearchProviderError),
    ):
        execute_source_index_scan(source_failure.pk)
    source_failure.refresh_from_db()
    assert source_failure.status == SourceIndexScan.Status.FAILED
    _assert_settlement(source_failure.quota_hold, consumed=0, released=1)

    negative_context = SharedSearchContext(
        official_name="额度验收主体",
        anchors=["额度验收主体"],
        products=[],
        keywords=[],
        self_domains=set(),
    )
    negative_success = create_negative_index_scan(user=user, subject_id=subject.pk)
    negative_payload = NegativeScanPayload(
        context=negative_context,
        records={},
        hits=[],
        provider_requests=1,
        provider_errors=0,
        raw_results=0,
        query_count=1,
        limit_reached=False,
        partial=False,
    )
    with (
        patch("apps.negative_index.services.BaiduSearchProvider"),
        patch("apps.negative_index.services.run_negative_search", return_value=negative_payload),
    ):
        assert execute_negative_index_scan(negative_success.pk)["status"] == "succeeded"
    _assert_settlement(negative_success.quota_hold, consumed=1, released=0)

    negative_failure = create_negative_index_scan(user=user, subject_id=subject.pk)
    with (
        patch("apps.negative_index.services.BaiduSearchProvider"),
        patch(
            "apps.negative_index.services.run_negative_search",
            side_effect=SearchProviderError("NEGATIVE_INDEX_TEST_FAILURE"),
        ),
        pytest.raises(SearchProviderError),
    ):
        execute_negative_index_scan(negative_failure.pk)
    negative_failure.refresh_from_db()
    assert negative_failure.status == NegativeIndexScan.Status.FAILED
    _assert_settlement(negative_failure.quota_hold, consumed=0, released=1)


def test_website_audit_consumes_on_success_and_releases_on_failure(settings):
    settings.WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS = 75
    settings.WEBSITE_AUDIT_MAX_PAGES = 20
    settings.WEBSITE_AUDIT_MAX_SITEMAPS = 5
    settings.WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS = 10_000
    _, user, _, subject, _, _ = _billable_facts("website_audits")
    success = create_website_audit(
        user=user,
        subject_id=subject.pk,
        url="https://example.com",
    )
    crawl = CrawlResult(root_url="https://example.com/", root_host="example.com")
    with (
        patch("apps.website_audits.services.crawl_website", return_value=crawl),
        patch("apps.website_audits.services.evaluate_deterministic_checks", return_value=[]),
    ):
        assert execute_website_audit(success.pk)["status"] == WebsiteAudit.Status.SUCCEEDED
    _assert_settlement(success.quota_hold, consumed=1, released=0)

    failure = create_website_audit(
        user=user,
        subject_id=subject.pk,
        url="https://example.com",
    )
    with (
        patch("apps.website_audits.services.crawl_website", side_effect=RuntimeError("test")),
        pytest.raises(RuntimeError),
    ):
        execute_website_audit(failure.pk)
    failure.refresh_from_db()
    assert failure.status == WebsiteAudit.Status.FAILED
    _assert_settlement(failure.quota_hold, consumed=0, released=1)


_TEXT_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.TEXT_GENERATION}),
    adapter_version="quota-acceptance-v1",
    prompt_version="quota-acceptance-v1",
)


def _text_response(content, *, request_id):
    return AIAdapterResponse(
        request_id=str(request_id),
        identity=_TEXT_DESCRIPTOR.identity,
        provider_request_id=f"provider-{uuid.uuid4().hex[:12]}",
        output=SimpleNamespace(content=content),
        usage=AIUsage(input_tokens=10, output_tokens=20, total_tokens=30),
    )


def _freeze_one(account, *, business_type: str, business_id, request_id):
    return freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type=business_type,
        business_id=business_id,
        idempotency_key=f"{business_type}-freeze-{business_id}",
        request_id=request_id,
    )


def _site_output():
    return {
        "tagline": "让企业信息更容易被理解",
        "pages": [
            {
                "key": key,
                "title": f"{key} 页面",
                "seo_title": f"{key} 页面标题",
                "seo_description": f"{key} 页面说明",
                "sections": [
                    {
                        "type": "text",
                        "title": "已确认资料",
                        "body": "本页面内容只使用已确认的主体资料。",
                        "items": [],
                    }
                ],
            }
            for key in PAGE_KEYS
        ],
    }


def _website_job(*, user, project, account):
    job_id = uuid.uuid4()
    request_id = uuid.uuid4()
    hold = _freeze_one(
        account,
        business_type="website_generation",
        business_id=job_id,
        request_id=request_id,
    )
    job = WebsiteGenerationJob.objects.create(
        id=job_id,
        user=user,
        project=project,
        quota_hold=hold,
        input_snapshot={"style_name": "专业商务", "source": {}},
        input_digest=uuid.uuid4().hex * 2,
        provider_key="deepseek",
        provider_model_id="deepseek-chat",
        adapter_version=_TEXT_DESCRIPTOR.adapter_version,
        prompt_version=_TEXT_DESCRIPTOR.prompt_version,
        idempotency_key_digest=uuid.uuid4().hex * 2,
        request_id=request_id,
    )
    return job, hold


def test_website_generation_consumes_on_success_and_releases_invalid_output():
    _, user, _, subject, version, accounts = _billable_facts(
        "website_generations",
        with_version=True,
    )
    project = WebsiteProject.objects.create(
        user=user,
        subject=subject,
        subject_version=version,
    )
    success, success_hold = _website_job(
        user=user,
        project=project,
        account=accounts["website_generations"],
    )
    adapter = SimpleNamespace(
        descriptor=_TEXT_DESCRIPTOR,
        invoke=lambda request: _text_response(_site_output(), request_id=request.request_id),
    )
    with (
        patch("apps.websites.services.DeepSeekWebsiteAdapter", return_value=adapter),
        patch(
            "apps.websites.services.get_capability_runtime_snapshot",
            return_value=SimpleNamespace(timeout_seconds=30),
        ),
    ):
        assert execute_generation_job(job_id=str(success.pk)) == {"status": "succeeded"}
    _assert_settlement(success_hold, consumed=1, released=0)

    failure, failure_hold = _website_job(
        user=user,
        project=project,
        account=accounts["website_generations"],
    )
    invalid_adapter = SimpleNamespace(
        descriptor=_TEXT_DESCRIPTOR,
        invoke=lambda request: _text_response({}, request_id=request.request_id),
    )
    with (
        patch("apps.websites.services.DeepSeekWebsiteAdapter", return_value=invalid_adapter),
        patch(
            "apps.websites.services.get_capability_runtime_snapshot",
            return_value=SimpleNamespace(timeout_seconds=30),
        ),
    ):
        assert execute_generation_job(job_id=str(failure.pk)) == {"status": "failed"}
    _assert_settlement(failure_hold, consumed=0, released=1)


def _video_output():
    return {
        "title": "三十秒认识企业服务",
        "hooks": ["服务到底怎么选？", "三十秒看懂核心价值", "先避开这三个误区"],
        "scenes": [
            {
                "visual": "主体名称与服务场景",
                "voiceover": "先从客户真正需要解决的问题讲起。",
                "subtitle": "从真实需求出发",
                "duration_seconds": 15,
            },
            {
                "visual": "展示已确认的服务资料",
                "voiceover": "所有内容都来自已经确认的主体资料。",
                "subtitle": "信息真实可核验",
                "duration_seconds": 15,
            },
        ],
        "full_voiceover": "先从客户真正需要解决的问题讲起，所有内容都来自已经确认的主体资料。",
        "cta": "查看完整服务资料。",
    }


def _video_job(*, user, subscription, subject, version, account):
    workspace = {
        "schema_version": VIDEO_SCRIPT_WORKSPACE_VERSION,
        "config": {"duration_seconds": 30},
        "source_snapshot": {},
        "script": None,
    }
    article = Article.objects.create(
        user=user,
        subject=subject,
        subject_version=version,
        custom_type=VIDEO_SCRIPT_CUSTOM_TYPE,
        title="额度验收视频脚本",
        content=json.dumps(workspace, ensure_ascii=False),
    )
    job_id = uuid.uuid4()
    request_id = uuid.uuid4()
    hold = _freeze_one(
        account,
        business_type="video_script_generation",
        business_id=job_id,
        request_id=request_id,
    )
    job = ArticleGenerationJob.objects.create(
        id=job_id,
        article=article,
        operation=ArticleGenerationJob.Operation.BODY,
        subscription=subscription,
        quota_hold=hold,
        source_pack_snapshot={},
        source_pack_digest=uuid.uuid4().hex * 2,
        input_snapshot={"config": {"duration_seconds": 30}},
        input_digest=uuid.uuid4().hex * 2,
        provider_key="deepseek",
        model_key="deepseek",
        provider_model_id="deepseek-chat",
        adapter_version=_TEXT_DESCRIPTOR.adapter_version,
        prompt_version=VIDEO_SCRIPT_PROMPT_VERSION,
        schema_version=VIDEO_SCRIPT_SCHEMA_VERSION,
        idempotency_key_digest=uuid.uuid4().hex * 2,
        request_digest=uuid.uuid4().hex * 2,
        request_id=request_id,
    )
    return job, hold


def test_video_script_consumes_on_success_and_releases_invalid_output():
    _, user, subscription, subject, version, accounts = _billable_facts(
        "video_script_generations",
        with_version=True,
    )
    success, success_hold = _video_job(
        user=user,
        subscription=subscription,
        subject=subject,
        version=version,
        account=accounts["video_script_generations"],
    )
    with patch(
        "apps.articles.video_services._invoke_video",
        return_value=_text_response(_video_output(), request_id=success.request_id),
    ):
        assert execute_video_generation_job(job_id=success.pk) == {"status": "succeeded"}
    _assert_settlement(success_hold, consumed=1, released=0)

    failure, failure_hold = _video_job(
        user=user,
        subscription=subscription,
        subject=subject,
        version=version,
        account=accounts["video_script_generations"],
    )
    with patch(
        "apps.articles.video_services._invoke_video",
        return_value=_text_response({}, request_id=failure.request_id),
    ):
        assert execute_video_generation_job(job_id=failure.pk) == {"status": "failed"}
    _assert_settlement(failure_hold, consumed=0, released=1)


@pytest.mark.parametrize(
    ("target_statuses", "expected_status", "settlement"),
    (
        ([PublicationTarget.Status.SUCCEEDED], Publication.Status.SUCCEEDED, "consume"),
        (
            [PublicationTarget.Status.SUCCEEDED, PublicationTarget.Status.FAILED],
            Publication.Status.PARTIAL,
            "consume",
        ),
        ([PublicationTarget.Status.FAILED], Publication.Status.FAILED, "release"),
        ([PublicationTarget.Status.PAUSED], Publication.Status.PAUSED, None),
    ),
)
def test_auto_publish_settles_once_only_for_a_real_public_result(
    target_statuses,
    expected_status,
    settlement,
):
    publication = SimpleNamespace(
        pk=uuid.uuid4(),
        quota_hold_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        status=Publication.Status.QUEUED,
        targets=SimpleNamespace(
            values_list=lambda *args: [(status, "") for status in target_statuses]
        ),
        save=lambda **kwargs: None,
    )
    with (
        patch(
            "apps.publishing.publication_state.Publication.objects.select_for_update"
        ) as locked,
        patch("apps.publishing.publication_state.consume_hold") as consume,
        patch("apps.publishing.publication_state.release_hold") as release,
    ):
        locked.return_value.get.return_value = publication
        result = aggregate_publication(publication.pk)

    assert result == expected_status
    assert publication.status == expected_status
    assert consume.call_count == (1 if settlement == "consume" else 0)
    assert release.call_count == (1 if settlement == "release" else 0)
