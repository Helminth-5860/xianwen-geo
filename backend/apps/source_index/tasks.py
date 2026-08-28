from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
from celery import shared_task  # type: ignore[import-untyped]

from .provider import SearchProviderError
from .services import execute_source_index_scan, fail_source_index_scan


@shared_task(
    name="source_index.execute",
    soft_time_limit=300,
    time_limit=320,
)
def execute_source_index_scan_task(scan_id):
    try:
        return execute_source_index_scan(scan_id)
    except SoftTimeLimitExceeded:
        fail_source_index_scan(scan_id, "SOURCE_INDEX_TIMEOUT")
        raise
    except SearchProviderError as exc:
        # Search-provider retry behavior is handled inside the bounded scanner so a Celery retry
        # cannot accidentally start a second full paid scan.
        fail_source_index_scan(scan_id, exc.code)
        raise
    except Exception:
        fail_source_index_scan(scan_id)
        raise
