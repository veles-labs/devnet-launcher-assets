#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="${ROOT_DIR}/assets"
VERSIONS=("v2.1.1")

case "$(uname -s)" in
  Darwin) OS="macos" ;;
  Linux) OS="linux" ;;
  *)
    echo "Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

for version in "${VERSIONS[@]}"; do
  version_dir="${ROOT_DIR}/${version}"
  node_dir="${version_dir}/casper-node"
  sidecar_dir="${version_dir}/casper-sidecar"
  assets_version_dir="${ASSETS_DIR}/${version}"

  mkdir -p "${assets_version_dir}/bin"
  mkdir -p "${assets_version_dir}"

  pushd "${node_dir}" >/dev/null
  cargo build --release --bin casper-node
  cp "target/release/casper-node" "${assets_version_dir}/bin/"
  popd >/dev/null

  pushd "${sidecar_dir}" >/dev/null
  cargo build --release --bin casper-sidecar
  cp "target/release/casper-sidecar" "${assets_version_dir}/bin/"
  popd >/dev/null

  cp "${node_dir}/resources/local/chainspec.toml.in" \
    "${assets_version_dir}/chainspec.toml"
  cp "${sidecar_dir}/resources/example_configs/default_rpc_only_config.toml" \
    "${assets_version_dir}/sidecar-config.toml"

  tarball="${ASSETS_DIR}/casper-${version}-${OS}.tar.gz"
  tar -C "${ASSETS_DIR}" -czf "${tarball}" "${version}"

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${tarball}" > "${tarball}.sha256"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${tarball}" > "${tarball}.sha256"
  else
    echo "Missing sha256 checksum tool (sha256sum or shasum)" >&2
    exit 1
  fi

  if command -v sha512sum >/dev/null 2>&1; then
    sha512sum "${tarball}" > "${tarball}.sha512"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 512 "${tarball}" > "${tarball}.sha512"
  else
    echo "Missing sha512 checksum tool (sha512sum or shasum)" >&2
    exit 1
  fi

  echo "Completed ${version}: ${tarball}"
done
