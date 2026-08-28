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
INSTALLED_APPS = [*INSTALLED_APPS, "apps.website_audits", "apps.publishing"]

# 自动发文平台必须逐个平台经过真实账号验证后才开放授权；默认全部保持“适配验证中”。
PUBLISHING_ENABLED_PLATFORM_KEYS = tuple(
    item.strip().lower()
    for item in os.getenv("PUBLISHING_ENABLED_PLATFORM_KEYS", "").split(",")
    if item.strip()
)
PUBLISHING_AUTH_SESSION_TTL_SECONDS = int(os.getenv("PUBLISHING_AUTH_SESSION_TTL_SECONDS", "900"))
PUBLISHING_CREDENTIAL_ENCRYPTION_KEY = os.getenv(
    "PUBLISHING_CREDENTIAL_ENCRYPTION_KEY", ""
).strip()
if PUBLISHING_AUTH_SESSION_TTL_SECONDS < 300 or PUBLISHING_AUTH_SESSION_TTL_SECONDS > 3600:
    raise ImproperlyConfigured(
        "PUBLISHING_AUTH_SESSION_TTL_SECONDS must be between 300 and 3600."
    )

WEBSITE_AUDIT_MAX_PAGES = int(os.getenv("WEBSITE_AUDIT_MAX_PAGES", "200"))
WEBSITE_AUDIT_MAX_SITEMAPS = int(os.getenv("WEBSITE_AUDIT_MAX_SITEMAPS", "20"))
WEBSITE_AUDIT_MAX_RESPONSE_BYTES = int(
    os.getenv("WEBSITE_AUDIT_MAX_RESPONSE_BYTES", str(4 * 1024 * 1024))
)
# WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS is the hard budget for the whole static crawl,
# not a fresh timeout for every URL. Keep single requests much shorter so one slow
# origin cannot consume the full customer-facing scan budget by itself.
WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS = int(os.getenv("WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS", "75"))
WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS = int(
    os.getenv("WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS", "8")
)
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

WEBSITE_AUDIT_SEMANTIC_ENABLED = os.getenv(
    "WEBSITE_AUDIT_SEMANTIC_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
WEBSITE_AUDIT_SEMANTIC_MAX_PAGES = int(
    os.getenv("WEBSITE_AUDIT_SEMANTIC_MAX_PAGES", "16")
)
WEBSITE_AUDIT_SEMANTIC_MAX_CHARS_PER_PAGE = int(
    os.getenv("WEBSITE_AUDIT_SEMANTIC_MAX_CHARS_PER_PAGE", "5000")
)
WEBSITE_AUDIT_SEMANTIC_MAX_TOTAL_CHARS = int(
    os.getenv("WEBSITE_AUDIT_SEMANTIC_MAX_TOTAL_CHARS", "70000")
)
WEBSITE_AUDIT_SEMANTIC_MAX_KEYWORDS = int(
    os.getenv("WEBSITE_AUDIT_SEMANTIC_MAX_KEYWORDS", "50")
)
WEBSITE_AUDIT_SEMANTIC_MAX_QUESTIONS = int(
    os.getenv("WEBSITE_AUDIT_SEMANTIC_MAX_QUESTIONS", "30")
)

for name in (
    "WEBSITE_AUDIT_MAX_PAGES",
    "WEBSITE_AUDIT_MAX_SITEMAPS",
    "WEBSITE_AUDIT_MAX_RESPONSE_BYTES",
    "WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS",
    "WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS",
    "WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS",
    "WEBSITE_AUDIT_BROWSER_MAX_PAGES",
    "WEBSITE_AUDIT_BROWSER_TIMEOUT_SECONDS",
    "WEBSITE_AUDIT_BROWSER_MAX_REQUESTS",
    "WEBSITE_AUDIT_BROWSER_MAX_DOM_CHARACTERS",
    "WEBSITE_AUDIT_SEMANTIC_MAX_PAGES",
    "WEBSITE_AUDIT_SEMANTIC_MAX_CHARS_PER_PAGE",
    "WEBSITE_AUDIT_SEMANTIC_MAX_TOTAL_CHARS",
    "WEBSITE_AUDIT_SEMANTIC_MAX_KEYWORDS",
    "WEBSITE_AUDIT_SEMANTIC_MAX_QUESTIONS",
):
    if globals()[name] <= 0:
        raise ImproperlyConfigured(f"{name} must be positive.")
if WEBSITE_AUDIT_MAX_PAGES > 1000:
    raise ImproperlyConfigured("WEBSITE_AUDIT_MAX_PAGES must not exceed 1000.")
if WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS > 30:
    raise ImproperlyConfigured("WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS must not exceed 30.")
if WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS > 300:
    raise ImproperlyConfigured("WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS must not exceed 300.")
if WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS > WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS:
    raise ImproperlyConfigured(
        "WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS must not exceed WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS."
    )
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
if WEBSITE_AUDIT_SEMANTIC_MAX_PAGES > 50:
    raise ImproperlyConfigured("WEBSITE_AUDIT_SEMANTIC_MAX_PAGES must not exceed 50.")
if WEBSITE_AUDIT_SEMANTIC_MAX_CHARS_PER_PAGE > 20000:
    raise ImproperlyConfigured(
        "WEBSITE_AUDIT_SEMANTIC_MAX_CHARS_PER_PAGE must not exceed 20000."
    )
if WEBSITE_AUDIT_SEMANTIC_MAX_TOTAL_CHARS > 200000:
    raise ImproperlyConfigured(
        "WEBSITE_AUDIT_SEMANTIC_MAX_TOTAL_CHARS must not exceed 200000."
    )
if WEBSITE_AUDIT_SEMANTIC_MAX_KEYWORDS > 200:
    raise ImproperlyConfigured("WEBSITE_AUDIT_SEMANTIC_MAX_KEYWORDS must not exceed 200.")
if WEBSITE_AUDIT_SEMANTIC_MAX_QUESTIONS > 100:
    raise ImproperlyConfigured("WEBSITE_AUDIT_SEMANTIC_MAX_QUESTIONS must not exceed 100.")
