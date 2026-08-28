from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.ai.errors import AIAdapterError
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .design import (
    WebsiteDesignConflict,
    apply_project_design,
    content_style_key,
    design_options_payload,
    project_design_payload,
    project_for_subject,
    recommend_design,
)
from .serializers import WebsiteDesignSerializer, WebsiteGenerateSerializer
from .services import (
    WebsiteInputError,
    create_generation_job,
    job_payload,
    project_payload,
    website_job_for_user,
    website_state,
)


def _project_payload_with_design(project):
    data = project_payload(project)
    data.update(project_design_payload(project))
    return data


class SubjectWebsiteView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        data = website_state(user=request.user, subject_id=subject_id)
        data["design_options"] = design_options_payload()
        data["recommendation"] = recommend_design(user=request.user, subject_id=subject_id)
        if data["project"] is not None:
            project = project_for_subject(user=request.user, subject_id=subject_id)
            data["project"].update(project_design_payload(project))
        return Response(data)


class SubjectWebsiteGenerateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, subject_id):
        serializer = WebsiteGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        selected_style = serializer.validated_data["style_key"]
        try:
            project, job, created = create_generation_job(
                user=request.user,
                subject_id=subject_id,
                style_key=content_style_key(selected_style),
                image_asset_ids=list(serializer.validated_data["image_asset_ids"]),
                document_ids=list(serializer.validated_data["document_ids"]),
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=getattr(request, "request_id", None),
            )
            project = apply_project_design(
                project=project,
                style_key=selected_style,
                theme_key=serializer.validated_data["theme_key"],
                density_key=serializer.validated_data["density_key"],
            )
        except WebsiteInputError as exc:
            raise ValidationError({"website": [str(exc)]}) from exc
        except WebsiteDesignConflict as exc:
            raise ValidationError({"website": [str(exc)]}) from exc
        except AIAdapterError as exc:
            raise ValidationError({"website": ["当前内容生成服务暂不可用，请稍后再试"]}) from exc
        return Response(
            {"project": _project_payload_with_design(project), "job": job_payload(job)},
            status=HTTP_202_ACCEPTED if created else HTTP_200_OK,
        )


class SubjectWebsiteDesignView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def patch(self, request, subject_id):
        serializer = WebsiteDesignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            project = project_for_subject(user=request.user, subject_id=subject_id)
            project = apply_project_design(
                project=project,
                style_key=serializer.validated_data["style_key"],
                theme_key=serializer.validated_data["theme_key"],
                density_key=serializer.validated_data["density_key"],
                expected_version=serializer.validated_data["expected_version"],
            )
        except WebsiteDesignConflict as exc:
            raise ValidationError({"website": [str(exc)]}) from exc
        return Response({"project": _project_payload_with_design(project)})


class WebsiteGenerationJobView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        job = website_job_for_user(user=request.user, job_id=job_id)
        return Response(
            {"job": job_payload(job), "project": _project_payload_with_design(job.project)}
        )
