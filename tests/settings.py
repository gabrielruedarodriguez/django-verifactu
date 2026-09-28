import os
from urllib.parse import urlsplit

from django_verifactu.aeat.domain import Party
from tests.certificates import fake_pkcs12

CERTIFICATE = fake_pkcs12()

SECRET_KEY = "test"
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django_verifactu",
    "tests.shop",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "tests.urls"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
# postgresql://user:password@host:port/name, for the concurrency tests.
if url := os.environ.get("VERIFACTU_TEST_POSTGRES"):
    parts = urlsplit(url)
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parts.path.lstrip("/"),
        "USER": parts.username,
        "PASSWORD": parts.password,
        "HOST": parts.hostname,
        "PORT": parts.port,
    }
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Europe/Madrid"
VERIFACTU = {
    "PRODUCTION": False,
    "SOFTWARE": {
        "producer": Party("Productor de prueba SL", tax_id="89890003T"),
        "name": "Facturador",
        "system_id": "FA",
        "version": "1.0",
        "multiple_taxpayers_possible": True,
    },
    "TAXPAYERS": {
        "89890001K": {"name": "Emisor de prueba SL", "certificate": CERTIFICATE, "password": "x"},
        "89890002E": {"name": "Otro emisor SL", "certificate": CERTIFICATE, "password": "x"},
    },
}
