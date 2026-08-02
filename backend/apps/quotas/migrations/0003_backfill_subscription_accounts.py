import calendar
import hashlib
import json
import uuid
from datetime import datetime

from django.db import migrations
from django.utils import timezone


BATCH_NAMESPACE = uuid.UUID("75b40c5c-b210-48a7-8805-a8f056e4eeac")
ACCOUNT_NAMESPACE = uuid.UUID("fc37ba44-775e-4c02-a026-e65d71042acc")
LEDGER_NAMESPACE = uuid.UUID("e7a5cad2-f5c6-443e-b232-a120426aab71")
MAX_AMOUNT = 2**63 - 1
DEFINITIONS = (
    ("detection_points", "detection_points", "point", "subscription"),
    ("article_credits", "article_credits", "article", "subscription"),
    ("image_credits", "image_credits", "image", "subscription"),
    ("storage_bytes", "storage_bytes", "byte", "account"),
    ("assistant_messages", "assistant_messages_per_cycle", "count", "account_cycle"),
)
REQUIRED_LIMIT_KEYS = (
    "detection_points",
    "article_credits",
    "image_credits",
    "storage_bytes",
    "assistant_messages_per_cycle",
    "keyword_regenerations_per_cycle",
    "distillation_regenerations_per_cycle",
    "question_bank_regenerations_per_cycle",
    "strategy_regenerations_per_cycle",
    "outline_regenerations_per_cycle",
    "local_ai_edits_per_cycle",
    "quality_rechecks_per_cycle",
)


def _amounts(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("limits"), dict):
        raise RuntimeError("invalid subscription entitlement snapshot")
    limits = snapshot["limits"]
    values = {}
    for key in REQUIRED_LIMIT_KEYS:
        value = limits.get(key)
        if type(value) is not int or value < 0 or value > MAX_AMOUNT:
            raise RuntimeError("invalid quota value in subscription entitlement snapshot")
        values[key] = value
    return values


def _cycle(subscription):
    local_start = timezone.localtime(subscription.starts_at)
    if local_start.month == 12:
        year, month = local_start.year + 1, 1
    else:
        year, month = local_start.year, local_start.month + 1
    day = min(subscription.cycle_anchor_day, calendar.monthrange(year, month)[1])
    boundary = datetime(
        year,
        month,
        day,
        local_start.hour,
        local_start.minute,
        local_start.second,
        local_start.microsecond,
        tzinfo=local_start.tzinfo,
    ).astimezone(subscription.starts_at.tzinfo)
    return subscription.starts_at, min(boundary, subscription.ends_at)


def _digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def backfill_accounts(apps, schema_editor):
    Subscription = apps.get_model("plans", "Subscription")
    Account = apps.get_model("quotas", "QuotaAccount")
    Ledger = apps.get_model("quotas", "QuotaLedgerEntry")
    for subscription in Subscription.objects.order_by("id").iterator():
        values = _amounts(subscription.entitlement_snapshot)
        for quota_type, source_key, unit, scope in DEFINITIONS:
            cycle_start = cycle_end = None
            if scope == "account_cycle":
                cycle_start, cycle_end = _cycle(subscription)
            cycle_marker = cycle_start.isoformat() if cycle_start else "subscription"
            batch_key = uuid.uuid5(
                BATCH_NAMESPACE, f"{subscription.pk}|{quota_type}|{cycle_marker}"
            )
            account_id = uuid.uuid5(ACCOUNT_NAMESPACE, str(batch_key))
            amount = values[source_key]
            account, created = Account.objects.get_or_create(
                subscription_id=subscription.pk,
                quota_type=quota_type,
                batch_key=batch_key,
                defaults={
                    "id": account_id,
                    "user_id": subscription.user_id,
                    "scope": scope,
                    "unit": unit,
                    "entitlement_amount": amount,
                    "cycle_started_at": cycle_start,
                    "cycle_ends_at": cycle_end,
                },
            )
            if not created:
                if (
                    account.user_id != subscription.user_id
                    or account.entitlement_amount != amount
                    or account.scope != scope
                    or account.unit != unit
                    or account.cycle_started_at != cycle_start
                    or account.cycle_ends_at != cycle_end
                ):
                    raise RuntimeError("existing quota account conflicts with immutable snapshot")
                continue
            payload = {
                "operation": "initialize",
                "subscription_id": str(subscription.pk),
                "account_id": str(account.pk),
                "quota_type": quota_type,
                "amount": amount,
                "cycle_started_at": cycle_start,
                "cycle_ends_at": cycle_end,
            }
            request_digest = _digest(payload)
            key_digest = _digest({"migration": "quotas-0003", **payload})
            entry = Ledger.objects.create(
                id=uuid.uuid5(LEDGER_NAMESPACE, f"{account.pk}|1"),
                account_id=account.pk,
                user_id=subscription.user_id,
                subscription_id=subscription.pk,
                quota_type=quota_type,
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
                safe_reason="Subscription quota initialized.",
                actor_id=subscription.opened_by_id,
                request_id=subscription.request_id,
                idempotency_key_version=1,
                idempotency_key_digest=key_digest,
                idempotency_scope_digest=_digest({"scope": payload}),
                request_digest=request_digest,
            )
            Account.objects.filter(pk=account.pk).update(
                available=amount,
                ledger_sequence=1,
                last_ledger_entry_id=entry.pk,
                version=2,
                updated_at=timezone.now(),
            )


class Migration(migrations.Migration):
    atomic = True
    dependencies = [
        ("plans", "0007_subscription_guards"),
        ("quotas", "0002_postgresql_guards"),
    ]
    operations = [migrations.RunPython(backfill_accounts, migrations.RunPython.noop)]
