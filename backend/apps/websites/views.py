from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.ai.errors import AIAdapterError

from .serializers import WebsiteGenerateSerializer
from .services import (
    WebsiteInputError,
    create_generation_job,
    job_payload,
    project_payload,
    website_job_for_user,
    website_state,
)


class SubjectWebsiteView(APIView):
    def get(self, request, subject_id):
        return Response(website_state(user=request.user, subject_id=subject_id))


class SubjectWebsiteGenerateView(APIView):
    def post(self, request, subject_id):
        serializer = WebsiteGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            project, job, created = create_generation_job(
                user=request.user,
                subject_id=subject_id,
                style_key=serializer.validated_data["style_key"],
                image_asset_ids=list(serializer.validated_data["image_asset_ids"]),
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=getattr(request, "request_id", None),
            )
        except WebsiteInputError as exc:
            raise ValidationError({"website": [str(exc)]}) from exc
        except AIAdapterError as exc:
            raise ValidationError({"website": ["当前内容生成服务暂不可用，请稍后再试"]}) from exc
        return Response(
            {"project": project_payload(project), "job": job_payload(job)},
            status=HTTP_202_ACCEPTED if created else HTTP_200_OK,
        )


class WebsiteGenerationJobView(APIView):
    def get(self, request, job_id):
        job = website_job_for_user(user=request.user, job_id=job_id)
        return Response({"job": job_payload(job), "project": project_payload(job.project)})
