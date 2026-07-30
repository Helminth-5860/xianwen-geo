from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.users.models import User
from apps.users.phone_numbers import mask_phone, normalize_phone, phone_fingerprint

STRONG_PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.mark.parametrize(
    "raw_phone",
    [
        "13800138000",
        "+8613800138000",
        "008613800138000",
        "138 0013 8000",
        "138-0013-8000",
        "+86 138-0013-8000",
    ],
)
def test_mainland_phone_equivalent_formats_are_normalized(raw_phone):
    assert normalize_phone(raw_phone) == "+8613800138000"


@pytest.mark.parametrize(
    "raw_phone",
    ["", "12800138000", "1380013800", "138001380000", "+8513800138000"],
)
def test_invalid_mainland_phone_is_rejected(raw_phone):
    with pytest.raises(ValidationError):
        normalize_phone(raw_phone)


def test_phone_mask_and_fingerprint_do_not_expose_full_phone(settings):
    settings.SECRET_KEY = "test-fingerprint-secret"

    assert mask_phone("+8613800138000") == "+86 138****8000"
    fingerprint = phone_fingerprint("+8613800138000")
    assert len(fingerprint) == 64
    assert "+8613800138000" not in fingerprint


@pytest.mark.django_db
def test_create_user_uses_uuid_normalized_phone_and_password_hash():
    user = User.objects.create_user(
        phone="0086 138-0013-8000",
        nickname="测试用户",
        password=STRONG_PASSWORD,
    )

    assert isinstance(user.id, UUID)
    assert user.phone == "+8613800138000"
    assert user.password != STRONG_PASSWORD
    assert user.check_password(STRONG_PASSWORD)
    assert user.approval_status == User.ApprovalStatus.PENDING
    assert user.account_status == User.AccountStatus.ACTIVE
    assert user.is_active is True
    for forbidden_field in ("username", "first_name", "last_name", "trial_ever_granted"):
        assert not hasattr(user, forbidden_field)


@pytest.mark.django_db
def test_equivalent_phone_formats_share_database_uniqueness():
    User.objects.create_user(
        phone="13800138000",
        nickname="用户一",
        password=STRONG_PASSWORD,
    )

    with pytest.raises(ValidationError):
        User.objects.create_user(
            phone="+86 138-0013-8000",
            nickname="用户二",
            password="Another-Secure-Password-2026!",
        )


@pytest.mark.django_db
def test_create_user_enforces_django_password_validators():
    with pytest.raises(ValidationError):
        User.objects.create_user(
            phone="13900139000",
            nickname="弱密码用户",
            password="1234567890",
        )


@pytest.mark.django_db
def test_create_superuser_sets_required_django_flags():
    user = User.objects.create_superuser(
        phone="13700137000",
        nickname="技术管理员",
        password=STRONG_PASSWORD,
    )

    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.is_active is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("account_status", "expected_active"),
    [
        (User.AccountStatus.ACTIVE, True),
        (User.AccountStatus.CANCEL_PENDING, True),
        (User.AccountStatus.FROZEN, False),
        (User.AccountStatus.CANCELLED, False),
    ],
)
def test_account_status_service_atomically_synchronizes_is_active(
    account_status,
    expected_active,
):
    user = User.objects.create_user(
        phone="13600136000",
        nickname="状态用户",
        password=STRONG_PASSWORD,
    )

    user.set_account_status(account_status)
    user.refresh_from_db()

    assert user.account_status == account_status
    assert user.is_active is expected_active


@pytest.mark.django_db(transaction=True)
def test_database_constraint_prevents_account_status_active_drift():
    user = User.objects.create_user(
        phone="13500135000",
        nickname="约束用户",
        password=STRONG_PASSWORD,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(
            account_status=User.AccountStatus.FROZEN,
            is_active=True,
        )
