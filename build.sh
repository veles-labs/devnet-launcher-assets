#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="${ROOT_DIR}/assets"
VERSIONS=(
  "v2.1.1"
  "v2.1.2"
  "v2.2.0"
  "v2.2.1"
  "v2.2.2"
)

if [[ $# -eq 1 && "$1" == "--list-versions" ]]; then
  printf '%s\n' "${VERSIONS[@]}"
  exit 0
fi

if [[ $# -gt 0 ]]; then
  for requested_version in "$@"; do
    supported=false
    for version in "${VERSIONS[@]}"; do
      if [[ "${requested_version}" == "${version}" ]]; then
        supported=true
        break
      fi
    done
    if [[ "${supported}" != true ]]; then
      echo "Unsupported version: ${requested_version}" >&2
      echo "Usage: $0 [--list-versions | VERSION ...]" >&2
      exit 1
    fi
  done
  VERSIONS=("$@")
fi

if command -v rustc >/dev/null 2>&1; then
  TARGET_TRIPLE="$(rustc -vV | awk -F': ' '/^host:/{print $2}')"
  echo "🧰 Rust target detected: ${TARGET_TRIPLE}"
else
  echo "Missing rustc; required to determine target triple" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing uv; install from https://astral.sh/uv" >&2
  exit 1
fi

for version in "${VERSIONS[@]}"; do
  echo "🚀 Starting build for ${version}"
  version_dir="${ROOT_DIR}/${version}"
  node_dir="${version_dir}/casper-node"
  sidecar_dir="${version_dir}/casper-sidecar"
  assets_version_dir="${ASSETS_DIR}/${version}"

  version_chainspec="${version_dir}/chainspec.toml"
  if [[ ! -f "${version_chainspec}" ]]; then
    version_chainspec="${node_dir}/resources/local/chainspec.toml.in"
  fi

  # Upstream local templates can retain an older protocol version. Check before
  # spending time and disk space on compilation.
  uv run --project "${ROOT_DIR}" python - "${version}" "${version_chainspec}" "${node_dir}/node/Cargo.toml" <<'PY'
import sys
import tomllib
from pathlib import Path

version, chainspec_path, cargo_path = sys.argv[1:]
expected = version.removeprefix("v")
for path, section, label in (
    (chainspec_path, "protocol", "chainspec"),
    (cargo_path, "package", "casper-node"),
):
    actual = tomllib.loads(Path(path).read_text())[section]["version"]
    if actual != expected:
        sys.exit(f"{label} version {actual} does not match {version}: {path}")
PY

  mkdir -p "${assets_version_dir}/bin"
  mkdir -p "${assets_version_dir}"

  pushd "${node_dir}" >/dev/null
  echo "🔨 Building casper-node"
  cargo build --release --bin casper-node
  cp "target/release/casper-node" "${assets_version_dir}/bin/"
  popd >/dev/null

  pushd "${sidecar_dir}" >/dev/null
  echo "🔧 Building casper-sidecar"
  cargo build --release --bin casper-sidecar
  cp "target/release/casper-sidecar" "${assets_version_dir}/bin/"
  popd >/dev/null

  echo "📦 Staging configs"
  cp "${version_chainspec}" "${assets_version_dir}/chainspec.toml"
  cp "${node_dir}/resources/local/config.toml" \
    "${assets_version_dir}/node-config.toml"
  cp "${sidecar_dir}/resources/example_configs/default_rpc_only_config.toml" \
    "${assets_version_dir}/sidecar-config.toml"

  manifest_path="${assets_version_dir}/manifest.json"
  echo "📝 Writing build manifest: ${manifest_path}"
  uv run "${ROOT_DIR}/dump_host_info.py" \
    --assets-dir "${ASSETS_DIR}" \
    --output "${manifest_path}" \
    --target-triple "${TARGET_TRIPLE}" \
    --version "${version}" \
    --version-dir "${version_dir}" \
    --package-dir "${assets_version_dir}"

  tarball="${ASSETS_DIR}/casper-${version}-${TARGET_TRIPLE}.tar.gz"
  echo "🧳 Creating archive: ${tarball}"
  tar -C "${ASSETS_DIR}" -czf "${tarball}" "${version}"

  if command -v sha256sum >/dev/null 2>&1; then
    echo "🧮 Writing SHA256"
    sha256sum "${tarball}" > "${tarball}.sha256"
  elif command -v shasum >/dev/null 2>&1; then
    echo "🧮 Writing SHA256"
    shasum -a 256 "${tarball}" > "${tarball}.sha256"
  else
    echo "Missing sha256 checksum tool (sha256sum or shasum)" >&2
    exit 1
  fi

  if command -v sha512sum >/dev/null 2>&1; then
    echo "🧮 Writing SHA512"
    sha512sum "${tarball}" > "${tarball}.sha512"
  elif command -v shasum >/dev/null 2>&1; then
    echo "🧮 Writing SHA512"
    shasum -a 512 "${tarball}" > "${tarball}.sha512"
  else
    echo "Missing sha512 checksum tool (sha512sum or shasum)" >&2
    exit 1
  fi

  echo "✅ Completed ${version}: ${tarball}"
done
