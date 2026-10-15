# Devnet Launcher Assets

This repo builds and packages Casper node and sidecar binaries plus required configs
for pinned Casper node tags. The build steps are scripted so the same
inputs are used every time, and the CI workflow uploads release artifacts with
checksums for verification.

Reproducibility note: builds are driven by pinned source in each version directory and a fixed
script, but exact bit-for-bit output can still depend on the host OS/toolchain.
Use the GitHub Actions release workflow for the most consistent environment.

Supported node tags: `v2.1.1`, `v2.1.2`, `v2.2.0`, `v2.2.1`, and `v2.2.2`.
The `v2.2.x` directories share the sidecar `v2.1.0` pin
(`c77d6891e29cee7270d19811ff3a88ee52981d44`).

## Layout

- `v<version>/` - version-pinned node and sidecar sources (submodules)
- `v<version>/chainspec.toml` - optional version-specific chainspec override
- `assets/v<version>/` - build outputs staged by `build.sh`
- `build.sh` - builds binaries, copies configs, creates tarball + checksums

## Building

Use GitHub Actions when local disk space is limited. For an intentional local
build, initialize only the version being built:

```bash
git submodule update --init --recursive --depth 1 -- \
  v2.2.2/casper-node v2.2.2/casper-sidecar
./build.sh v2.2.2
```

The script accepts one or more versions. With no arguments, it builds every
supported version sequentially. List versions without building or installing tools:

```bash
./build.sh --list-versions
```

Note: `build.sh` uses `uv` to run `dump_host_info.py` with pinned Python deps.
Python is pinned via `.python-version`, and deps are pinned in `pyproject.toml` + `uv.lock`.
Install uv from https://astral.sh/uv before running the script.

Before compiling a version, the script checks that its chainspec protocol version
and node package version both match the selected tag. Chainspecs use the matching
node's `resources/local/chainspec.toml.in` as their schema reference. The `v2.2.x`
overrides retain the repo's devnet settings, including standard rewards handling
and the `${TIMESTAMP}` activation placeholder for the launcher to fill in.

Outputs (using `v2.2.2` as an example):

- `assets/v2.2.2/bin/casper-node`
- `assets/v2.2.2/bin/casper-sidecar`
- `assets/v2.2.2/chainspec.toml`
- `assets/v2.2.2/node-config.toml`
- `assets/v2.2.2/sidecar-config.toml`
- `assets/casper-v2.2.2-<target>.tar.gz`
- `assets/casper-v2.2.2-<target>.tar.gz.sha256`
- `assets/casper-v2.2.2-<target>.tar.gz.sha512`
- `assets/v2.2.2/manifest.json` (included in the tarball)

## Verify checksums

```bash
# Linux
sha256sum -c assets/casper-v2.2.2-<target>.tar.gz.sha256
sha512sum -c assets/casper-v2.2.2-<target>.tar.gz.sha512

# macOS
shasum -a 256 -c assets/casper-v2.2.2-<target>.tar.gz.sha256
shasum -a 512 -c assets/casper-v2.2.2-<target>.tar.gz.sha512
```

## GitHub Releases

Publishing a GitHub Release triggers the workflow in
`.github/workflows/build-release.yml`. It reads the version list from `build.sh`
and runs an independent job for every version/platform pair: Linux x86_64 and
ARM64, and macOS Intel and Apple Silicon. Each job checks out only its version's
submodules and attaches that version's tarball and checksums to the release.

Manual workflow runs can select a single tag with the optional `version` input;
leaving it empty builds all supported versions. Manual runs save the tarballs and
checksums as workflow artifacts, named by version and platform.

## Adding an upstream tag

1. Add `v<version>/casper-node` as a submodule from
   `https://github.com/casper-network/casper-node` and check out the exact public tag
   with `git checkout --detach v<version>` inside the submodule.
2. Add `v<version>/casper-sidecar` from
   `https://github.com/casper-network/casper-sidecar`, checked out at the same sidecar
   commit as the preceding supported version unless a sidecar upgrade is intended.
3. Compare that node tag's `resources/local/chainspec.toml.in` with the preceding
   version. Create `v<version>/chainspec.toml` with any new schema fields, retain the
   devnet settings, and set `[protocol].version` to the node tag without `v`.
   Upstream local templates can still declare an older protocol version.
4. Add the tag to `VERSIONS` in `build.sh` and the supported tags above. Record both
   submodule pins, `.gitmodules`, and the chainspec in the parent repository. CI
   picks up the updated version list automatically; no local compilation is needed.
