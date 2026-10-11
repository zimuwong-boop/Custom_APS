from config.settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
    }
}
WHITENOISE_AUTOREFRESH = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "loggers": {"aps.requests": {"handlers": ["null"], "propagate": False}},
}

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
