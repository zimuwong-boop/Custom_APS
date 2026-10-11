.PHONY: setup check python-check frontend-check e2e frontend-dev docs-check lock

setup:
	./scripts/setup.sh

check: python-check frontend-check docs-check migration-check

python-check:
	.venv/bin/python -m pip check
	.venv/bin/ruff check aps config manage.py tests scripts
	.venv/bin/ruff format --check aps config manage.py tests scripts
	.venv/bin/python -m pytest

frontend-check:
	./scripts/npm run lint
	./scripts/npm run format:check
	./scripts/npm run test
	./scripts/npm run build

e2e:
	./scripts/npm run test:e2e

frontend-dev:
	./scripts/npm run dev

docs-check:
	.venv/bin/python Docs/tools/check_docs.py

lock:
	.venv/bin/python scripts/lock_requirements.py

backend-dev:
	.venv/bin/python manage.py migrate
	.venv/bin/python manage.py init_system
	.venv/bin/python manage.py runserver 127.0.0.1:8000

init:
	.venv/bin/python manage.py migrate
	.venv/bin/python manage.py init_system

serve:
	.venv/bin/python manage.py runserver 127.0.0.1:8000

build:
	./scripts/npm run build

migration-check:
	.venv/bin/python manage.py makemigrations --check --dry-run
	.venv/bin/python manage.py check
