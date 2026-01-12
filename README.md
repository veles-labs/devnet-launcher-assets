# Devnet Launcher Assets

This repo builds and packages Casper node and sidecar binaries plus required configs
for a specific, pinned version (`v2.1.1`). The build steps are scripted so the same
inputs are used every time, and the CI workflow uploads release artifacts with
checksums for verification.

Reproducibility note: builds are driven by pinned source in `v2.1.1/` and a fixed
script, but exact bit-for-bit output can still depend on the host OS/toolchain.
Use the GitHub Actions release workflow for the most consistent environment.

## Layout

- `v2.1.1/` - version-pinned sources (submodules)
- `assets/v2.1.1/` - build outputs staged by `build.sh`
- `build.sh` - builds binaries, copies configs, creates tarball + checksums

## Local build

1) Ensure submodules are present:

```bash
git submodule update --init --recursive
```

2) Build and package:

```bash
./build.sh
```

Note: `build.sh` uses `uv` to run `dump_host_info.py` with pinned Python deps.
Python is pinned via `.python-version`; install uv from https://astral.sh/uv before running the script.

Outputs:

- `assets/v2.1.1/bin/casper-node`
- `assets/v2.1.1/bin/casper-sidecar`
- `assets/v2.1.1/chainspec.toml`
- `assets/v2.1.1/sidecar-config.toml`
- `assets/casper-v2.1.1-<target>.tar.gz`
- `assets/casper-v2.1.1-<target>.tar.gz.sha256`
- `assets/casper-v2.1.1-<target>.tar.gz.sha512`
- `assets/v2.1.1/manifest.json` (included in the tarball)

## Verify checksums

```bash
# Linux
sha256sum -c assets/casper-v2.1.1-<target>.tar.gz.sha256
sha512sum -c assets/casper-v2.1.1-<target>.tar.gz.sha512

# macOS
shasum -a 256 -c assets/casper-v2.1.1-<target>.tar.gz.sha256
shasum -a 512 -c assets/casper-v2.1.1-<target>.tar.gz.sha512
```

## GitHub Releases

Publishing a GitHub Release triggers the workflow in
`.github/workflows/build-release.yml` to build on Linux and macOS and attach the
tarball plus checksum files to the release.
