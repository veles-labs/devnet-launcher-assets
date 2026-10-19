# Devnet Launcher Assets

This repo builds and packages Casper node and sidecar binaries plus required configs
for pinned Casper node tags. The build steps are scripted so the same
inputs are used every time, and the CI workflow uploads release artifacts with
checksums for verification.

Reproducibility note: builds are driven by pinned source and versioned patches in each version directory and a fixed
script, but exact bit-for-bit output can still depend on the host OS/toolchain.
Use the GitHub Actions release workflow for the most consistent environment.

Supported node tags: `v2.1.1`, `v2.1.2`, `v2.2.0`, `v2.2.1`, and `v2.2.2`.
The `v2.2.x` directories share the sidecar `v2.1.0` pin
(`c77d6891e29cee7270d19811ff3a88ee52981d44`).

## Layout

- `v<version>/` - version-pinned node and sidecar sources (submodules)
- `v<version>/chainspec.toml` - optional version-specific chainspec override
- `v<version>/patches/` - node source patches applied in filename order by `build.sh`
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

Every supported node version is built with the execution engine's `test-support`
feature to enable the VM1 `casper_print` host function for Wasm contract debugging:

```bash
cargo build --release --bin casper-node --features casper-execution-engine/test-support
```

The feature belongs to `casper-execution-engine`, so the build uses Cargo's
[package-qualified feature syntax](https://doc.rust-lang.org/cargo/reference/features.html#command-line-feature-options).
The shared build command applies to all versions and platforms in CI. This is a
compile-time choice; no chainspec setting is required. It also enables upstream
test-support diagnostics, such as runtime stack information on execution errors.

Print output defaults to the node's stdout and can be routed to a dedicated
inherited descriptor as described below. Rust contracts using
`casper_contract::contract_api::runtime::print` must also enable `test-support` on
their `casper-contract` dependency. These assets are intended for devnets;
contracts importing `casper_print` require a node built with this feature, and
should omit those calls when targeting nodes that do not expose it.

Outputs (using `v2.2.2` as an example):

- `assets/v2.2.2/bin/casper-node`
- `assets/v2.2.2/bin/casper-sidecar`
- `assets/v2.2.2/chainspec.toml`
- `assets/v2.2.2/node-config.toml`
- `assets/v2.2.2/sidecar-config.toml`
- `assets/v2.2.2/patches/` (exact node patches, included in manifest file hashes)
- `assets/casper-v2.2.2-<target>.tar.gz`
- `assets/casper-v2.2.2-<target>.tar.gz.sha256`
- `assets/casper-v2.2.2-<target>.tar.gz.sha512`
- `assets/v2.2.2/manifest.json` (included in the tarball)

## Experimental contract print descriptor

Each supported version includes `patches/0001-casper-print-fd.patch`. It redirects
only the VM1 `casper_print` host function when the node process has
`CASPER_DEVNET_EXPERIMENTAL_PRINT_FD` set. The value is the decimal descriptor
number **in the child node process**, referring to a writable, blocking pipe,
stream socket, or file inherited from `casper-devnet`. The environment variable
alone does not transfer a descriptor. The interface is experimental.

At startup, before worker threads start, the node reads the variable once and
duplicates the descriptor for the execution engine. It leaves the original
descriptor open and uses its own close-on-exec copy. An unset variable preserves
stdout output. An empty, malformed, negative, or unopened descriptor causes a
startup error instead of silently switching to stdout. A valid but unwritable
descriptor produces an I/O error when a contract prints.

Output is the contract's UTF-8 text followed by one newline, including any
newlines already present in the text. Writes are serialized within each node and
handle partial writes and interrupted system calls. There is no additional
buffering or event metadata. Print I/O failures produce one warning per process;
they do not panic the node or change the contract's execution result. Failed
writes can lose output and are not redirected to stdout.

For `casper-devnet` integration:

1. Create a separate pipe or stream socket for each node. Keep the reading end in
   `casper-devnet` and arrange for the writing end to survive the node's `exec`
   (for example, `dup2` it to an available child FD and clear `FD_CLOEXEC`). Choose
   an FD that does not overlap other inherited descriptors, such as consensus key
   pipes. Set `CASPER_DEVNET_EXPERIMENTAL_PRINT_FD` on that node's command to the
   resulting child FD number. Normal stdout/stderr can retain their existing log
   destinations.
2. After spawning the node, close the parent's copy of the writing end. Drain the
   reader continuously: a full blocking pipe will stall the executing print call.
   Identify the node by its dedicated pipe; calls from separate node processes
   sharing a pipe are not serialized together.
3. Repeat the descriptor setup for node restarts and upgrades. Remove the variable
   from commands that do not inherit the descriptor, such as binary version probes.

For a shell example using an already built node and an existing validator config:

```bash
CASPER_DEVNET_EXPERIMENTAL_PRINT_FD=3 \
  ./assets/v2.2.2/bin/casper-node validator /path/to/config.toml \
  3>>contract-print.log
```

`build.sh` applies each version's patches before compilation. Repeated builds
recognize already applied patches; conflicts stop the build without resetting
local changes. Submodule commits remain pinned to upstream tags, while the
patched working trees are reported as dirty in the manifest. The archive includes
the exact patches and their hashes so the effective sources can be identified.
The changes in this repository provide the node interface; `casper-devnet` must
wire descriptor inheritance and collection into its process launcher.

Run the focused checks without building a node:

```bash
python3 scripts/check-node-patches.py          # all supported versions
python3 scripts/check-node-patches.py v2.2.2   # one version
```

These checks apply patches to temporary source fixtures and compile only the
small standard-library-only descriptor writer. They exercise stdout fallback,
inherited pipes and files, descriptor ownership, concurrent and large writes,
invalid configuration, and write errors. All temporary sources and executables
are removed on success or failure; no Cargo `target` directory is created. CI runs
these checks on every version/platform pair before the full node build.

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
   submodule pins, `.gitmodules`, and the chainspec in the parent repository. Port
   the preceding version's `patches/` to the new tag and run
   `python3 scripts/check-node-patches.py v<version>` to check application and the
   print descriptor interface. CI
   picks up the updated version list automatically; no local compilation is needed.
