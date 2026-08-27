from celery import shared_task  # type: ignore[import-untyped]

from .services import execute_generation_job
from .video_services import execute_video_generation_job


@shared_task(name="articles.execute_generation_job", ignore_result=True)
def execute_generation_job_task(job_id: str):
    return execute_generation_job(job_id=job_id)


@shared_task(name="articles.execute_video_script_job", ignore_result=True)
def execute_video_script_job_task(job_id: str):
    return execute_video_generation_job(job_id=job_id)
