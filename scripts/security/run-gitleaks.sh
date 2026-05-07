#!/usr/bin/env bash

set -euo pipefail

GITLEAKS_VERSION="${GITLEAKS_VERSION:-8.30.1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
machine="$(uname -m)"

case "${os}" in
  linux | darwin)
    ;;
  *)
    echo "Unsupported OS for bootstrapped gitleaks scan: ${os}" >&2
    exit 1
    ;;
esac

case "${machine}" in
  x86_64 | amd64)
    arch="x64"
    ;;
  arm64 | aarch64)
    arch="arm64"
    ;;
  *)
    echo "Unsupported architecture for bootstrapped gitleaks scan: ${machine}" >&2
    exit 1
    ;;
esac

archive="gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz"
case "${archive}" in
  gitleaks_8.30.1_darwin_arm64.tar.gz)
    expected_sha256="b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5"
    ;;
  gitleaks_8.30.1_darwin_x64.tar.gz)
    expected_sha256="dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709"
    ;;
  gitleaks_8.30.1_linux_arm64.tar.gz)
    expected_sha256="e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080"
    ;;
  gitleaks_8.30.1_linux_x64.tar.gz)
    expected_sha256="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
    ;;
  *)
    echo "No pinned checksum is configured for ${archive}" >&2
    exit 1
    ;;
esac

cache_dir="${REPO_ROOT}/.cache/gitleaks/v${GITLEAKS_VERSION}/${os}_${arch}"
binary="${cache_dir}/gitleaks"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

if [ ! -x "${binary}" ]; then
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "${tmpdir}"' EXIT

  url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${archive}"
  curl -sSL -o "${tmpdir}/${archive}" "${url}"

  actual_sha256="$(sha256_file "${tmpdir}/${archive}")"
  if [ "${actual_sha256}" != "${expected_sha256}" ]; then
    echo "Checksum mismatch for ${archive}" >&2
    echo "Expected: ${expected_sha256}" >&2
    echo "Actual:   ${actual_sha256}" >&2
    exit 1
  fi

  tar -xzf "${tmpdir}/${archive}" -C "${tmpdir}" gitleaks
  mkdir -p "${cache_dir}"
  install -m 0755 "${tmpdir}/gitleaks" "${binary}"
fi

cd "${REPO_ROOT}"
exec "${binary}" git . --no-banner --redact=100 "$@"
