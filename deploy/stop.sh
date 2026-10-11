#!/bin/sh
set -eu
DEPLOY_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DEPLOY_DIR"
docker compose --project-name "${APS_PROJECT_NAME:-custom-aps-demo}" stop
