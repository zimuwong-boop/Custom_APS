FROM node:24.21.0-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13.1-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBUG=0 DATABASE_PATH=/data/aps.sqlite3
WORKDIR /app
COPY requirements/base.txt /app/requirements/base.txt
RUN pip install --no-cache-dir --require-hashes -r requirements/base.txt \
    && groupadd --gid 10001 aps && useradd --uid 10001 --gid aps --no-create-home aps \
    && mkdir /data && chown aps:aps /data
COPY config/ /app/config/
COPY aps/ /app/aps/
COPY manage.py /app/manage.py
COPY scripts/container_entrypoint.sh scripts/backup_sqlite.py scripts/restore_sqlite.py scripts/benchmark.py /app/scripts/
COPY --from=frontend /build/frontend/dist /app/frontend/dist
RUN mkdir -p /app/staticfiles && python manage.py collectstatic --noinput && chmod +x scripts/container_entrypoint.sh
COPY deploy/demo-initial.sqlite3 /opt/deploy/demo-initial.sqlite3
COPY deploy/seed_database.py /opt/deploy/seed_database.py
COPY deploy/railway/entrypoint.sh /app/scripts/railway_entrypoint.sh
RUN chmod +x /app/scripts/railway_entrypoint.sh
USER aps
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/v1/health/ready',timeout=2)"
ENTRYPOINT ["/app/scripts/railway_entrypoint.sh"]
