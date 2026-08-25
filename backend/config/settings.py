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

WEBSITE_AUDIT_BROWSER_ENABLED = os.getenv("WEBSITE_AUDIT_BROWSER_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEBSITE_AUDIT_BROWSER_MAX_PAGES = int(os.getenv("WEBSITE_AUDIT_BROWSER_MAX_PAGES", "8"))
WEBSITE_AUDIT_BROWSER_TIMEOUT_SECONDS = int(
    os.getenv("WEBSITE_AUDIT_BROWSER_TIMEOUT_SECONDS", "30")
)
WEBSITE_AUDIT_BROWSER_SETTLE_MS = int(os.getenv("WEBSITE_AUDIT_BROWSER_SETTLE_MS", "1200"))
WEBSITE_AUDIT_BROWSER_MAX_REQUESTS = int(os.getenv("WEBSITE_AUDIT_BROWSER_MAX_REQUESTS", "300"))
WEBSITE_AUDIT_BROWSER_MAX_DOM_CHARACTERS = int(
    os.getenv("WEBSITE_AUDIT_BROWSER_MAX_DOM_CHARACTERS", str(2_000_000))
)
WEBSITE_AUDIT_BROWSER_PROFILES = tuple(
    item.strip().lower()
    for item in os.getenv("WEBSITE_AUDIT_BROWSER_PROFILES", "mobile,desktop").split(",")
    if item.strip()
)

for name in (
    "WEBSITE_AUDIT_MAX_PAGES",
    "WEBSITE_AUDIT_MAX_SITEMAPS",
    "WEBSITE_AUDIT_MAX_RESPONSE_BYTES",
    "WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS",
    "WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS",
    "WEBSITE_AUDIT_BROWSER_MAX_PAGES",
    "WEBSITE_AUDIT_BROWSER_TIMEOUT_SECONDS",
    "WEBSITE_AUDIT_BROWSER_MAX_REQUESTS",
    "WEBSITE_AUDIT_BROWSER_MAX_DOM_CHARACTERS",
):
    if globals()[name] <= 0:
        raise ImproperlyConfigured(f"{name} must be positive.")
if WEBSITE_AUDIT_MAX_PAGES > 1000:
    raise ImproperlyConfigured("WEBSITE_AUDIT_MAX_PAGES must not exceed 1000.")
if WEBSITE_AUDIT_BROWSER_MAX_PAGES > 50:
    raise ImproperlyConfigured("WEBSITE_AUDIT_BROWSER_MAX_PAGES must not exceed 50.")
if WEBSITE_AUDIT_BROWSER_TIMEOUT_SECONDS > 120:
    raise ImproperlyConfigured("WEBSITE_AUDIT_BROWSER_TIMEOUT_SECONDS must not exceed 120.")
if WEBSITE_AUDIT_BROWSER_SETTLE_MS < 0 or WEBSITE_AUDIT_BROWSER_SETTLE_MS > 10000:
    raise ImproperlyConfigured("WEBSITE_AUDIT_BROWSER_SETTLE_MS must be between 0 and 10000.")
if WEBSITE_AUDIT_BROWSER_MAX_REQUESTS > 2000:
    raise ImproperlyConfigured("WEBSITE_AUDIT_BROWSER_MAX_REQUESTS must not exceed 2000.")
if not WEBSITE_AUDIT_BROWSER_PROFILES or any(
    item not in {"mobile", "desktop"} for item in WEBSITE_AUDIT_BROWSER_PROFILES
):
    raise ImproperlyConfigured(
        "WEBSITE_AUDIT_BROWSER_PROFILES must contain only mobile and/or desktop."
    )
