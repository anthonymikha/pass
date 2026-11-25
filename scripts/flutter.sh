#!/usr/bin/env bash
# Run any Flutter command inside the pinned Flutter Docker image.
# Usage: scripts/flutter.sh pub get | analyze | test | build web ...
# Works from the main checkout and from git worktrees.
set -euo pipefail
IMAGE="pass-flutter-tools:3.35.7"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -q -t "$IMAGE" -f "$(dirname "$0")/../docker/flutter-tools.Dockerfile" "$(dirname "$0")/../docker" >/dev/null
fi
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
COMMON="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
mkdir -p "$COMMON/.pub-cache"
UIDGID="$(id -u):$(id -g)"
docker run --rm \
  -v "$ROOT/frontend:/app" \
  -v "$COMMON/.pub-cache:/root/.pub-cache" \
  -w /app \
  -e PUB_CACHE=/root/.pub-cache \
  "$IMAGE" bash -c 'flutter --no-version-check --suppress-analytics "$@"; rc=$?; chown -R '"$UIDGID"' /app /root/.pub-cache; exit $rc' _ "$@"
