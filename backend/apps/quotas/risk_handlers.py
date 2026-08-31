import hmac

from rest_framework.exceptions import NotFound

from apps.admin_rbac.risk_handlers import HandlerResult, HandlerSpec

from .exceptions import QuotaIdempotencyConflict
from .idempotency import IdempotencyDigests, canonical_digest
from .models import QuotaAccount
from .selectors import scoped_account_or_404
from .serializers import QuotaAdjustmentPayloadSerializer
from .services import adjust_quota_account


def quota_account_version(user, context, target_id, lock):
    visible = scoped_account_or_404(user, context, target_id)
    query = QuotaAccount.objects.all()
    if lock:
        subscription_model = visible.subscription.__class__
        subscription_model.objects.select_for_update().get(pk=visible.subscription_id)
        query = query.select_for_update()
    try:
        return query.only("version").get(pk=visible.pk).version
    except QuotaAccount.DoesNotExist as exc:
        raise NotFound from exc


def _handler(action):
    def execute(context):
        before_account = scoped_account_or_404(
            context.requester, context.request.admin_context, context.target_id
        )
        before = {
            "available": before_account.available,
            "frozen": before_account.frozen,
            "version": before_account.version,
        }
        payload = context.payload
        expected_request_digest = canonical_digest(
            {"amount": payload["amount"], "reason": payload["reason"]}
        )
        if not hmac.compare_digest(expected_request_digest, payload["request_digest"]):
            raise QuotaIdempotencyConflict
        digests = IdempotencyDigests(
            key_version=payload["idempotency_key_version"],
            key_digest=payload["idempotency_key_digest"],
            scope_digest=payload["idempotency_scope_digest"],
            request_digest=payload["request_digest"],
        )
        account, entry = adjust_quota_account(
            requester=context.requester,
            admin_context=context.request.admin_context,
            account_id=context.target_id,
            expected_version=context.target_version,
            action=action,
            amount=payload["amount"],
            reason=payload["reason"],
            digests=digests,
            request_id=context.request.request_id,
        )
        after = {
            "available": account.available,
            "frozen": account.frozen,
            "version": account.version,
        }
        return HandlerResult(
            before,
            after,
            {
                "account_id": str(account.pk),
                "ledger_entry_id": str(entry.pk),
                **after,
            },
            account.user,
        )

    return execute


QUOTA_HANDLER_SPECS = {
    action_key: HandlerSpec(
        "quotas.adjust",
        False,
        QuotaAdjustmentPayloadSerializer,
        quota_account_version,
        _handler(action),
    )
    for action_key, action in {
        "quota.grant": "grant",
        "quota.compensate": "compensate",
        "quota.refund": "refund",
        "quota.manual_deduct": "manual_deduct",
    }.items()
}

QUOTA_HANDLER_REGISTRY = {
    action_key: spec.execute for action_key, spec in QUOTA_HANDLER_SPECS.items()
}
