#!/bin/sh
set -eu
DEPLOY_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DEPLOY_DIR"
ARCH=$(docker info --format '{{.Architecture}}')
case "$ARCH" in aarch64|arm64) ARCH=arm64 ;; x86_64|amd64) ARCH=amd64 ;; *) exit 1 ;; esac
BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT HUP INT TERM
tar -xzf source.tar.gz -C "$BUILD_DIR"
docker build --platform "linux/$ARCH" -t "custom-aps-demo:$ARCH" "$BUILD_DIR"
printf 'Image built. Run ./start.sh\n'
