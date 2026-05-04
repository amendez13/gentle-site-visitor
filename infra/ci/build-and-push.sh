#!/usr/bin/env bash
set -euo pipefail

SHA="$(git rev-parse --short HEAD)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

repository_owner_from_origin() {
  local remote_url path
  remote_url="$(git config --get remote.origin.url || true)"

  case "$remote_url" in
    git@github.com:*) path="${remote_url#git@github.com:}" ;;
    https://github.com/*) path="${remote_url#https://github.com/}" ;;
    ssh://git@github.com/*) path="${remote_url#ssh://git@github.com/}" ;;
    *) path="" ;;
  esac

  path="${path%.git}"
  if [[ "$path" == */* ]]; then
    printf '%s\n' "${path%%/*}"
  fi
}

REPO_OWNER="${REPO_OWNER:-$(repository_owner_from_origin)}"
if [[ -z "${REPO:-}" && -z "$REPO_OWNER" ]]; then
  echo "Set REPO or REPO_OWNER, or configure origin as a GitHub remote." >&2
  exit 1
fi

REPO="${REPO:-ghcr.io/${REPO_OWNER}/gentle-site-visitor-ci}"

# Authenticate first:
#   echo "$GHCR_TOKEN" | docker login ghcr.io -u "$REPO_OWNER" --password-stdin

BUILDER_NAME="${BUILDER_NAME:-gentle-site-visitor-ci-multiarch}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
  docker buildx create --name "$BUILDER_NAME" --use
else
  docker buildx use "$BUILDER_NAME"
fi

docker buildx inspect --bootstrap >/dev/null

docker buildx build \
  --platform "$PLATFORMS" \
  -f "$SCRIPT_DIR/Dockerfile" \
  -t "$REPO:$SHA" \
  -t "$REPO:latest" \
  --push \
  "$REPO_ROOT"
