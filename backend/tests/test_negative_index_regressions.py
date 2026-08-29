from __future__ import annotations

import inspect
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from apps.negative_index.models import NegativeIndexScan
from apps.negative_index.services import _start_scan
from apps.search_discovery.provider import BaiduSearchProvider
from apps.subjects.models import Subject, SubjectType


class NegativeIndexRegressionTests(SimpleTestCase):
    def test_start_scan_does_not_join_nullable_current_version_under_lock(self):
        source = inspect.getsource(_start_scan)
        self.assertIn('select_related("subject")', source)
        self.assertNotIn('select_related("subject", "subject__current_version")', source)

    @override_settings(SEARCH_DISCOVERY_CACHE_TTL_SECONDS=0)
    @patch("apps.search_discovery.provider.CanonicalBaiduSearchProvider")
    def test_negative_search_reuses_canonical_source_index_provider(self, provider_class):
        upstream = Mock()
        upstream.search.return_value = []
        provider_class.return_value = upstream

        provider = BaiduSearchProvider()
        try:
            result = provider.search("测试主体 投诉")
        finally:
            provider.close()

        self.assertEqual(result, [])
        provider_class.assert_called_once_with()
        upstream.search.assert_called_once_with(
            "测试主体 投诉",
            start_date=None,
            end_date=None,
        )
        upstream.close.assert_called_once_with()


class NegativeIndexDatabaseLockTests(TestCase):
    def test_start_scan_accepts_subject_without_current_version(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            phone="13800138201",
            password="StrongPass123!",
            nickname="NegativeLock",
        )
        subject_type = SubjectType.objects.get(key="enterprise")
        subject = Subject.objects.create(
            user=user,
            subject_type=subject_type,
            status=Subject.Status.ACTIVE,
            draft_values={},
            schema_version=1,
            schema_snapshot={},
            schema_digest="negative-lock-regression",
        )
        self.assertIsNone(subject.current_version_id)
        scan = NegativeIndexScan.objects.create(user=user, subject=subject)

        locked = _start_scan(scan.id)

        self.assertEqual(locked.status, NegativeIndexScan.Status.RUNNING)
        self.assertEqual(locked.subject_id, subject.id)
