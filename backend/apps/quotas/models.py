import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ProtectedQuerySet(models.QuerySet):
    def delete(self):
        raise RuntimeError("额度事实记录不能删除。")


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("额度流水不能修改。")

    def delete(self):
        raise RuntimeError("额度流水不能删除。")


class QuotaAccount(models.Model):  # noqa: DJ008
    class Scope(models.TextChoices):
        SUBSCRIPTION = "subscription", "订阅"
        ACCOUNT = "account", "账号"
        ACCOUNT_CYCLE = "account_cycle", "账号周期"

    class BatchType(models.TextChoices):
        PRIMARY = "primary", "套餐基础批次"
        CARRYOVER = "carryover", "保留额度批次"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="quota_accounts"
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="quota_accounts"
    )
    quota_type = models.CharField(max_length=100)
    scope = models.CharField(max_length=24, choices=Scope.choices)
    unit = models.CharField(max_length=32)
    batch_key = models.UUIDField(default=uuid.uuid4)
    batch_type = models.CharField(
        max_length=16,
        choices=BatchType.choices,
        default=BatchType.PRIMARY,
    )
    spendable_until = models.DateTimeField(null=True, blank=True)
    source_change = models.ForeignKey(
        "plans.SubscriptionChange",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="carryover_quota_accounts",
    )
    entitlement_amount = models.BigIntegerField()
    available = models.BigIntegerField(default=0)
    frozen = models.BigIntegerField(default=0)
    cycle_started_at = models.DateTimeField(null=True, blank=True)
    cycle_ends_at = models.DateTimeField(null=True, blank=True)
    ledger_sequence = models.BigIntegerField(default=0)
    last_ledger_entry = models.ForeignKey(
        "QuotaLedgerEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="latest_for_accounts",
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "quota_accounts"
        ordering = ("quota_type", "cycle_started_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "quota_type", "batch_key"),
                name="quota_account_unique_batch",
            ),
            models.UniqueConstraint(
                fields=("subscription", "quota_type"),
                condition=Q(batch_type="primary", cycle_started_at__isnull=True),
                name="quota_account_unique_noncycle",
            ),
            models.UniqueConstraint(
                fields=("subscription", "quota_type", "cycle_started_at"),
                condition=Q(batch_type="primary", cycle_started_at__isnull=False),
                name="quota_account_unique_cycle",
            ),
            models.CheckConstraint(
                condition=Q(entitlement_amount__gte=0), name="quota_entitlement_gte_0"
            ),
            models.CheckConstraint(condition=Q(available__gte=0), name="quota_available_gte_0"),
            models.CheckConstraint(condition=Q(frozen__gte=0), name="quota_frozen_gte_0"),
            models.CheckConstraint(
                condition=Q(ledger_sequence__gte=0), name="quota_sequence_gte_0"
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="quota_account_version_gte_1"),
            models.CheckConstraint(
                condition=(Q(cycle_started_at__isnull=True) & Q(cycle_ends_at__isnull=True))
                | (
                    Q(cycle_started_at__isnull=False)
                    & Q(cycle_ends_at__isnull=False)
                    & Q(cycle_started_at__lt=F("cycle_ends_at"))
                ),
                name="quota_account_cycle_window",
            ),
            models.CheckConstraint(
                condition=Q(scope="account_cycle", cycle_started_at__isnull=False)
                | (~Q(scope="account_cycle") & Q(cycle_started_at__isnull=True)),
                name="quota_account_scope_cycle",
            ),
            models.CheckConstraint(
                condition=Q(batch_type__in=("primary", "carryover")),
                name="quota_account_batch_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        batch_type="primary",
                        source_change__isnull=True,
                        spendable_until__isnull=True,
                    )
                    | Q(
                        batch_type="carryover",
                        source_change__isnull=False,
                        spendable_until__isnull=False,
                        entitlement_amount=0,
                    )
                ),
                name="quota_account_batch_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "quota_type"), name="quota_account_user_type_idx"),
            models.Index(
                fields=("subscription", "quota_type", "cycle_ends_at"),
                name="quota_account_cycle_idx",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("额度账户不能删除。")


class QuotaHoldGroup(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        OPEN = "open", "待结算"
        PARTIALLY_SETTLED = "partially_settled", "部分结算"
        SETTLED = "settled", "已结算"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="quota_hold_groups"
    )
    quota_type = models.CharField(max_length=100)
    business_type = models.CharField(max_length=64)
    business_id = models.UUIDField()
    requested_amount = models.BigIntegerField()
    consumed_amount = models.BigIntegerField(default=0)
    released_amount = models.BigIntegerField(default=0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    freeze_idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    freeze_idempotency_key_digest = models.CharField(max_length=64, unique=True)
    freeze_idempotency_scope_digest = models.CharField(max_length=64)
    freeze_request_digest = models.CharField(max_length=64)
    version = models.BigIntegerField(default=1)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "quota_hold_groups"
        ordering = ("-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "quota_type", "business_type", "business_id"),
                name="quota_hold_group_business_unique",
            ),
            models.CheckConstraint(
                condition=Q(requested_amount__gt=0), name="quota_hold_group_requested_gt_0"
            ),
            models.CheckConstraint(
                condition=Q(consumed_amount__gte=0), name="quota_hold_group_consumed_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(released_amount__gte=0), name="quota_hold_group_released_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(consumed_amount__lte=F("requested_amount") - F("released_amount")),
                name="quota_hold_group_total_lte",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="quota_hold_group_version_gte_1"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="open", consumed_amount=0, released_amount=0, settled_at__isnull=True)
                    | (
                        Q(status="partially_settled", settled_at__isnull=True)
                        & (Q(consumed_amount__gt=0) | Q(released_amount__gt=0))
                        & Q(consumed_amount__lt=F("requested_amount") - F("released_amount"))
                    )
                    | (
                        Q(status="settled", settled_at__isnull=False)
                        & Q(consumed_amount=F("requested_amount") - F("released_amount"))
                    )
                ),
                name="quota_hold_group_status_amounts",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "status", "created_at"), name="quota_hold_group_user_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("额度冻结组不能删除。")


class QuotaHold(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        OPEN = "open", "待结算"
        PARTIALLY_SETTLED = "partially_settled", "部分结算"
        SETTLED = "settled", "已结算"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(QuotaHoldGroup, on_delete=models.PROTECT, related_name="allocations")
    account = models.ForeignKey(QuotaAccount, on_delete=models.PROTECT, related_name="holds")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="quota_holds"
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="quota_holds"
    )
    quota_type = models.CharField(max_length=100)
    business_type = models.CharField(max_length=64)
    business_id = models.UUIDField()
    requested_amount = models.BigIntegerField()
    consumed_amount = models.BigIntegerField(default=0)
    released_amount = models.BigIntegerField(default=0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    freeze_idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    freeze_idempotency_key_digest = models.CharField(max_length=64, unique=True)
    freeze_idempotency_scope_digest = models.CharField(max_length=64)
    freeze_request_digest = models.CharField(max_length=64)
    version = models.BigIntegerField(default=1)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "quota_holds"
        ordering = ("-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("group", "account"),
                name="quota_hold_group_account_unique",
            ),
            models.CheckConstraint(
                condition=Q(requested_amount__gt=0), name="quota_hold_requested_gt_0"
            ),
            models.CheckConstraint(
                condition=Q(consumed_amount__gte=0), name="quota_hold_consumed_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(released_amount__gte=0), name="quota_hold_released_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(consumed_amount__lte=F("requested_amount") - F("released_amount")),
                name="quota_hold_total_lte_requested",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="quota_hold_version_gte_1"),
            models.CheckConstraint(
                condition=(
                    Q(status="open", consumed_amount=0, released_amount=0, settled_at__isnull=True)
                    | (
                        Q(status="partially_settled", settled_at__isnull=True)
                        & (Q(consumed_amount__gt=0) | Q(released_amount__gt=0))
                        & Q(consumed_amount__lt=F("requested_amount") - F("released_amount"))
                    )
                    | (
                        Q(status="settled", settled_at__isnull=False)
                        & Q(consumed_amount=F("requested_amount") - F("released_amount"))
                    )
                ),
                name="quota_hold_status_amounts",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "status", "created_at"), name="quota_hold_user_status_idx"
            ),
            models.Index(fields=("account", "status"), name="quota_hold_account_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("额度冻结记录不能删除。")


class QuotaLedgerEntry(models.Model):  # noqa: DJ008
    class Action(models.TextChoices):
        INITIALIZE = "initialize", "初始化"
        STORAGE_CAPACITY_RECONCILE = (
            "storage_capacity_reconcile",
            "\u5b58\u50a8\u5bb9\u91cf\u6536\u655b",
        )
        FREEZE = "freeze", "冻结"
        CONSUME = "consume", "扣除"
        RELEASE = "release", "返还"
        GRANT = "grant", "赠送"
        COMPENSATE = "compensate", "补偿"
        MANUAL_DEDUCT = "manual_deduct", "人工扣减"
        PLAN_CHANGE_FORFEIT = "plan_change_forfeit", "套餐变更清零"
        PLAN_CHANGE_TRANSFER_OUT = "plan_change_transfer_out", "套餐变更转出"
        PLAN_CHANGE_TRANSFER_IN = "plan_change_transfer_in", "套餐变更转入"
        CYCLE_FORFEIT = "cycle_forfeit", "Cycle forfeit"
        CYCLE_LATE_RELEASE_FORFEIT = "cycle_late_release_forfeit", "Late cycle release forfeit"
        EXPIRY_FORFEIT = "expiry_forfeit", "Expiry forfeit"
        EXPIRY_LATE_RELEASE_FORFEIT = "expiry_late_release_forfeit", "Late expiry release forfeit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        QuotaAccount, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    hold = models.ForeignKey(
        QuotaHold, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="quota_ledger_entries"
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="quota_ledger_entries"
    )
    quota_type = models.CharField(max_length=100)
    sequence = models.BigIntegerField()
    action = models.CharField(max_length=32, choices=Action.choices)
    available_before = models.BigIntegerField()
    available_delta = models.BigIntegerField()
    available_after = models.BigIntegerField()
    frozen_before = models.BigIntegerField()
    frozen_delta = models.BigIntegerField()
    frozen_after = models.BigIntegerField()
    account_version_before = models.BigIntegerField()
    account_version_after = models.BigIntegerField()
    business_type = models.CharField(max_length=64)
    business_id = models.UUIDField(null=True, blank=True)
    safe_reason = models.CharField(max_length=500, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="acted_quota_ledger_entries",
    )
    request_id = models.UUIDField()
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    idempotency_scope_digest = models.CharField(max_length=64)
    request_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "quota_ledger_entries"
        ordering = ("account_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("account", "sequence"), name="quota_ledger_account_sequence_unique"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1), name="quota_ledger_sequence_gte_1"
            ),
            models.CheckConstraint(
                condition=Q(available_after=F("available_before") + F("available_delta")),
                name="quota_ledger_available_formula",
            ),
            models.CheckConstraint(
                condition=Q(frozen_after=F("frozen_before") + F("frozen_delta")),
                name="quota_ledger_frozen_formula",
            ),
            models.CheckConstraint(
                condition=Q(available_after__gte=0), name="quota_ledger_available_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(frozen_after__gte=0), name="quota_ledger_frozen_gte_0"
            ),
            models.CheckConstraint(
                condition=Q(account_version_after=F("account_version_before") + 1),
                name="quota_ledger_version_step",
            ),
            models.CheckConstraint(
                condition=(
                    Q(action__in=("freeze", "consume", "release"), hold__isnull=False)
                    | (
                        Q(
                            action__in=(
                                "initialize",
                                "storage_capacity_reconcile",
                                "grant",
                                "compensate",
                                "manual_deduct",
                                "plan_change_forfeit",
                                "plan_change_transfer_out",
                                "plan_change_transfer_in",
                                "cycle_forfeit",
                                "cycle_late_release_forfeit",
                                "expiry_forfeit",
                                "expiry_late_release_forfeit",
                            )
                        )
                        & Q(hold__isnull=True)
                    )
                ),
                name="quota_ledger_hold_by_action",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "quota_type", "created_at"), name="quota_ledger_user_type_idx"
            ),
            models.Index(
                fields=("subscription", "created_at"), name="quota_ledger_subscription_idx"
            ),
            models.Index(fields=("hold", "sequence"), name="quota_ledger_hold_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("额度流水不能修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("额度流水不能删除。")


class QuotaTransfer(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change = models.ForeignKey(
        "plans.SubscriptionChange",
        on_delete=models.PROTECT,
        related_name="quota_transfers",
    )
    quota_type = models.CharField(max_length=100)
    amount = models.BigIntegerField()
    source_account = models.ForeignKey(
        QuotaAccount,
        on_delete=models.PROTECT,
        related_name="outgoing_transfers",
    )
    target_account = models.ForeignKey(
        QuotaAccount,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
    )
    transfer_out_entry = models.OneToOneField(
        QuotaLedgerEntry,
        on_delete=models.PROTECT,
        related_name="outgoing_transfer",
    )
    transfer_in_entry = models.OneToOneField(
        QuotaLedgerEntry,
        on_delete=models.PROTECT,
        related_name="incoming_transfer",
    )
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "quota_transfers"
        ordering = ("change_id", "quota_type", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("change", "source_account", "target_account"),
                name="quota_transfer_account_pair_unique",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="quota_transfer_amount_gt_0",
            ),
            models.CheckConstraint(
                condition=~Q(source_account=F("target_account")),
                name="quota_transfer_distinct_accounts",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("额度迁移记录不能删除。")


class QuotaCycleReset(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="quota_cycle_resets"
    )
    quota_type = models.CharField(max_length=100)
    boundary = models.DateTimeField()
    previous_account = models.OneToOneField(
        QuotaAccount, on_delete=models.PROTECT, related_name="outgoing_cycle_reset"
    )
    next_account = models.OneToOneField(
        QuotaAccount, on_delete=models.PROTECT, related_name="incoming_cycle_reset"
    )
    forfeit_entry = models.OneToOneField(
        QuotaLedgerEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cycle_reset_forfeit",
    )
    initialize_entry = models.OneToOneField(
        QuotaLedgerEntry, on_delete=models.PROTECT, related_name="cycle_reset_initialize"
    )
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "quota_cycle_resets"
        ordering = ("boundary", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "quota_type", "boundary"),
                name="quota_cycle_reset_unique_boundary",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise RuntimeError("Cycle reset facts cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Cycle reset facts cannot be deleted.")


class QuotaExpiryDisposition(models.Model):  # noqa: DJ008
    class Policy(models.TextChoices):
        ZERO = "zero", "Zero"
        FREEZE = "freeze", "Freeze"
        RETAIN = "retain", "Retain"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.OneToOneField(
        QuotaAccount, on_delete=models.PROTECT, related_name="expiry_disposition"
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="quota_expiry_dispositions"
    )
    policy = models.CharField(max_length=16, choices=Policy.choices)
    ledger_entry = models.OneToOneField(
        QuotaLedgerEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="expiry_disposition",
    )
    renewal_change = models.ForeignKey(
        "plans.SubscriptionChange",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quota_expiry_dispositions",
    )
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "quota_expiry_dispositions"
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(policy__in=("zero", "freeze", "retain")),
                name="quota_expiry_policy_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(policy="zero", renewal_change__isnull=True)
                    | Q(policy="freeze", ledger_entry__isnull=True, renewal_change__isnull=True)
                    | Q(policy="retain", ledger_entry__isnull=True)
                ),
                name="quota_expiry_evidence_consistent",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise RuntimeError("Expiry disposition facts cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Expiry disposition facts cannot be deleted.")
