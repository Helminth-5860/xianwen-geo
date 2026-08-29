from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.negative_index.classifier import (
    AnalysisBatchResult,
    CandidateAnalysis,
    fallback_analysis,
    rule_signal,
)
from apps.negative_index.clustering import build_event, cluster_items
from apps.negative_index.models import NegativeEvent, NegativeIndexScan
from apps.negative_index.queries import build_negative_queries
from apps.negative_index.scanner import NegativeScanPayload
from apps.negative_index.scoring import calculate_negative_index, event_risk
from apps.negative_index.services import execute_negative_index_scan
from apps.search_discovery.subject_context import SubjectSearchContext
from apps.subjects.models import Subject, SubjectType


class NegativeIndexRuleTests(SimpleTestCase):
    def test_negative_queries_are_subject_anchored_and_bounded(self):
        context = SubjectSearchContext(
            official_name="广州显问网络科技有限公司",
            anchors=["广州显问网络科技有限公司", "显问"],
            products=["GEO智能体"],
            keywords=[],
            self_domains=set(),
        )
        queries = build_negative_queries(context, max_queries=12)
        self.assertLessEqual(len(queries), 12)
        self.assertGreaterEqual(len(queries), 8)
        self.assertTrue(all("显问" in query for query in queries))
        self.assertTrue(any("投诉" in query for query in queries))
        self.assertTrue(any("处罚" in query for query in queries))

    def test_rebuttal_is_not_promoted_to_misconduct(self):
        signal = rule_signal(
            "显问回应诈骗传闻：相关内容严重失实",
            "公司发布澄清声明并否认相关指控",
        )
        self.assertTrue(signal.rebuttal)
        fallback = fallback_analysis(
            title="显问回应诈骗传闻：相关内容严重失实",
            snippet="公司发布澄清声明",
            source_type="news_media",
            authority=85,
            signal=signal,
        )
        self.assertEqual(
            fallback.claim_type,
            NegativeEvent.ClaimType.REBUTTAL,
        )
        self.assertLess(fallback.negative_confidence, 10)

    def test_official_formal_signal_has_safe_fallback_when_ai_unavailable(self):
        signal = rule_signal(
            "市场监督管理局对某公司作出行政处罚",
            "因违法行为罚款并责令整改",
        )
        fallback = fallback_analysis(
            title="市场监督管理局对某公司作出行政处罚",
            snippet="因违法行为罚款并责令整改",
            source_type="government_association",
            authority=98,
            signal=signal,
        )
        self.assertEqual(
            fallback.claim_type,
            NegativeEvent.ClaimType.OFFICIAL_FINDING,
        )
        self.assertEqual(
            fallback.event_status,
            NegativeEvent.Status.CONFIRMED,
        )
        self.assertGreaterEqual(fallback.evidence_confidence, 90)


class NegativeIndexScoringTests(SimpleTestCase):
    def test_retracted_event_has_zero_risk(self):
        self.assertEqual(
            event_risk(
                severity=100,
                evidence=100,
                visibility=100,
                freshness=100,
                status=NegativeEvent.Status.RETRACTED,
            ),
            Decimal("0.00"),
        )

    def test_one_high_confidence_event_can_drive_high_index(self):
        risk = event_risk(
            severity=95,
            evidence=100,
            visibility=95,
            freshness=100,
            status=NegativeEvent.Status.CONFIRMED,
        )
        score, _factors = calculate_negative_index(
            [
                {
                    "current_risk": risk,
                    "evidence_score": 100,
                    "visibility_score": 95,
                    "last_seen_at": timezone.now(),
                }
            ]
        )
        self.assertGreater(score, 60)

    def test_many_low_risk_items_do_not_saturate_index(self):
        events = [
            {
                "current_risk": Decimal("10.00"),
                "evidence_score": 20,
                "visibility_score": 20,
                "last_seen_at": timezone.now(),
            }
            for _ in range(20)
        ]
        score, _factors = calculate_negative_index(events)
        self.assertLess(score, 40)

    def test_similar_reposts_cluster_as_one_event(self):
        now = timezone.now()
        common = {
            "category": NegativeEvent.Category.REGULATORY,
            "claim_type": NegativeEvent.ClaimType.OFFICIAL_FINDING,
            "event_status": NegativeEvent.Status.CONFIRMED,
            "severity_score": 75,
            "evidence_confidence": 95,
            "authority_score": 90,
            "visibility_score": 85,
            "freshness_score": 100,
            "published_at": now,
            "root_domain": "example.com",
            "ai_summary": "监管部门作出行政处罚。",
        }
        rows = [
            {
                **common,
                "title": "某公司因虚假宣传被处罚50万元",
                "event_title": "某公司虚假宣传行政处罚",
            },
            {
                **common,
                "title": "监管部门处罚某公司虚假宣传行为",
                "event_title": "某公司虚假宣传行政处罚",
                "root_domain": "example.cn",
            },
        ]
        clusters = cluster_items(rows)
        self.assertEqual(len(clusters), 1)
        event = build_event(clusters[0])
        self.assertEqual(event["source_count"], 2)
        self.assertEqual(event["independent_domain_count"], 2)

    def test_event_claim_type_comes_from_strongest_evidence(self):
        now = timezone.now()
        rows = [
            {
                "category": NegativeEvent.Category.REGULATORY,
                "claim_type": NegativeEvent.ClaimType.USER_ALLEGATION,
                "event_status": NegativeEvent.Status.REPORTED,
                "severity_score": 95,
                "evidence_confidence": 35,
                "authority_score": 45,
                "visibility_score": 90,
                "freshness_score": 100,
                "published_at": now,
                "root_domain": "forum.example",
                "title": "网友称某公司虚假宣传被重罚",
                "event_title": "某公司虚假宣传行政处罚",
                "ai_summary": "用户提出高严重度指控。",
            },
            {
                "category": NegativeEvent.Category.REGULATORY,
                "claim_type": NegativeEvent.ClaimType.OFFICIAL_FINDING,
                "event_status": NegativeEvent.Status.CONFIRMED,
                "severity_score": 70,
                "evidence_confidence": 99,
                "authority_score": 98,
                "visibility_score": 70,
                "freshness_score": 100,
                "published_at": now,
                "root_domain": "example.gov.cn",
                "title": "监管部门公布某公司行政处罚决定",
                "event_title": "某公司虚假宣传行政处罚",
                "ai_summary": "监管部门公布正式处罚决定。",
            },
        ]
        clusters = cluster_items(rows)
        self.assertEqual(len(clusters), 1)
        event = build_event(clusters[0])
        self.assertEqual(
            event["claim_type"],
            NegativeEvent.ClaimType.OFFICIAL_FINDING,
        )
        self.assertEqual(event["status"], NegativeEvent.Status.CONFIRMED)
        self.assertEqual(event["summary"], "监管部门公布正式处罚决定。")


class NegativeIndexApiIsolationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user_a = user_model.objects.create_user(
            phone="13800138101",
            password="StrongPass123!",
            nickname="A",
        )
        self.user_b = user_model.objects.create_user(
            phone="13800138102",
            password="StrongPass123!",
            nickname="B",
        )
        subject_type = SubjectType.objects.create(
            key="company-negative-index-test",
            name="企业",
        )
        self.subject = Subject.objects.create(
            user=self.user_a,
            subject_type=subject_type,
            status=Subject.Status.ACTIVE,
            draft_values={},
            schema_version=1,
            schema_snapshot={},
            schema_digest="negative-index-test-digest",
        )
        self.scan = NegativeIndexScan.objects.create(
            user=self.user_a,
            subject=self.subject,
        )
        self.client = APIClient()

    def test_other_user_cannot_read_scan(self):
        self.client.force_authenticate(self.user_b)
        response = self.client.get(
            f"/api/v1/negative-index/scans/{self.scan.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_subject_summary_is_scoped_to_owner(self):
        self.client.force_authenticate(self.user_b)
        response = self.client.get(
            f"/api/v1/subjects/{self.subject.id}/negative-index/"
        )
        self.assertEqual(response.status_code, 404)

    @patch("apps.negative_index.views.execute_negative_index_scan_task.apply_async")
    def test_duplicate_running_scan_is_rejected(self, apply_async):
        self.client.force_authenticate(self.user_a)
        response = self.client.post(
            f"/api/v1/subjects/{self.subject.id}/negative-index/scans/",
            {},
        )
        self.assertEqual(response.status_code, 409)
        apply_async.assert_not_called()


@override_settings(
    NEGATIVE_INDEX_MIN_RELEVANCE_SCORE=60,
    NEGATIVE_INDEX_MIN_RULE_SIGNAL_SCORE=20,
    NEGATIVE_INDEX_MAX_AI_CANDIDATES=20,
    NEGATIVE_INDEX_AI_BATCH_SIZE=10,
    NEGATIVE_INDEX_MAX_VERIFICATIONS=2,
    NEGATIVE_INDEX_MIN_NEGATIVE_CONFIDENCE=60,
)
class NegativeIndexPipelineTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            phone="13800138103",
            password="StrongPass123!",
            nickname="Pipeline",
        )
        subject_type = SubjectType.objects.create(
            key="company-negative-pipeline",
            name="企业",
        )
        self.subject = Subject.objects.create(
            user=self.user,
            subject_type=subject_type,
            status=Subject.Status.ACTIVE,
            draft_values={},
            schema_version=1,
            schema_snapshot={},
            schema_digest="negative-pipeline-digest",
        )
        self.scan = NegativeIndexScan.objects.create(
            user=self.user,
            subject=self.subject,
        )

    @patch("apps.negative_index.services.analyze_candidates")
    @patch("apps.negative_index.services.run_negative_search")
    @patch("apps.negative_index.services.BaiduSearchProvider")
    def test_pipeline_persists_one_confirmed_event(
        self,
        provider_class,
        run_search,
        analyze,
    ):
        provider_class.return_value.__enter__.return_value = Mock()
        context = SubjectSearchContext(
            official_name="测试科技有限公司",
            anchors=["测试科技有限公司", "测试科技"],
            products=[],
            keywords=[],
            self_domains=set(),
        )
        run_search.return_value = NegativeScanPayload(
            context=context,
            records={
                "https://example.gov.cn/notice/1": {
                    "original_url": "https://example.gov.cn/notice/1",
                    "normalized_url": "https://example.gov.cn/notice/1",
                    "domain": "example.gov.cn",
                    "root_domain": "example.gov.cn",
                    "website": "市场监督管理局",
                    "title": "测试科技有限公司因虚假宣传被行政处罚",
                    "snippet": "市场监督管理局决定罚款并责令整改。",
                    "published_at": timezone.now(),
                    "best_rank": 1,
                    "matched_queries": {
                        "测试科技有限公司 处罚 违法 监管"
                    },
                }
            },
            hits=[
                {
                    "normalized_url": "https://example.gov.cn/notice/1",
                    "query": "测试科技有限公司 处罚 违法 监管",
                    "rank": 1,
                    "range_start": None,
                    "range_end": None,
                }
            ],
            provider_requests=1,
            provider_errors=0,
            raw_results=1,
            query_count=1,
            limit_reached=False,
            partial=False,
        )
        analyze.return_value = AnalysisBatchResult(
            analyses={
                "c1": CandidateAnalysis(
                    subject_relevance=100,
                    negative_confidence=100,
                    category=NegativeEvent.Category.REGULATORY,
                    severity=78,
                    claim_type=NegativeEvent.ClaimType.OFFICIAL_FINDING,
                    evidence_confidence=98,
                    event_status=NegativeEvent.Status.CONFIRMED,
                    event_title="虚假宣传行政处罚",
                    summary="监管部门对主体作出行政处罚。",
                )
            },
            provider_key="deepseek",
            model_key="deepseek",
            provider_model_id="test-model",
        )
        result = execute_negative_index_scan(self.scan.id)
        self.scan.refresh_from_db()
        self.assertEqual(result["status"], NegativeIndexScan.Status.SUCCEEDED)
        self.assertEqual(self.scan.event_count, 1)
        self.assertEqual(self.scan.negative_item_count, 1)
        self.assertGreater(self.scan.index_score, 0)
        event = self.scan.events.get()
        self.assertEqual(event.status, NegativeEvent.Status.CONFIRMED)
        self.assertEqual(event.source_count, 1)
