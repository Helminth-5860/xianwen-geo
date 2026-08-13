import hashlib
import io
import uuid
from datetime import time, timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.models import DocumentVersion, UserDocument
from apps.documents.ocr import MockOcrProvider
from apps.documents.parse_exceptions import (
    DocumentOcrUnavailable,
    DocumentParseContentInvalid,
    DocumentParseSecurityRejected,
    DocumentParseStateConflict,
    DocumentParseUnexpectedError,
    DocumentParseVersionConflict,
)
from apps.documents.parse_models import (
    DocumentParsedVersion,
    DocumentParseEvent,
    DocumentParseJob,
    DocumentParseState,
)
from apps.documents.parse_services import (
    confirm_parsed_text,
    create_parse_job,
    due_parse_job_ids,
    execute_parse,
    get_confirmed_document_content,
)
from apps.documents.parsers import canonicalize_text, parse_stream
from apps.documents.storage import MockStorageProvider, ObjectMetadata
from apps.documents.tasks import execute_parse_job
from apps.plans.models import Plan, PlanVersion, Subscription
from apps.subjects.models import Subject, SubjectType
from apps.users.models import Notification, User

pytestmark = pytest.mark.django_db


def _facts(
    *,
    kind="txt",
    data=b"data",
    with_subscription=True,
    account_status=User.AccountStatus.ACTIVE,
):
    suffix = uuid.uuid4().hex[:10]
    user = User.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="Parser user",
        password="correct-test-password",
        approval_status=User.ApprovalStatus.APPROVED,
        account_status=account_status,
    )
    subject_type = SubjectType.objects.create(
        key=f"parse-{suffix}", name="Parse type", schema_version=1
    )
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.DRAFT,
        draft_values={"name": "Parser subject"},
        schema_version=1,
        schema_snapshot_format_version=1,
        schema_snapshot={"fields": []},
        schema_digest="a" * 64,
    )
    now = timezone.now()
    if with_subscription:
        plan = Plan.objects.create(
            code=f"parse-{suffix}",
            name="Parse plan",
            price_display_mode=Plan.PriceDisplayMode.CONTACT,
            is_trial=True,
            status=Plan.Status.PUBLISHED,
        )
        plan_version = PlanVersion.objects.create(
            plan=plan,
            version_no=1,
            status=PlanVersion.Status.PUBLISHED,
            valid_days=30,
            queue_priority=1,
            effective_config={"limits": {}},
            config_digest="b" * 64,
            snapshot_generated_at=now,
            published_at=now,
        )
        Subscription.objects.create(
            user=user,
            source_type=Subscription.SourceType.TRIAL_GRANT,
            plan=plan,
            plan_version=plan_version,
            plan_version_no=1,
            entitlement_snapshot={"limits": {}},
            entitlement_digest="c" * 64,
            status=Subscription.Status.ACTIVE,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=10),
            cycle_anchor_day=now.day,
            cycle_anchor_time=time(0, 0),
            is_trial=True,
            activated_at=now,
            request_id=uuid.uuid4(),
        )
    document = UserDocument.objects.create(
        user=user,
        subject=subject,
        purpose="subject_library",
        display_name="private-file",
    )
    version = DocumentVersion.objects.create(
        document=document,
        version_no=1,
        object_key=f"objects/{uuid.uuid4().hex}/{uuid.uuid4().hex}",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        detected_file_kind=kind,
        detected_mime={
            "txt": "text/plain",
            "markdown": "text/plain",
            "pdf": "application/pdf",
        }.get(kind, "image/png"),
        scanner_engine_version="mock-v1",
    )
    UserDocument.objects.filter(pk=document.pk).update(current_version=version)
    document.current_version = version
    return user, subject, document, version


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_canonical_text_is_minimal_and_rejects_controls():
    assert canonicalize_text("a\r\nb\rc  d") == "a\nb\nc  d"
    with pytest.raises(DocumentParseContentInvalid):
        canonicalize_text("bad\x00text")
    with pytest.raises(DocumentParseContentInvalid):
        canonicalize_text("bad\x01text")


def test_txt_markdown_are_plain_and_image_uses_explicit_ocr():
    text = parse_stream("markdown", io.BytesIO(b"# title\n<script>x</script>"), None)
    assert text.canonical_text == "# title\n<script>x</script>"
    image = parse_stream("png", io.BytesIO(b"not-logged"), MockOcrProvider())
    assert image.parser_key == "image_ocr"
    assert image.ocr_engine_version == "mock-v1"


def test_docx_and_xlsx_security_preflight_rejects_external_or_embedded_parts():
    import zipfile

    for name, kind in (
        ("word/embeddings/object.bin", "docx"),
        ("xl/externalLinks/link.xml", "xlsx"),
    ):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", b"<Types/>")
            archive.writestr(name, b"unsafe")
        output.seek(0)
        with pytest.raises(DocumentParseSecurityRejected):
            parse_stream(kind, output, None)


@override_settings(ROOT_URLCONF="config.urls", DOCUMENT_OCR_PROVIDER="unavailable")
def test_image_ocr_unavailable_returns_503_and_creates_no_job():
    user, _, document, version = _facts(kind="png")
    response = _client(user).post(
        f"/api/v1/documents/{document.pk}/parse",
        {"document_version_id": str(version.pk)},
        format="json",
        HTTP_IDEMPOTENCY_KEY="image-parse-test-key-0001",
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DOCUMENT_OCR_UNAVAILABLE"
    assert not DocumentParseJob.objects.exists()


@override_settings(ROOT_URLCONF="config.urls")
def test_parse_payload_is_strict_and_requires_subscription():
    user, _, document, version = _facts(with_subscription=False)
    response = _client(user).post(
        f"/api/v1/documents/{document.pk}/parse",
        {"document_version_id": str(version.pk), "parser_key": "txt"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="strict-parse-test-key-0001",
    )
    assert response.status_code == 422
    assert not DocumentParseJob.objects.exists()
    response = _client(user).post(
        f"/api/v1/documents/{document.pk}/parse",
        {"document_version_id": str(version.pk)},
        format="json",
        HTTP_IDEMPOTENCY_KEY="strict-parse-test-key-0002",
    )
    assert response.status_code == 409
    assert not DocumentParseJob.objects.exists()


@override_settings(ROOT_URLCONF="config.urls", DOCUMENT_OCR_PROVIDER="mock")
def test_parse_confirmation_replay_and_second_edit_form_continuous_chain(
    django_capture_on_commit_callbacks,
):
    data = b"machine\r\ntext"
    user, subject, document, version = _facts(data=data)
    MockStorageProvider.put_for_test(version.object_key, data, "text/plain")
    with (
        patch("apps.documents.parse_views.execute_parse_job.apply_async") as enqueue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = _client(user).post(
            f"/api/v1/documents/{document.pk}/parse",
            {"document_version_id": str(version.pk)},
            format="json",
            HTTP_IDEMPOTENCY_KEY="parse-continuous-chain-0001",
        )
    assert response.status_code == 202
    assert response["Cache-Control"] == "no-store"
    assert enqueue.call_count == 1
    job_id = response.json()["data"]["id"]
    assert execute_parse(job_id=job_id)["status"] == "succeeded"
    state = DocumentParseState.objects.get(document_version=version)
    assert state.latest_parsed_version.version_no == 1
    assert state.latest_parsed_version.extracted_text == "machine\ntext"

    first = confirm_parsed_text(
        user_id=user.pk,
        document_id=document.pk,
        expected_parse_state_version=state.version,
        source_parsed_version_id=state.latest_parsed_version_id,
        confirmed_text="confirmed one",
        request_id=uuid.uuid4(),
    )
    replay = confirm_parsed_text(
        user_id=user.pk,
        document_id=document.pk,
        expected_parse_state_version=state.version,
        source_parsed_version_id=state.latest_parsed_version_id,
        confirmed_text="confirmed one",
        request_id=uuid.uuid4(),
    )
    assert first[1].pk == replay[1].pk
    assert replay[2] is False
    current_state = DocumentParseState.objects.get(pk=state.pk)
    assert current_state.version == first[0].version

    second = confirm_parsed_text(
        user_id=user.pk,
        document_id=document.pk,
        expected_parse_state_version=current_state.version,
        source_parsed_version_id=current_state.latest_parsed_version_id,
        confirmed_text="confirmed two",
        request_id=uuid.uuid4(),
    )
    assert second[1].version_no == 3
    assert second[1].machine_base_version.version_no == 1
    assert (
        get_confirmed_document_content(subject=subject, document_version=version).pk == second[1].pk
    )
    assert DocumentParseEvent.objects.filter(event_type="confirmed").count() == 2


def test_stale_confirmation_different_text_conflicts():
    user, _, document, version = _facts()
    state = DocumentParseState.objects.create(
        user=user, subject=document.subject, document=document, document_version=version
    )
    machine = DocumentParsedVersion.objects.create(
        user=user,
        subject=document.subject,
        document=document,
        document_version=version,
        version_no=1,
        source="parser",
        extracted_text="machine",
        parser_key="txt",
        parser_version="1",
        content_digest="e" * 64,
    )
    state.latest_parsed_version = machine
    state.version = 2
    state.save()
    confirm_parsed_text(
        user_id=user.pk,
        document_id=document.pk,
        expected_parse_state_version=2,
        source_parsed_version_id=machine.pk,
        confirmed_text="first",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(DocumentParseVersionConflict):
        confirm_parsed_text(
            user_id=user.pk,
            document_id=document.pk,
            expected_parse_state_version=2,
            source_parsed_version_id=machine.pk,
            confirmed_text="different",
            request_id=uuid.uuid4(),
        )


def test_transient_storage_failure_persists_retry_wait_not_failed():
    user, _, document, version = _facts()
    job, _ = create_parse_job(
        user_id=user.pk,
        document_id=document.pk,
        document_version_id=version.pk,
        idempotency_key="transient-storage-test-0001",
        request_id=uuid.uuid4(),
    )
    with patch("apps.documents.parse_services.storage_provider") as factory:
        factory.return_value.head_object.side_effect = FileStorageUnavailable
        result = execute_parse(job_id=job.pk)
    job.refresh_from_db()
    assert result["status"] == "retry_wait"
    assert job.status == DocumentParseJob.Status.RETRY_WAIT
    assert job.next_attempt_at is not None
    assert job.finished_at is None


def test_finalize_notification_failure_rolls_back_all_machine_facts():
    data = b"safe text"
    user, _, document, version = _facts(data=data)
    job, _ = create_parse_job(
        user_id=user.pk,
        document_id=document.pk,
        document_version_id=version.pk,
        idempotency_key="finalize-rollback-test-0001",
        request_id=uuid.uuid4(),
    )
    MockStorageProvider.put_for_test(version.object_key, data, "text/plain")
    with patch.object(Notification.objects, "create", side_effect=RuntimeError("injected")):
        with pytest.raises(DocumentParseUnexpectedError):
            execute_parse(job_id=job.pk)
    job.refresh_from_db()
    state = DocumentParseState.objects.get(document_version=version)
    assert job.status == DocumentParseJob.Status.RUNNING
    assert state.latest_parsed_version_id is None
    assert not DocumentParsedVersion.objects.exists()
    assert not DocumentParseEvent.objects.filter(event_type="succeeded").exists()


def test_confirm_requires_active_account_but_not_subscription():
    user, _, document, version = _facts(with_subscription=False)
    state = DocumentParseState.objects.create(
        user=user, subject=document.subject, document=document, document_version=version
    )
    parsed = DocumentParsedVersion.objects.create(
        user=user,
        subject=document.subject,
        document=document,
        document_version=version,
        version_no=1,
        source="parser",
        extracted_text="machine",
        parser_key="txt",
        parser_version="1",
        content_digest="f" * 64,
    )
    state.latest_parsed_version = parsed
    state.version = 2
    state.save()
    confirm_parsed_text(
        user_id=user.pk,
        document_id=document.pk,
        expected_parse_state_version=2,
        source_parsed_version_id=parsed.pk,
        confirmed_text="allowed without subscription",
        request_id=uuid.uuid4(),
    )
    User.objects.filter(pk=user.pk).update(account_status=User.AccountStatus.CANCEL_PENDING)
    with pytest.raises(DocumentParseStateConflict):
        confirm_parsed_text(
            user_id=user.pk,
            document_id=document.pk,
            expected_parse_state_version=3,
            source_parsed_version_id=DocumentParseState.objects.get(
                pk=state.pk
            ).latest_parsed_version_id,
            confirmed_text="read only account",
            request_id=uuid.uuid4(),
        )


def test_models_do_not_add_parse_quota_web_import_or_subject_storage():
    fields = {field.name for field in DocumentParseJob._meta.fields}
    assert "quota_account" not in fields
    assert "subject_quota" not in fields
    assert not any("url" in field for field in fields)


def _parse_job_with_object(*, data=b"expected parser bytes", kind="txt"):
    user, _, document, version = _facts(kind=kind, data=data)
    job, created = create_parse_job(
        user_id=user.pk,
        document_id=document.pk,
        document_version_id=version.pk,
        idempotency_key=f"parse-integrity-{uuid.uuid4()}",
        request_id=uuid.uuid4(),
    )
    assert created
    MockStorageProvider.put_for_test(
        version.object_key,
        data,
        version.detected_mime,
    )
    return document, version, job


def _assert_integrity_failure(*, version, job):
    job.refresh_from_db()
    state = DocumentParseState.objects.get(document_version=version)
    assert job.status == DocumentParseJob.Status.FAILED
    assert job.stable_error_code == "DOCUMENT_PARSE_SOURCE_INTEGRITY_FAILED"
    assert state.latest_parsed_version_id is None
    assert state.current_confirmed_version_id is None
    assert not DocumentParsedVersion.objects.filter(document_version=version).exists()
    assert not DocumentParseEvent.objects.filter(
        document_version=version,
        event_type=DocumentParseEvent.EventType.SUCCEEDED,
    ).exists()
    assert not Notification.objects.filter(notification_type="document_parse_succeeded").exists()


@pytest.mark.parametrize(
    ("fault", "actual"),
    (
        ("head_size", b"expected parser bytes"),
        ("metadata_sha", b"expected parser bytes"),
        ("metadata_mime", b"expected parser bytes"),
        ("truncated_stream", b"short"),
        ("same_size_sha", b"EXPECTED PARSER BYTES"),
    ),
)
def test_parse_source_integrity_mismatch_fails_closed(fault, actual):
    expected = b"expected parser bytes"
    _, version, job = _parse_job_with_object(data=expected)
    expected_sha = hashlib.sha256(expected).hexdigest()
    metadata = ObjectMetadata(
        len(expected),
        "safe-etag",
        version.detected_mime,
        {"sha256": expected_sha},
    )
    if fault == "head_size":
        metadata = ObjectMetadata(
            len(expected) + 1,
            "safe-etag",
            version.detected_mime,
            {"sha256": expected_sha},
        )
    elif fault == "metadata_sha":
        metadata = ObjectMetadata(
            len(expected),
            "safe-etag",
            version.detected_mime,
            {"sha256": "0" * 64},
        )
    elif fault == "metadata_mime":
        metadata = ObjectMetadata(
            len(expected),
            "safe-etag",
            "application/octet-stream",
            {"sha256": expected_sha},
        )

    with patch("apps.documents.parse_services.storage_provider") as factory:
        factory.return_value.head_object.return_value = metadata
        factory.return_value.open_object.return_value = io.BytesIO(actual)
        result = execute_parse(job_id=job.pk)

    assert result == {
        "status": "failed",
        "code": "DOCUMENT_PARSE_SOURCE_INTEGRITY_FAILED",
    }
    _assert_integrity_failure(version=version, job=job)


def test_verified_pdf_input_is_same_seekable_bounded_spool():
    from apps.documents.parsers import ParseResult

    data = b"x" * 128
    _, version, job = _parse_job_with_object(data=data, kind="pdf")

    def assert_spool(file_kind, stream, ocr):
        assert file_kind == "pdf"
        assert stream.seekable()
        assert stream.tell() == 0
        assert stream.read() == data
        stream.seek(0)
        assert stream._rolled is True
        return ParseResult("bounded pdf", [], [], "pdf", "1")

    with (
        patch("apps.documents.parse_services.PARSE_SPOOL_MEMORY_BYTES", 16),
        patch("apps.documents.parse_services.parse_stream", side_effect=assert_spool),
    ):
        assert execute_parse(job_id=job.pk)["status"] == "succeeded"


def test_known_ocr_transient_persists_retry_wait():
    _, version, job = _parse_job_with_object(data=b"image bytes", kind="png")
    ocr = MockOcrProvider()
    with (
        patch("apps.documents.parse_services.get_ocr_provider", return_value=ocr),
        patch.object(ocr, "recognize", side_effect=DocumentOcrUnavailable),
    ):
        result = execute_parse(job_id=job.pk)
    job.refresh_from_db()
    assert result["status"] == "retry_wait"
    assert job.status == DocumentParseJob.Status.RETRY_WAIT
    assert job.stable_error_code == "DOCUMENT_OCR_UNAVAILABLE"


def test_permanent_parser_error_is_terminal_and_not_due():
    _, version, job = _parse_job_with_object(data=b"bad\x00text")
    result = execute_parse(job_id=job.pk)
    job.refresh_from_db()
    assert result["status"] == "failed"
    assert result["code"] == "DOCUMENT_PARSE_CONTENT_INVALID"
    assert job.status == DocumentParseJob.Status.FAILED
    assert job.pk not in due_parse_job_ids()
    assert not DocumentParsedVersion.objects.filter(document_version=version).exists()


@override_settings(DOCUMENT_PARSE_INTERNAL_MAX_RETRIES=1)
def test_unknown_exception_uses_bounded_task_retry_then_terminal(caplog):
    _, version, job = _parse_job_with_object()
    raw_exception = "private parser implementation detail"
    execute_parse_job.push_request(retries=0, headers={})
    try:
        with (
            patch(
                "apps.documents.parse_services.parse_stream",
                side_effect=RuntimeError(raw_exception),
            ),
            pytest.raises(Retry),
        ):
            execute_parse_job.run(str(job.pk))
    finally:
        execute_parse_job.pop_request()

    job.refresh_from_db()
    generation = job.generation
    assert job.status == DocumentParseJob.Status.RUNNING
    assert job.pk not in due_parse_job_ids()

    execute_parse_job.push_request(retries=1, headers={})
    try:
        with patch(
            "apps.documents.parse_services.parse_stream",
            side_effect=RuntimeError(raw_exception),
        ):
            result = execute_parse_job.run(str(job.pk), str(generation))
    finally:
        execute_parse_job.pop_request()

    job.refresh_from_db()
    assert result == {"status": "failed", "code": "DOCUMENT_PARSE_INTERNAL_ERROR"}
    assert job.status == DocumentParseJob.Status.FAILED
    assert job.stable_error_code == "DOCUMENT_PARSE_INTERNAL_ERROR"
    assert job.pk not in due_parse_job_ids()
    assert not DocumentParsedVersion.objects.filter(document_version=version).exists()
    assert (
        DocumentParseEvent.objects.filter(
            job=job,
            event_type=DocumentParseEvent.EventType.STARTED,
        ).count()
        == 1
    )
    persisted = str(
        list(DocumentParseEvent.objects.filter(job=job).values("stable_error_code", "safe_summary"))
    ) + str(
        list(
            Notification.objects.filter(recipient=job.user).values(
                "notification_type", "safe_summary"
            )
        )
    )
    assert raw_exception not in persisted
    assert raw_exception in caplog.text
    assert not getattr(execute_parse_job, "autoretry_for", ())
