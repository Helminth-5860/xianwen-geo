import hashlib
import json
import uuid

from django.db import migrations

BATCH_NAMESPACE = uuid.UUID("75b40c5c-b210-48a7-8805-a8f056e4eeac")
ACCOUNT_NAMESPACE = uuid.UUID("7bdfe812-b8ed-49a4-8a28-1713305265ab")
LEDGER_NAMESPACE = uuid.UUID("8302f4fc-2d3f-4a92-9dde-a6a238bbbaec")
REQUEST_NAMESPACE = uuid.UUID("c71326a5-e33d-4ea6-bd93-a6fdc770f9d0")
MAX_AMOUNT = 2**63 - 1


def _digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def backfill_video_accounts(apps, schema_editor):
    Subscription = apps.get_model("plans", "Subscription")
    Account = apps.get_model("quotas", "QuotaAccount")
    Ledger = apps.get_model("quotas", "QuotaLedgerEntry")
    for subscription in Subscription.objects.order_by("id").iterator():
        snapshot = subscription.entitlement_snapshot
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("limits"), dict):
            raise RuntimeError("invalid subscription entitlement snapshot")
        limits = snapshot["limits"]
        # Historical immutable snapshots predate video_credits. Ordinary
        # subscriptions must fail closed at zero, while the dedicated internal
        # test subscription remains unlimited just like its other quota types.
        raw_amount = (
            MAX_AMOUNT
            if subscription.source_type == "internal_test"
            else limits.get("video_credits", 0)
        )
        if type(raw_amount) is not int or not 0 <= raw_amount <= MAX_AMOUNT:
            raise RuntimeError("invalid video quota value in subscription entitlement snapshot")
        amount = raw_amount
        batch_key = uuid.uuid5(BATCH_NAMESPACE, f"{subscription.pk}|video_credits|subscription")
        account_id = uuid.uuid5(ACCOUNT_NAMESPACE, str(batch_key))
        account, created = Account.objects.get_or_create(
            subscription_id=subscription.pk,
            quota_type="video_credits",
            subject_id=None,
            batch_type="primary",
            cycle_started_at=None,
            defaults={
                "id": account_id,
                "user_id": subscription.user_id,
                "scope": "subscription",
                "unit": "second",
                "batch_key": batch_key,
                "entitlement_amount": amount,
            },
        )
        if not created:
            if (
                account.user_id != subscription.user_id
                or account.scope != "subscription"
                or account.unit != "second"
                or account.batch_key != batch_key
                or account.entitlement_amount != amount
                or account.cycle_started_at is not None
                or account.cycle_ends_at is not None
                or account.ledger_sequence < 1
                or account.last_ledger_entry_id is None
            ):
                raise RuntimeError(
                    "existing video quota account conflicts with immutable subscription snapshot"
                )
            continue
        request_id = uuid.uuid5(REQUEST_NAMESPACE, str(account.pk))
        payload = {
            "operation": "initialize-video-credits",
            "subscription_id": str(subscription.pk),
            "account_id": str(account.pk),
            "quota_type": "video_credits",
            "amount": amount,
        }
        entry = Ledger.objects.create(
            id=uuid.uuid5(LEDGER_NAMESPACE, str(account.pk)),
            account_id=account.pk,
            user_id=subscription.user_id,
            subscription_id=subscription.pk,
            quota_type="video_credits",
            sequence=1,
            action="initialize",
            available_before=0,
            available_delta=amount,
            available_after=amount,
            frozen_before=0,
            frozen_delta=0,
            frozen_after=0,
            account_version_before=1,
            account_version_after=2,
            business_type="subscription",
            business_id=subscription.pk,
            safe_reason="视频额度账户初始化。",
            actor_id=None,
            request_id=request_id,
            idempotency_key_version=1,
            idempotency_key_digest=_digest({"key": payload}),
            idempotency_scope_digest=_digest({"scope": payload}),
            request_digest=_digest(payload),
        )
        Account.objects.filter(pk=account.pk).update(
            available=amount,
            ledger_sequence=1,
            last_ledger_entry_id=entry.pk,
            version=2,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("plans", "0017_add_video_credit_definition"),
        ("quotas", "0013_quotaholdgroup_test_account_bypass"),
    ]
    operations = [
        migrations.RunPython(backfill_video_accounts, migrations.RunPython.noop),
    ]
