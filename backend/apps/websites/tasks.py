from celery import shared_task  # type: ignore[import-untyped]

from .services import execute_generation_job


@shared_task(name="websites.execute_generation_job", ignore_result=True)
def execute_website_generation_task(job_id: str):
    return execute_generation_job(job_id=job_id)
