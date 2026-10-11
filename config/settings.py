import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-only-custom-aps")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.staticfiles", "aps"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "aps.middleware.RequestLoggingMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", str(BASE_DIR / "data.sqlite3")),
        "OPTIONS": {"timeout": 10, "transaction_mode": "IMMEDIATE"},
    }
}
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
LANGUAGE_CODE = "zh-hans"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_ROOT = BASE_DIR / "frontend/dist"
CSRF_FAILURE_VIEW = "aps.api.csrf_failure"
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
# Railway terminates HTTPS before forwarding to the application.
# Trust its proxy header only for deployments that explicitly enable this setting.
if os.environ.get("TRUST_PROXY_HEADERS") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    ALLOWED_HOSTS += ["healthcheck.railway.app"]

railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if railway_domain:
    ALLOWED_HOSTS += [railway_domain]
    CSRF_TRUSTED_ORIGINS += [f"https://{railway_domain}"]

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
APPEND_SLASH = False
GRAPH_NODE_BUDGET = int(os.environ.get("GRAPH_NODE_BUDGET", "20000"))
GRAPH_EDGE_BUDGET = int(os.environ.get("GRAPH_EDGE_BUDGET", "50000"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"aps.requests": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
