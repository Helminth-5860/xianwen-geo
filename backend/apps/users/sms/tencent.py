from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from django.conf import settings
from requests import RequestException, Timeout
from tencentcloud.common import credential  # type: ignore[import-untyped]
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (  # type: ignore[import-untyped]
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile  # type: ignore[import-untyped]
from tencentcloud.common.profile.http_profile import HttpProfile  # type: ignore[import-untyped]
from tencentcloud.common.retry import NoopRetryer  # type: ignore[import-untyped]
from tencentcloud.sms.v20210111 import models, sms_client  # type: ignore[import-untyped]

from .exceptions import SmsServiceUnavailable
from .purposes import SmsPurpose

TENCENT_SMS_ENDPOINT = "sms.tencentcloudapi.com"
TENCENT_SMS_API_VERSION = "2021-01-11"
TENCENT_SMS_PROVIDER_KEY = "tencent"
SAFE_PROVIDER_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

TEMPLATE_SETTING_BY_PURPOSE: Mapping[SmsPurpose, str] = {
    SmsPurpose.REGISTER: "SMS_TEMPLATE_REGISTER",
    SmsPurpose.LOGIN: "SMS_TEMPLATE_LOGIN",
    SmsPurpose.PASSWORD_RESET: "SMS_TEMPLATE_SECURITY",
    SmsPurpose.ADMIN_STEP_UP: "SMS_TEMPLATE_SECURITY",
}


class SmsProviderErrorCategory(StrEnum):
    AUTH_OR_PERMISSION = "AUTH_OR_PERMISSION"
    RATE_OR_QUOTA = "RATE_OR_QUOTA"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_REQUEST = "INVALID_REQUEST"
    TEMPLATE_OR_SIGN = "TEMPLATE_OR_SIGN"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_NETWORK = "PROVIDER_NETWORK"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    UNKNOWN_PROVIDER_FAILURE = "UNKNOWN_PROVIDER_FAILURE"


class SmsProviderError(SmsServiceUnavailable):
    def __init__(
        self,
        category: SmsProviderErrorCategory,
        *,
        provider_code: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__()
        self.category = category
        self.provider_code = _safe_provider_text(provider_code)
        self.provider_request_id = _safe_provider_text(provider_request_id)


@dataclass(frozen=True, repr=False)
class TencentSmsConfig:
    secret_id: str
    secret_key: str
    app_id: str
    sign_name: str
    region: str
    timeout_seconds: int
    template_ids: Mapping[SmsPurpose, str]


class TencentSmsClient(Protocol):
    def SendSms(self, request: models.SendSmsRequest) -> object: ...


TencentClientFactory = Callable[[TencentSmsConfig], TencentSmsClient]


def _safe_provider_text(value: object) -> str | None:
    return value if isinstance(value, str) and SAFE_PROVIDER_CODE.fullmatch(value) else None


def _configuration_failure(name: str) -> SmsProviderError:
    return SmsProviderError(
        SmsProviderErrorCategory.INVALID_CONFIGURATION,
        provider_code=name,
    )


def _required_setting(name: str) -> str:
    value = getattr(settings, name, "")
    if not isinstance(value, str) or not value.strip():
        raise _configuration_failure(name)
    return value.strip()


def _config_from_settings() -> TencentSmsConfig:
    if getattr(settings, "ENABLE_REAL_SMS", False) is not True:
        raise _configuration_failure("ENABLE_REAL_SMS")
    timeout = getattr(settings, "SMS_PROVIDER_TIMEOUT_SECONDS", None)
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise _configuration_failure("SMS_PROVIDER_TIMEOUT_SECONDS")
    templates = {
        purpose: _required_setting(setting_name)
        for purpose, setting_name in TEMPLATE_SETTING_BY_PURPOSE.items()
    }
    return TencentSmsConfig(
        secret_id=_required_setting("SMS_SECRET_ID"),
        secret_key=_required_setting("SMS_SECRET_KEY"),
        app_id=_required_setting("SMS_APP_ID"),
        sign_name=_required_setting("SMS_SIGN_NAME"),
        region=_required_setting("SMS_REGION"),
        timeout_seconds=timeout,
        template_ids=templates,
    )


def _default_client_factory(config: TencentSmsConfig) -> TencentSmsClient:
    http_profile = HttpProfile(
        protocol="https",
        endpoint=TENCENT_SMS_ENDPOINT,
        reqMethod="POST",
        reqTimeout=config.timeout_seconds,
    )
    client_profile = ClientProfile(
        httpProfile=http_profile,
        retryer=NoopRetryer(),
    )
    configured_credential = credential.Credential(config.secret_id, config.secret_key)
    return sms_client.SmsClient(configured_credential, config.region, client_profile)


def _timeout_message(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.casefold()
    return "timeout" in normalized or "timed out" in normalized


def _category_for_provider_code(
    provider_code: str | None,
    *,
    provider_message: object = None,
) -> SmsProviderErrorCategory:
    code = (provider_code or "").casefold()
    if code.startswith(("authfailure", "unauthorizedoperation")):
        return SmsProviderErrorCategory.AUTH_OR_PERMISSION
    if code.startswith(("requestlimitexceeded", "limitexceeded")):
        return SmsProviderErrorCategory.RATE_OR_QUOTA
    if "template" in code or "sign" in code:
        return SmsProviderErrorCategory.TEMPLATE_OR_SIGN
    if code.startswith(("invalidparameter", "missingparameter")):
        return SmsProviderErrorCategory.INVALID_REQUEST
    if code in {"clientparamserror", "clientprofileerror"}:
        return SmsProviderErrorCategory.INVALID_CONFIGURATION
    if code == "clientnetworkerror":
        if _timeout_message(provider_message):
            return SmsProviderErrorCategory.PROVIDER_TIMEOUT
        return SmsProviderErrorCategory.PROVIDER_NETWORK
    if code == "servernetworkerror":
        return SmsProviderErrorCategory.PROVIDER_NETWORK
    if (
        code.startswith("internalerror")
        or code.startswith("failedoperation")
        or code
        in {
            "resourceunavailable",
            "serviceunavailable",
        }
    ):
        return SmsProviderErrorCategory.PROVIDER_UNAVAILABLE
    return SmsProviderErrorCategory.UNKNOWN_PROVIDER_FAILURE


class TencentSmsProvider:
    def __init__(
        self,
        config: TencentSmsConfig,
        *,
        client_factory: TencentClientFactory = _default_client_factory,
    ) -> None:
        self._config = config
        self._client = client_factory(config)

    @classmethod
    def from_settings(
        cls,
        *,
        client_factory: TencentClientFactory = _default_client_factory,
    ) -> TencentSmsProvider:
        return cls(_config_from_settings(), client_factory=client_factory)

    @property
    def locally_available(self) -> bool:
        return True

    def send_verification_code(
        self,
        *,
        phone: str,
        purpose: SmsPurpose,
        code: str,
        expires_in: int,
    ) -> None:
        template_id = self._config.template_ids.get(purpose)
        if not template_id:
            setting_name = TEMPLATE_SETTING_BY_PURPOSE.get(purpose, "SMS_TEMPLATE_UNKNOWN")
            raise _configuration_failure(setting_name)
        if type(expires_in) is not int or expires_in <= 0:
            raise SmsProviderError(SmsProviderErrorCategory.INVALID_REQUEST)

        request = models.SendSmsRequest()
        request.PhoneNumberSet = [phone]
        request.SmsSdkAppId = self._config.app_id
        request.TemplateId = template_id
        request.SignName = self._config.sign_name
        request.TemplateParamSet = [code, str(math.ceil(expires_in / 60))]
        request.ExtendCode = ""
        request.SessionContext = ""
        request.SenderId = ""

        try:
            response = self._client.SendSms(request)
        except TencentCloudSDKException as exc:
            provider_code = _safe_provider_text(exc.get_code())
            raise SmsProviderError(
                _category_for_provider_code(
                    provider_code,
                    provider_message=exc.get_message(),
                ),
                provider_code=provider_code,
                provider_request_id=exc.get_request_id(),
            ) from None
        except (Timeout, TimeoutError):
            raise SmsProviderError(SmsProviderErrorCategory.PROVIDER_TIMEOUT) from None
        except RequestException:
            raise SmsProviderError(SmsProviderErrorCategory.PROVIDER_NETWORK) from None
        except Exception:
            raise SmsProviderError(SmsProviderErrorCategory.UNKNOWN_PROVIDER_FAILURE) from None

        statuses = getattr(response, "SendStatusSet", None)
        if not isinstance(statuses, (list, tuple)) or len(statuses) != 1:
            raise SmsProviderError(
                SmsProviderErrorCategory.UNKNOWN_PROVIDER_FAILURE,
                provider_request_id=getattr(response, "RequestId", None),
            )
        status = statuses[0]
        status_code = _safe_provider_text(getattr(status, "Code", None))
        status_phone = getattr(status, "PhoneNumber", None)
        if status_phone != phone or status_code is None:
            raise SmsProviderError(
                SmsProviderErrorCategory.UNKNOWN_PROVIDER_FAILURE,
                provider_request_id=getattr(response, "RequestId", None),
            )
        if status_code != "Ok":
            raise SmsProviderError(
                _category_for_provider_code(status_code),
                provider_code=status_code,
                provider_request_id=getattr(response, "RequestId", None),
            )
