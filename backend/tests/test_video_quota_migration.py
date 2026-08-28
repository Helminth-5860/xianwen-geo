import copy
import importlib
import uuid
from datetime import timedelta

import pytest
from django.apps import apps
from django.core.management import call_command
from django.utils import timezone

from apps.plans.models import Subscription
from apps.quotas.models import QuotaAccount, QuotaLedgerEntry
from apps.users.models import User
from tests.test_subscriptions import PASSWORD, published_plan

MAX_AMOUNT = 2**63 - 1


def _historical_subscription(*, user, plan, version, source_type):
    snapshot = copy.deepcopy(version.effective_config)
    snapshot["limits"].pop("video_credits", None)
    now = timezone.now()
    return Subscription.objects.create(
        user=user,
        source_type=source_type,
        plan=plan,
        plan_version=version,
        plan_version_no=version.version_no,
        entitlement_snapshot=snapshot,
        entitlement_digest="f" * 64,
        status=Subscription.Status.ACTIVE,
        starts_at=now,
        ends_at=now + timedelta(days=30),
        cycle_anchor_day=timezone.localtime(now).day,
        cycle_anchor_time=timezone.localtime(now).timetz().replace(tzinfo=None),
        is_trial=source_type == Subscription.SourceType.TRIAL_GRANT,
        activated_at=now,
        request_id=uuid.uuid4(),
    )


@pytest.mark.django_db
def test_video_quota_backfill_is_fail_closed_and_preserves_internal_test_access():
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    admin = User.objects.create_superuser(
        phone="13900139111",
        nickname="迁移测试管理员",
        password=PASSWORD,
    )
    ordinary = User.objects.create_user(
        phone="13800138111",
        nickname="历史普通用户",
        password=PASSWORD,
    )
    internal = User.objects.create_user(
        phone="13700137111",
        nickname="历史测试用户",
        password=PASSWORD,
        is_test_account=True,
    )
    plan, version = published_plan(
        admin,
        code=f"video-migration-{uuid.uuid4().hex[:8]}",
        trial=True,
    )
    ordinary_subscription = _historical_subscription(
        user=ordinary,
        plan=plan,
        version=version,
        source_type=Subscription.SourceType.TRIAL_GRANT,
    )
    internal_subscription = _historical_subscription(
        user=internal,
        plan=plan,
        version=version,
        source_type=Subscription.SourceType.INTERNAL_TEST,
    )

    migration = importlib.import_module(
        "apps.quotas.migrations.0014_backfill_video_credit_accounts"
    )
    migration.backfill_video_accounts(apps, None)
    migration.backfill_video_accounts(apps, None)

    ordinary_account = QuotaAccount.objects.get(
        subscription=ordinary_subscription,
        quota_type="video_credits",
    )
    internal_account = QuotaAccount.objects.get(
        subscription=internal_subscription,
        quota_type="video_credits",
    )
    assert (ordinary_account.entitlement_amount, ordinary_account.available) == (0, 0)
    assert (internal_account.entitlement_amount, internal_account.available) == (
        MAX_AMOUNT,
        MAX_AMOUNT,
    )
    assert (
        QuotaLedgerEntry.objects.filter(
            account__in=(ordinary_account, internal_account),
            action=QuotaLedgerEntry.Action.INITIALIZE,
        ).count()
        == 2
    )
    for account in (ordinary_account, internal_account):
        assert account.unit == "second"
        assert account.scope == "subscription"
        assert account.ledger_sequence == 1
        assert account.last_ledger_entry_id is not None
