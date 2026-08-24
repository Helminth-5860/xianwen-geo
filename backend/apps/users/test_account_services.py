from django.db import transaction

from apps.plans.subscription_services import (
    ensure_internal_test_subscription,
    terminate_internal_test_subscription,
)

from .models import User


class TestAccountTargetInvalid(Exception):
    pass


@transaction.atomic
def set_test_account_access(*, user_id, enabled: bool, actor, request_id) -> User:
    try:
        user = User.objects.select_for_update().get(
            pk=user_id,
            is_staff=False,
            is_superuser=False,
        )
    except User.DoesNotExist as exc:
        raise TestAccountTargetInvalid from exc

    if enabled:
        if not user.is_test_account:
            user.is_test_account = True
            user.save(update_fields=["is_test_account", "updated_at"])
        ensure_internal_test_subscription(
            user=user,
            request_id=request_id,
            actor=actor,
        )
    else:
        terminate_internal_test_subscription(user=user, actor=actor)
        if user.is_test_account:
            user.is_test_account = False
            user.save(update_fields=["is_test_account", "updated_at"])
    return user
