#!/bin/sh
set -eu
if test "${1:-}" != '--yes'; then
  echo 'Replace this deployment database with the initial demo (a safety backup is retained):'
  echo '  ./reset-demo.sh --yes'
  exit 1
fi
DEPLOY_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DEPLOY_DIR"
PROJECT="${APS_PROJECT_NAME:-custom-aps-demo}"
ARCH=$(docker info --format '{{.Architecture}}')
case "$ARCH" in aarch64|arm64) ARCH=arm64 ;; x86_64|amd64) ARCH=amd64 ;; *) exit 1 ;; esac
export APS_IMAGE_ARCH="$ARCH"
docker compose --project-name "$PROJECT" stop aps
docker compose --project-name "$PROJECT" run --rm --no-deps --entrypoint python aps /opt/deploy/reset_database.py
docker compose --project-name "$PROJECT" up -d --wait --wait-timeout 120
