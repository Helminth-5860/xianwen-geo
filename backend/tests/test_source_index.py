from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.source_index.models import SourceIndexHit, SourceIndexItem, SourceIndexScan
from apps.source_index.provider import (
    BaiduSearchProvider,
    baidu_query_units,
    truncate_baidu_query,
)
from apps.source_index.scanner import (
    SearchTask,
    SubjectSearchContext,
    _expand_task,
    build_initial_queries,
)
from apps.source_index.scoring import (
    calculate_index,
    classify_source,
    freshness_score,
    normalize_url,
    relevance_score,
    source_weight,
    visibility_score,
)
from apps.subjects.models import Subject, SubjectType


class SourceScoringTests(SimpleTestCase):
    def test_url_normalization_removes_tracking_but_preserves_semantic_query(self):
        normalized = normalize_url("http://Example.COM/a/?utm_source=x&id=42&fbclid=abc#section")
        self.assertIsNotNone(normalized)
        url, domain, root = normalized
        self.assertEqual(url, "https://example.com/a?id=42")
        self.assertEqual(domain, "example.com")
        self.assertEqual(root, "example.com")

    def test_cn_root_domain(self):
        normalized = normalize_url("https://news.example.com.cn/a")
        self.assertEqual(normalized[2], "example.com.cn")

    def test_known_news_domain_gets_high_authority(self):
        source_type, authority = classify_source(
            root="xinhuanet.com",
            domain="www.xinhuanet.com",
            website="新华网",
            title="企业新闻",
            self_domains=set(),
        )
        self.assertEqual(source_type, SourceIndexItem.SourceType.NEWS_MEDIA)
        self.assertGreaterEqual(authority, 95)

    def test_relevance_prefers_official_name_in_title(self):
        score = relevance_score(
            title="广州显问网络科技有限公司发布新品",
            snippet="",
            website="某媒体",
            anchors=["显问"],
            official_name="广州显问网络科技有限公司",
            matched_queries={"广州显问网络科技有限公司"},
        )
        self.assertEqual(score, 100)

    def test_source_weight_is_deterministic(self):
        self.assertEqual(
            source_weight(authority=80, relevance=90, visibility=85, freshness=70),
            Decimal("82.50"),
        )

    def test_visibility_buckets(self):
        self.assertEqual(visibility_score(1), 100)
        self.assertEqual(visibility_score(10), 85)
        self.assertEqual(visibility_score(51), 40)

    def test_unknown_date_is_neutral_not_zero(self):
        self.assertEqual(freshness_score(None), 50)
        self.assertEqual(freshness_score(timezone.now() - timedelta(days=5)), 100)

    def test_index_rewards_exposure_and_diversity_but_caps_at_100(self):
        rows = [
            {
                "root_domain": f"site{i}.cn",
                "authority_score": 80,
                "visibility_score": 85,
                "freshness_score": 70,
            }
            for i in range(100)
        ]
        score, factors = calculate_index(rows)
        self.assertGreater(score, 60)
        self.assertLessEqual(score, 100)
        self.assertEqual(factors["diversity"], 100.0)


@override_settings(
    BAIDU_SEARCH_API_KEY="test-key",
    BAIDU_SEARCH_AUTH_HEADER="Authorization",
    SOURCE_INDEX_REQUEST_TIMEOUT_SECONDS=5,
)
class BaiduProviderTests(SimpleTestCase):
    def test_query_limit_counts_chinese_as_two_units(self):
        query = "显" * 40
        truncated = truncate_baidu_query(query)
        self.assertLessEqual(baidu_query_units(truncated), 72)
        self.assertEqual(len(truncated), 36)

    def test_search_uses_metadata_only_contract(self):
        provider = BaiduSearchProvider()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "references": [
                {
                    "id": 1,
                    "type": "web",
                    "title": "显问 GEO 报道",
                    "url": "https://example.com/article",
                    "website": "示例媒体",
                    "snippet": "显问相关公开摘要",
                    "date": "2026-08-20 10:00:00",
                }
            ]
        }
        provider.client.post = Mock(return_value=response)
        try:
            results = provider.search("显问 GEO")
            request_kwargs = provider.client.post.call_args.kwargs
        finally:
            provider.close()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "显问 GEO 报道")
        self.assertEqual(
            request_kwargs["json"]["resource_type_filter"],
            [{"type": "web", "top_k": 50}],
        )
        self.assertNotIn("url", request_kwargs["json"])

    def test_search_uses_provider_date_range_filter(self):
        provider = BaiduSearchProvider()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"references": []}
        provider.client.post = Mock(return_value=response)
        try:
            provider.search(
                "显问 GEO",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
            )
            request_kwargs = provider.client.post.call_args.kwargs
        finally:
            provider.close()
        self.assertEqual(
            request_kwargs["json"]["search_filter"],
            {"range": {"page_time": {"gte": "2026-07-01", "lte": "2026-07-31"}}},
        )


class SourceScannerTests(SimpleTestCase):
    def test_queries_remain_subject_anchored(self):
        context = SubjectSearchContext(
            official_name="广州显问网络科技有限公司",
            anchors=["广州显问网络科技有限公司", "显问"],
            products=["GEO智能体"],
            keywords=["GEO优化", "AI搜索优化"],
            self_domains=set(),
        )
        queries = build_initial_queries(context)
        self.assertLessEqual(len(queries), 12)
        self.assertIn("广州显问网络科技有限公司", queries)
        self.assertTrue(all("显问" in query for query in queries))
        self.assertNotIn("GEO优化", queries)

    def test_unbounded_saturated_branch_expands_to_non_overlapping_date_windows(self):
        tasks = list(_expand_task(SearchTask("显问")))
        self.assertGreaterEqual(len(tasks), 4)
        ordered = sorted(tasks, key=lambda task: task.range_start)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            self.assertLess(previous.range_end, current.range_start)

    def test_bounded_branch_splits_in_half(self):
        tasks = list(
            _expand_task(
                SearchTask(
                    "显问",
                    date(2025, 1, 1),
                    date(2025, 12, 31),
                    1,
                )
            )
        )
        self.assertEqual(len(tasks), 2)
        self.assertLess(tasks[0].range_end, tasks[1].range_start)


class SourceIndexApiIsolationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user_a = user_model.objects.create_user(
            phone="13800138001",
            password="StrongPass123!",
            nickname="A",
        )
        self.user_b = user_model.objects.create_user(
            phone="13800138002",
            password="StrongPass123!",
            nickname="B",
        )
        subject_type = SubjectType.objects.create(key="company-source-index-test", name="企业")
        self.subject = Subject.objects.create(
            user=self.user_a,
            subject_type=subject_type,
            status=Subject.Status.ACTIVE,
            draft_values={},
            schema_version=1,
            schema_snapshot={},
            schema_digest="source-index-test-digest",
        )
        self.scan = SourceIndexScan.objects.create(user=self.user_a, subject=self.subject)
        self.client = APIClient()

    def test_other_user_cannot_read_scan(self):
        self.client.force_authenticate(self.user_b)
        response = self.client.get(f"/api/v1/source-index/scans/{self.scan.id}/")
        self.assertEqual(response.status_code, 404)

    def test_subject_summary_is_scoped_to_owner(self):
        self.client.force_authenticate(self.user_b)
        response = self.client.get(f"/api/v1/subjects/{self.subject.id}/source-index/")
        self.assertEqual(response.status_code, 404)

    def test_time_slice_rank_is_not_exposed_as_global_query_rank(self):
        self.scan.status = SourceIndexScan.Status.SUCCEEDED
        self.scan.stage = SourceIndexScan.Stage.COMPLETED
        self.scan.index_score = Decimal("60.00")
        self.scan.finished_at = timezone.now()
        self.scan.save()
        item = SourceIndexItem.objects.create(
            scan=self.scan,
            original_url="https://example.com/report",
            normalized_url="https://example.com/report",
            domain="example.com",
            root_domain="example.com",
            website="示例媒体",
            title="显问 GEO 报道",
            snippet="显问 GEO 公开信源",
            source_type=SourceIndexItem.SourceType.NEWS_MEDIA,
            authority_score=80,
            relevance_score=90,
            visibility_score=40,
            freshness_score=70,
            source_weight=Decimal("72.50"),
            best_rank=51,
        )
        SourceIndexHit.objects.create(
            scan=self.scan,
            item=item,
            query="显问 GEO",
            rank=1,
            range_start=date(2026, 7, 1),
            range_end=date(2026, 7, 31),
        )
        self.client.force_authenticate(self.user_a)
        response = self.client.get(f"/api/v1/subjects/{self.subject.id}/source-index/")
        self.assertEqual(response.status_code, 200)
        coverage = response.json()["latest_result"]["query_coverage"]
        self.assertEqual(len(coverage), 1)
        self.assertIsNone(coverage[0]["best_rank"])

    @patch("apps.source_index.views.execute_source_index_scan_task.apply_async")
    def test_duplicate_running_scan_is_rejected(self, apply_async):
        self.client.force_authenticate(self.user_a)
        response = self.client.post(
            f"/api/v1/subjects/{self.subject.id}/source-index/scans/",
            {},
        )
        self.assertEqual(response.status_code, 409)
        apply_async.assert_not_called()
