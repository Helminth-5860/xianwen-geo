import time as time_module
import uuid
from datetime import time, timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.plans.models import Plan, PlanVersion, Subscription
from apps.subjects.models import Subject, SubjectType
from apps.users.models import User
from apps.web_sources.exceptions import (
    WebSourceContentTooLarge,
    WebSourceContentUnsupported,
    WebSourceStateConflict,
    WebSourceUnexpectedError,
    WebSourceUrlInvalid,
    WebSourceUrlNotAllowed,
)
from apps.web_sources.http_transport import FetchResult, _request_once, fetch_url
from apps.web_sources.models import WebSourceImport, WebSourceParsedVersion, WebSourceSnapshot
from apps.web_sources.parser import parse_response
from apps.web_sources.services import confirmed_content, execute_import
from apps.web_sources.url_security import canonicalize_url, is_allowed_address, resolve_and_validate

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-2026!"


def _facts():
    suffix = uuid.uuid4().hex[:10]
    user = User.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="Web source user",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
    )
    subject_type = SubjectType.objects.create(
        key=f"web_{suffix}",
        name="Web type",
        status=SubjectType.Status.INACTIVE,
    )
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.DRAFT,
        draft_values={},
        schema_version=1,
        schema_snapshot_format_version=1,
        schema_snapshot={"fields": []},
        schema_digest="a" * 64,
    )
    now = timezone.now()
    plan = Plan.objects.create(
        code=f"web-{suffix}",
        name="Web plan",
        is_trial=True,
        status=Plan.Status.PUBLISHED,
    )
    version = PlanVersion.objects.create(
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
        plan_version=version,
        plan_version_no=1,
        entitlement_snapshot={"limits": {}},
        entitlement_digest="c" * 64,
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=10),
        cycle_anchor_day=now.day,
        cycle_anchor_time=time(0, 0),
        is_trial=True,
        activated_at=now,
        request_id=uuid.uuid4(),
    )
    return user, subject


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "http://user:pass@example.com/",
        "http://example.com/#secret",
        "http://example.com\\@evil.test/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://[fe80::1%25eth0]/",
        "http://example.com:8080/",
    ],
)
def test_url_parser_rejects_ambiguous_or_dangerous_forms(value):
    with pytest.raises((WebSourceUrlInvalid, WebSourceUrlNotAllowed)):
        canonicalize_url(value)


def test_url_canonicalization_preserves_query_semantics_but_redacts_display():
    value = canonicalize_url("HTTPS://BÜCHER.example?token=a%2Fb&token=A+b")
    assert value.host == "xn--bcher-kva.example"
    assert value.value.endswith("/?token=a%2Fb&token=A+b")
    assert value.display == "https://xn--bcher-kva.example/"
    assert value.has_query is True


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1", "::ffff:127.0.0.1"],
)
def test_production_address_predicate_rejects_non_global_ranges(address):
    with override_settings(APP_ENV="production", WEB_IMPORT_TEST_ALLOWED_CIDRS=()):
        assert is_allowed_address(address) is False


def test_dns_answer_set_fails_closed_if_any_answer_is_private():
    answers = [
        (2, 1, 6, "", ("93.184.216.34", 80)),
        (2, 1, 6, "", ("127.0.0.1", 80)),
    ]
    with (
        override_settings(APP_ENV="production", WEB_IMPORT_TEST_ALLOWED_CIDRS=()),
        patch(
            "apps.web_sources.url_security.socket.getaddrinfo",
            return_value=answers,
        ),
    ):
        with pytest.raises(WebSourceUrlNotAllowed):
            resolve_and_validate("example.com", 80)


def test_static_parser_ignores_executable_and_subresource_content():
    body = b"<title>Safe</title><p>Hello</p><script>secret()</script><iframe>bad</iframe>"
    title, text, charset, _ = parse_response(
        body=body, media_type="text/html", content_type="text/html; charset=utf-8"
    )
    assert title == "Safe"
    assert text == "Safe Hello"
    assert charset == "utf-8"


def test_parser_rejects_unapproved_charset():
    with pytest.raises(WebSourceContentUnsupported):
        parse_response(
            body=b"text",
            media_type="text/plain",
            content_type="text/plain; charset=utf-16",
        )


def test_saga_finalization_is_exactly_once_and_requires_confirmation_for_selector():
    user, subject = _facts()
    row = WebSourceImport.objects.create(
        user=user,
        subject=subject,
        canonical_url="https://example.com/",
        display_url="https://example.com/",
        has_query=False,
        hostname_fingerprint="d" * 64,
        idempotency_key_digest=uuid.uuid4().hex * 2,
        request_digest="e" * 64,
        request_id=uuid.uuid4(),
    )
    fetched = FetchResult(
        request_url=row.canonical_url,
        final_url=row.canonical_url,
        status=200,
        content_type="text/html; charset=utf-8",
        body=b"<h1>Public page</h1>",
        response_sha256="f" * 64,
        redirect_count=0,
        peer_ip="93.184.216.34",
    )
    with patch("apps.web_sources.services.fetch_url", return_value=fetched):
        assert execute_import(import_id=row.pk)["status"] == "succeeded"
        assert execute_import(import_id=row.pk)["status"] == "unchanged"
    row.refresh_from_db()
    assert WebSourceSnapshot.objects.filter(import_record=row).count() == 1
    assert WebSourceParsedVersion.objects.filter(import_record=row).count() == 1
    with pytest.raises(WebSourceStateConflict):
        confirmed_content(subject=subject, import_record=row)


def test_import_api_has_csrf_idempotency_redacted_url_and_no_store():
    user, subject = _facts()
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf")
    login = client.post(
        "/api/v1/auth/login/password",
        {"phone": user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["xianwen_csrf"].value,
    )
    assert login.status_code == 200
    path = "/api/v1/web-sources/import"
    payload = {"subject_id": str(subject.pk), "url": "https://example.com/?token=secret"}
    missing_csrf = client.post(path, payload, format="json", HTTP_IDEMPOTENCY_KEY="web-key-0001")
    assert missing_csrf.status_code == 403
    with patch("apps.web_sources.views.execute_import_task.apply_async"):
        response = client.post(
            path,
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="web-key-0001",
            HTTP_X_CSRFTOKEN=client.cookies["xianwen_csrf"].value,
        )
    assert response.status_code == 202
    assert response["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["display_url"] == "https://example.com/"
    assert data["has_query"] is True
    assert "secret" not in response.content.decode()


def test_broker_enqueue_failure_keeps_durable_import_accepted():
    user, subject = _facts()
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf")
    client.post(
        "/api/v1/auth/login/password",
        {"phone": user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["xianwen_csrf"].value,
    )
    with patch(
        "apps.web_sources.views.execute_import_task.apply_async",
        side_effect=RuntimeError("broker unavailable"),
    ):
        response = client.post(
            "/api/v1/web-sources/import",
            {"subject_id": str(subject.pk), "url": "https://example.com/"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="web-key-enqueue-failure",
            HTTP_X_CSRFTOKEN=client.cookies["xianwen_csrf"].value,
        )
    assert response.status_code == 202
    row = WebSourceImport.objects.get(pk=response.json()["data"]["id"])
    assert row.status == "queued"


def test_unknown_failure_retry_reuses_the_claimed_generation():
    user, subject = _facts()
    row = WebSourceImport.objects.create(
        user=user,
        subject=subject,
        canonical_url="https://example.com/",
        display_url="https://example.com/",
        has_query=False,
        hostname_fingerprint="d" * 64,
        idempotency_key_digest=uuid.uuid4().hex * 2,
        request_digest="e" * 64,
        request_id=uuid.uuid4(),
    )
    with patch("apps.web_sources.services.fetch_url", side_effect=RuntimeError("bug")):
        with pytest.raises(WebSourceUnexpectedError):
            execute_import(import_id=row.pk)
    row.refresh_from_db()
    generation = row.generation
    fetched = FetchResult(
        request_url=row.canonical_url,
        final_url=row.canonical_url,
        status=200,
        content_type="text/plain; charset=utf-8",
        body=b"safe",
        response_sha256="f" * 64,
        redirect_count=0,
        peer_ip="93.184.216.34",
    )
    with patch("apps.web_sources.services.fetch_url", return_value=fetched):
        result = execute_import(import_id=row.pk, expected_generation=generation)
    assert result["status"] == "succeeded"


def test_ipv6_literal_is_canonicalized_without_idna_reinterpretation():
    parsed = canonicalize_url("https://[2001:4860:4860::8888]/a?x=%2F")
    assert parsed.host == "2001:4860:4860::8888"
    assert parsed.value == "https://[2001:4860:4860::8888]/a?x=%2F"


def test_static_parser_excludes_hidden_form_and_embed_subtrees():
    body = (
        b"<p>visible</p><section hidden>secret</section>"
        b"<form>credential</form><embed>plugin</embed><p>end</p>"
    )
    _, text, _, _ = parse_response(
        body=body, media_type="text/html", content_type="text/html; charset=utf-8"
    )
    assert text == "visible end"


def test_redirect_handling_rejects_downgrade_nonstandard_and_excessive_hops():
    with patch(
        "apps.web_sources.http_transport._request_once",
        return_value=(302, [("Location", "http://example.com/")], b"", "93.184.216.34"),
    ):
        with pytest.raises(WebSourceUrlNotAllowed):
            fetch_url("https://example.com/")
    with patch(
        "apps.web_sources.http_transport._request_once",
        return_value=(304, [("Location", "https://example.com/next")], b"", "93.184.216.34"),
    ):
        with pytest.raises(WebSourceContentUnsupported):
            fetch_url("https://example.com/")
    redirect = (302, [("Location", "/again")], b"", "93.184.216.34")
    with patch("apps.web_sources.http_transport._request_once", return_value=redirect):
        with pytest.raises(WebSourceUrlInvalid):
            fetch_url("https://example.com/")


class _FakeSocket:
    def settimeout(self, _timeout):
        return None

    def sendall(self, _payload):
        return None

    def close(self):
        return None


class _FakeResponse:
    reason = "OK"
    status = 200

    def __init__(self, _socket, *, headers, body):
        self.headers = headers
        self.body = body
        self.offset = 0

    def begin(self):
        return None

    def getheaders(self):
        return self.headers

    def getheader(self, name):
        values = [value for key, value in self.headers if key.lower() == name.lower()]
        return values[0] if values else None

    def read(self, amount):
        chunk = self.body[self.offset : self.offset + amount]
        self.offset += len(chunk)
        return chunk


@pytest.mark.parametrize(
    ("headers", "body", "error"),
    [
        ([("Content-Encoding", "gzip")], b"x", WebSourceContentUnsupported),
        ([("Content-Length", "999999999")], b"", WebSourceContentTooLarge),
        ([("Content-Length", "4")], b"xx", WebSourceContentUnsupported),
        (
            [("Transfer-Encoding", "chunked"), ("Content-Length", "2")],
            b"xx",
            WebSourceContentUnsupported,
        ),
    ],
)
def test_response_bounds_and_encoding_fail_closed(headers, body, error):
    with (
        patch(
            "apps.web_sources.http_transport.resolve_and_validate", return_value=("93.184.216.34",)
        ),
        patch("apps.web_sources.http_transport._connect", return_value=_FakeSocket()),
        patch(
            "apps.web_sources.http_transport.http.client.HTTPResponse",
            side_effect=lambda sock: _FakeResponse(sock, headers=headers, body=body),
        ),
    ):
        with pytest.raises(error):
            _request_once(canonicalize_url("https://example.com/"), time_module.monotonic() + 5)
