"""Dependency installation smoke tests, not APS business acceptance tests."""

import importlib
import sqlite3
from contextlib import closing

import django
import pytest
from jsonschema import Draft202012Validator


def test_runtime_dependencies_import():
    for module in ("rest_framework", "django_filters", "gunicorn", "whitenoise"):
        importlib.import_module(module)
    assert django.VERSION[:2] == (5, 2)


def test_sqlite_foreign_keys_and_transactions():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO sample VALUES (1)")
        connection.rollback()
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone() == (0,)


@pytest.mark.django_db(transaction=True)
def test_django_supports_sqlite_immediate_transactions():
    from django.db import connection, transaction

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
    connection.close()


def test_graph_schema_validation_library():
    validator = Draft202012Validator(
        {"type": "object", "required": ["jobs"], "properties": {"jobs": {"type": "array"}}}
    )
    assert validator.is_valid({"jobs": []})
    assert not validator.is_valid({"jobs": "invalid"})
