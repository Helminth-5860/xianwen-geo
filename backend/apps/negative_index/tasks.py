from billiard.exceptions import SoftTimeLimitExceeded
from celery import shared_task  # type: ignore[import-untyped]

from apps.search_discovery.provider import SearchProviderError

from .services import execute_negative_index_scan, fail_negative_index_scan


@shared_task(name="negative_index.execute", soft_time_limit=300, time_limit=320)
def execute_negative_index_scan_task(scan_id):
    try:
        return execute_negative_index_scan(scan_id)
    except SoftTimeLimitExceeded:
        fail_negative_index_scan(scan_id, "NEGATIVE_INDEX_TIMEOUT")
        raise
    except SearchProviderError as exc:
        fail_negative_index_scan(scan_id, exc.code)
        raise
    except Exception:
        fail_negative_index_scan(scan_id)
        raise
