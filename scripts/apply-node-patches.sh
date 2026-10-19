#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 NODE_DIR PATCH_DIR" >&2
  exit 1
fi

node_dir="$(cd "$1" && pwd)"
patch_dir="$(cd "$2" && pwd)"
shopt -s nullglob
patches=("${patch_dir}"/*.patch)
if [[ ${#patches[@]} -eq 0 ]]; then
  echo "No node patches found in ${patch_dir}" >&2
  exit 1
fi

for patch in "${patches[@]}"; do
  if git -C "${node_dir}" apply --check "${patch}" 2>/dev/null; then
    git -C "${node_dir}" apply "${patch}"
    echo "Applied $(basename "${patch}")"
  elif git -C "${node_dir}" apply --reverse --check "${patch}" 2>/dev/null; then
    echo "Already applied $(basename "${patch}")"
  else
    echo "Cannot apply ${patch}; check the node version and local edits." >&2
    exit 1
  fi
done
