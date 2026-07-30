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
