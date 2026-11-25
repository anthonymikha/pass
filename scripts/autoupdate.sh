#!/usr/bin/env bash
# Poll the git remote; when the current branch's upstream has new commits, pull and rebuild the stack.
# Usage: scripts/autoupdate.sh          (env: INTERVAL=seconds between checks, default 300)
# Run it in the background: nohup scripts/autoupdate.sh >> autoupdate.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
INTERVAL="${INTERVAL:-300}"
log() { echo "$(date '+%F %T') $*"; }

while true; do
  if ! git fetch --quiet; then
    log "fetch failed, retrying later"
  # only commits on the remote that HEAD lacks count; local-only commits must not trigger a rebuild every loop
  elif [ -n "$(git rev-list HEAD..'@{u}')" ]; then
    log "update found: $(git rev-parse --short HEAD) -> $(git rev-parse --short '@{u}')"
    # ponytail: --ff-only refuses local edits/diverged history instead of merging; fix by hand then it resumes
    if ! git pull --ff-only --quiet; then
      log "pull failed (local changes or diverged branch), skipping"
    # a failed build leaves the old container running
    elif docker compose up -d --build; then
      log "rebuilt and restarted at $(git rev-parse --short HEAD)"
    else
      log "build failed, old version still running"
    fi
  fi
  sleep "$INTERVAL"
done
