import io
from urllib.parse import urlsplit

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminProfile,
    AdminRole,
    AuditEvent,
    CustomerAssignment,
    SalesContactConfiguration,
)
from apps.documents.storage import MockStorageProvider, S3CompatibleStorageProvider
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

ADMIN_PATH = "/api/v1/admin/sales-contact"
CUSTOMER_PATH = "/api/v1/sales-contact"


@pytest.fixture(autouse=True)
def clear_mock_storage():
    MockStorageProvider.clear()
    yield
    MockStorageProvider.clear()


def image_file(
    name: str,
    color: tuple[int, int, int],
    *,
    size: tuple[int, int] = (128, 128),
) -> SimpleUploadedFile:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


def make_root(phone: str = "13900139000") -> User:
    return User.objects.create_user(
        phone=phone,
        nickname="平台管理员",
        password="Safe-Test-Password-2026!",
        is_staff=True,
        is_superuser=True,
    )


def make_agent(phone: str, name: str) -> AdminProfile:
    role = AdminRole.objects.create(
        name=f"{name}角色",
        description="销售服务",
        data_scope=AdminRole.DataScope.OWN,
    )
    user = User.objects.create_user(
        phone=phone,
        nickname=name,
        password="Safe-Test-Password-2026!",
        is_staff=True,
    )
    return AdminProfile.objects.create(user=user, role=role)


def make_customer(phone: str, *, owner: AdminProfile | None = None) -> User:
    user = User.objects.create_user(
        phone=phone,
        nickname="套餐客户",
        password="Safe-Test-Password-2026!",
    )
    CustomerAssignment.objects.create(customer=user, owner_admin=owner)
    return user


def admin_client(user: User) -> APIClient:
    return authenticate_admin_client(APIClient(), user)


def upload(client: APIClient, image: SimpleUploadedFile, *, enabled=True):
    return client.put(
        ADMIN_PATH,
        {"qr_code": image, "enabled": enabled},
        format="multipart",
    )


def customer_client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def media_path(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def media_bytes(url: str):
    response = APIClient().get(media_path(url))
    content = b"".join(response.streaming_content) if response.streaming else response.content
    return response.status_code, content


@pytest.mark.django_db
def test_superuser_configures_global_qr_and_direct_customer_receives_signed_media():
    root = make_root()
    response = upload(admin_client(root), image_file("global.png", (20, 40, 60)))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scope"] == "global"
    assert data["configured"] is True
    assert data["enabled"] is True
    assert data["updated_at"]
    assert "object_key" not in response.content.decode()
    assert "owner_admin" not in response.content.decode()

    config = SalesContactConfiguration.objects.get(scope="global")
    assert config.owner_admin_id is None
    assert config.updated_by_id == root.pk
    audit = AuditEvent.objects.get(
        target_type="sales_contact", action_key="sales_contact_qr_set"
    )
    assert audit.safe_after["scope"] == "global"
    assert audit.safe_after["agent_id"] is None
    assert audit.safe_after["file_reference"] == config.object_key

    customer = make_customer("13800138000")
    resolved = customer_client(customer).get(CUSTOMER_PATH)
    assert resolved.status_code == 200
    assert resolved.json()["data"]["configured"] is True
    status_code, content = media_bytes(resolved.json()["data"]["qr_code_url"])
    assert status_code == 200
    assert content == image_file("expected.png", (20, 40, 60)).read()


@pytest.mark.django_db
def test_agent_is_strictly_limited_to_own_configuration_and_customer_prefers_it():
    root = make_root()
    upload(admin_client(root), image_file("global.png", (10, 10, 10)))
    agent_a = make_agent("13700137001", "甲方代理")
    agent_b = make_agent("13700137002", "乙方代理")

    saved = upload(admin_client(agent_a.user), image_file("agent-a.png", (30, 90, 150)))
    assert saved.status_code == 200
    assert saved.json()["data"]["scope"] == "agent"

    own_a = SalesContactConfiguration.objects.get(owner_admin=agent_a)
    original_agent_sha = own_a.sha256
    original_global_sha = SalesContactConfiguration.objects.get(scope="global").sha256
    denied = admin_client(agent_b.user).put(
        ADMIN_PATH,
        {
            "qr_code": image_file("agent-b.png", (200, 40, 50)),
            "enabled": True,
            "owner_admin_id": str(agent_a.pk),
        },
        format="multipart",
    )
    assert denied.status_code == 422
    own_a.refresh_from_db()
    assert own_a.sha256 == original_agent_sha
    assert not SalesContactConfiguration.objects.filter(owner_admin=agent_b).exists()

    own_b = upload(admin_client(agent_b.user), image_file("agent-b.png", (200, 40, 50)))
    assert own_b.status_code == 200
    assert SalesContactConfiguration.objects.get(scope="global").sha256 == original_global_sha
    assert SalesContactConfiguration.objects.get(owner_admin=agent_b).owner_admin_id == agent_b.pk

    customer = make_customer("13800138001", owner=agent_a)
    resolved = customer_client(customer).get(CUSTOMER_PATH).json()["data"]
    status_code, content = media_bytes(resolved["qr_code_url"])
    assert status_code == 200
    assert content == image_file("expected.png", (30, 90, 150)).read()


@pytest.mark.django_db
def test_missing_or_disabled_agent_qr_falls_back_to_global_then_friendly_empty_state():
    root = make_root()
    global_response = upload(admin_client(root), image_file("global.png", (80, 80, 80)))
    global_url = global_response.json()["data"]["qr_code_url"]
    agent = make_agent("13700137003", "无二维码代理")
    customer = make_customer("13800138002", owner=agent)

    fallback = customer_client(customer).get(CUSTOMER_PATH)
    assert fallback.status_code == 200
    assert media_bytes(fallback.json()["data"]["qr_code_url"])[1] == media_bytes(global_url)[1]

    uploaded = upload(admin_client(agent.user), image_file("agent.png", (30, 130, 70)))
    assert uploaded.status_code == 200
    disabled = admin_client(agent.user).patch(ADMIN_PATH, {"enabled": False}, format="json")
    assert disabled.status_code == 200
    assert disabled.json()["data"]["configured"] is True
    assert disabled.json()["data"]["enabled"] is False
    fallback_after_disable = customer_client(customer).get(CUSTOMER_PATH).json()["data"]
    assert media_bytes(fallback_after_disable["qr_code_url"])[1] == media_bytes(global_url)[1]

    assert admin_client(agent.user).patch(
        ADMIN_PATH, {"enabled": True}, format="json"
    ).status_code == 200
    agent.admin_status = AdminProfile.Status.DISABLED
    agent.save(update_fields=("admin_status", "updated_at"))
    assert (
        media_bytes(customer_client(customer).get(CUSTOMER_PATH).json()["data"]["qr_code_url"])[
            1
        ]
        == media_bytes(global_url)[1]
    )

    disabled_global = admin_client(root).patch(
        ADMIN_PATH, {"enabled": False}, format="json"
    )
    assert disabled_global.status_code == 200
    empty = customer_client(customer).get(CUSTOMER_PATH)
    assert empty.status_code == 200
    assert empty.json()["data"] == {
        "configured": False,
        "message": "销售联系方式暂未配置，请稍后联系平台客服。",
    }


@pytest.mark.django_db
def test_replacing_qr_invalidates_old_token_and_invalid_images_are_rejected():
    root = make_root()
    client = admin_client(root)
    first = upload(client, image_file("first.png", (1, 2, 3)))
    old_url = first.json()["data"]["qr_code_url"]

    second = upload(client, image_file("second.png", (4, 5, 6)))
    new_url = second.json()["data"]["qr_code_url"]
    assert APIClient().get(media_path(old_url)).status_code == 404
    assert media_bytes(new_url)[0] == 200
    assert AuditEvent.objects.filter(
        target_type="sales_contact", action_key="sales_contact_qr_replaced"
    ).count() == 1
    replacement_audit = AuditEvent.objects.get(
        target_type="sales_contact", action_key="sales_contact_qr_replaced"
    )
    assert replacement_audit.safe_before["file_reference"]
    assert replacement_audit.safe_after["file_reference"]
    assert (
        replacement_audit.safe_before["file_reference"]
        != replacement_audit.safe_after["file_reference"]
    )

    invalid = upload(
        client,
        SimpleUploadedFile("fake.png", b"this is not an image", content_type="image/png"),
    )
    assert invalid.status_code == 422
    assert SalesContactConfiguration.objects.count() == 1

    too_small = upload(client, image_file("tiny.png", (1, 1, 1), size=(32, 32)))
    assert too_small.status_code == 422
    too_wide = upload(client, image_file("wide.png", (1, 1, 1), size=(4097, 64)))
    assert too_wide.status_code == 422


@pytest.mark.django_db
def test_agent_cannot_enable_without_upload_and_invalid_media_token_never_500s():
    agent = make_agent("13700137004", "未配置代理")
    response = admin_client(agent.user).patch(ADMIN_PATH, {"enabled": True}, format="json")
    assert response.status_code == 422
    assert APIClient().get("/api/v1/sales-contact/qr?token=invalid").status_code == 404


@pytest.mark.django_db
def test_signed_media_streams_through_s3_compatible_provider(monkeypatch):
    root = make_root()
    saved = upload(admin_client(root), image_file("global.png", (70, 80, 90)))
    url = saved.json()["data"]["qr_code_url"]
    config = SalesContactConfiguration.objects.get(scope="global")
    expected = MockStorageProvider().open_object(config.object_key).read()

    class FakeS3Client:
        def get_object(self, *, Bucket, Key):  # noqa: N803
            assert Bucket == "private-media"
            assert Key == config.object_key
            return {"Body": io.BytesIO(expected)}

    provider = S3CompatibleStorageProvider.__new__(S3CompatibleStorageProvider)
    provider.bucket = "private-media"
    provider.client = FakeS3Client()
    monkeypatch.setattr(
        "apps.admin_rbac.sales_contact_views.storage_provider",
        lambda: provider,
    )

    status_code, content = media_bytes(url)
    assert status_code == 200
    assert content == expected


@pytest.mark.django_db
def test_media_url_respects_the_trusted_proxy_https_scheme():
    root = make_root()
    response = admin_client(root).put(
        ADMIN_PATH,
        {"qr_code": image_file("global.png", (9, 8, 7)), "enabled": True},
        format="multipart",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_HOST="testserver",
    )
    assert response.status_code == 200
    assert response.json()["data"]["qr_code_url"].startswith(
        "https://testserver/api/v1/sales-contact/qr?"
    )
