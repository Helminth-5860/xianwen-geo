# ruff: noqa: F403, F405
import os

from .test import *

DATABASES = {
    "default": database_from_url(
        os.environ["DATABASE_URL"],
        conn_max_age=0,
    )
}
