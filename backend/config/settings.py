import os
from importlib import import_module

from django.core.exceptions import ImproperlyConfigured

environment = os.getenv("APP_ENV", "local").strip().lower()
settings_modules = {
    "local": "config.django_settings.local",
    "test": "config.django_settings.test",
    "production": "config.django_settings.production",
}

module_path = settings_modules.get(environment)
if module_path is None:
    allowed = ", ".join(settings_modules)
    raise ImproperlyConfigured(f"APP_ENV must be one of: {allowed}.")

settings_module = import_module(module_path)
for setting_name in dir(settings_module):
    if setting_name.isupper():
        globals()[setting_name] = getattr(settings_module, setting_name)

# 官网深度检测在所有运行环境共用同一套扫描内核；网络安全策略复用 web_sources。
INSTALLED_APPS = [*INSTALLED_APPS, "apps.website_audits"]
WEBSITE_AUDIT_MAX_PAGES = int(os.getenv("WEBSITE_AUDIT_MAX_PAGES", "200"))
WEBSITE_AUDIT_MAX_SITEMAPS = int(os.getenv("WEBSITE_AUDIT_MAX_SITEMAPS", "20"))
WEBSITE_AUDIT_MAX_RESPONSE_BYTES = int(
    os.getenv("WEBSITE_AUDIT_MAX_RESPONSE_BYTES", str(4 * 1024 * 1024))
)
WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS = int(os.getenv("WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS", "25"))
WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS = int(
    os.getenv("WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS", "100000")
)
WEBSITE_AUDIT_USER_AGENT = os.getenv("WEBSITE_AUDIT_USER_AGENT", "XianwenWebsiteAudit/1.0").strip()

for name in (
    "WEBSITE_AUDIT_MAX_PAGES",
    "WEBSITE_AUDIT_MAX_SITEMAPS",
    "WEBSITE_AUDIT_MAX_RESPONSE_BYTES",
    "WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS",
    "WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS",
):
    if globals()[name] <= 0:
        raise ImproperlyConfigured(f"{name} must be positive.")
if WEBSITE_AUDIT_MAX_PAGES > 1000:
    raise ImproperlyConfigured("WEBSITE_AUDIT_MAX_PAGES must not exceed 1000.")
