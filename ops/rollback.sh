#!/usr/bin/env bash
set -e

# ops/rollback.sh: Checkout supplied Git tag and rebuild
if [ -z "$1" ]; then
  echo "Usage: $0 <git-tag>" >&2
  exit 1
fi
TAG="$1"
git fetch --all
git checkout "$TAG"
cd "$(dirname "$0")/.."
./scripts/build.sh

