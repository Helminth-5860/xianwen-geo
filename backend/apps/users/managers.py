from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from .phone_numbers import normalize_phone

if TYPE_CHECKING:
    from .models import User


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, phone: str, password: str, **extra_fields: Any) -> "User":
        if not password:
            raise ValueError("必须设置密码。")

        normalized_phone = normalize_phone(phone)
        user = self.model(phone=normalized_phone, **extra_fields)
        user.synchronize_active_state()
        validate_password(password, user)
        user.set_password(password)
        user.full_clean(exclude={"password"})
        user.save(using=self._db)
        return user

    def create_user(self, phone: str, password: str, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, password, **extra_fields)

    def create_superuser(self, phone: str, password: str, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("account_status", self.model.AccountStatus.ACTIVE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("超级管理员必须设置 is_staff=True。")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("超级管理员必须设置 is_superuser=True。")
        return self._create_user(phone, password, **extra_fields)

    @transaction.atomic
    def set_account_status(self, user_id, account_status: str) -> "User":
        user = self.select_for_update().get(pk=user_id)
        user.account_status = account_status
        user.synchronize_active_state()
        user.full_clean()
        user.save(update_fields=["account_status", "is_active", "updated_at"])
        return user
