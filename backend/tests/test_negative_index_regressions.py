from __future__ import annotations

import inspect
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from apps.negative_index.services import _start_scan
from apps.search_discovery.provider import BaiduSearchProvider


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
