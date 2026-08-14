"""Celery autodiscovery entry point for subject tasks."""

from .enrichment_tasks import dispatch_enrichment_jobs, execute_enrichment_task

__all__ = ("dispatch_enrichment_jobs", "execute_enrichment_task")
