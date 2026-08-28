from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import PlatformAccount
from .security import PublishingCredentialError, decrypt_secret
from .wechat_component import WechatComponentUnavailable, refresh_authorizer_account


class PlatformCredentialRuntimeUnavailable(RuntimeError):
    """The account remains authorized but its temporary runtime token cannot be refreshed now."""


def platform_credentials(account: PlatformAccount) -> dict:
    if not account.secret_ciphertext:
        raise PublishingCredentialError("授权凭证不存在")

    if account.platform_key == "wechat" and (
        account.session_expires_at is None
        or account.session_expires_at <= timezone.now() + timedelta(minutes=10)
    ):
        try:
            refreshed = refresh_authorizer_account(account)
        except WechatComponentUnavailable as exc:
            # Missing component ticket/network availability is a platform-runtime problem,
            # not proof that the customer's official-account authorization was revoked.
            raise PlatformCredentialRuntimeUnavailable("wechat_refresh_unavailable") from exc
        if not refreshed:
            raise PublishingCredentialError("微信公众号授权凭证无法刷新")
        account.refresh_from_db()

    return decrypt_secret(account.secret_ciphertext)
