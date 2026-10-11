#!/bin/sh
set -eu
DEPLOY_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DEPLOY_DIR"
command -v docker >/dev/null 2>&1 || { echo 'Install and start Docker with Docker Compose first.' >&2; exit 1; }
ARCH=$(docker info --format '{{.Architecture}}')
case "$ARCH" in
  aarch64|arm64) ARCH=arm64 ;;
  x86_64|amd64) ARCH=amd64 ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac
export APS_IMAGE_ARCH="$ARCH"
ARCHIVE="images/custom-aps-demo-$ARCH.tar.gz"
if test -f "$ARCHIVE"; then
  docker load -i "$ARCHIVE"
elif ! docker image inspect "custom-aps-demo:$ARCH" >/dev/null 2>&1; then
  echo "Missing $ARCHIVE. Run ./build-image.sh to build for this machine." >&2
  exit 1
fi
if test ! -f .env; then
  (umask 077; docker run --rm --network none --entrypoint python "custom-aps-demo:$ARCH" -c 'import secrets; print("SECRET_KEY=" + secrets.token_urlsafe(48))' > .env)
fi
SAVED_PORT=$(sed -n 's/^APS_PORT=//p' .env | tail -n 1)
export APS_PORT="${APS_PORT:-${SAVED_PORT:-8000}}"
case "$APS_PORT" in *[!0-9]*|'') echo "Invalid APS_PORT" >&2; exit 1 ;; esac
test "$APS_PORT" -ge 1 && test "$APS_PORT" -le 65535
if test "$SAVED_PORT" != "$APS_PORT"; then
  sed '/^APS_PORT=/d' .env > .env.tmp
  printf 'APS_PORT=%s\n' "$APS_PORT" >> .env.tmp
  chmod 600 .env.tmp
  mv .env.tmp .env
fi
docker compose --project-name "${APS_PROJECT_NAME:-custom-aps-demo}" up -d --wait --wait-timeout 120
printf 'Demo ready: http://127.0.0.1:%s\n' "$APS_PORT"
