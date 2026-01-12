#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#   "psutil==5.9.8",
# ]
# ///
import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil


def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd,
            check=True,
            text=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def parse_kv_lines(output):
    data = {}
    if not output:
        return data
    for line in output.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        data[key.strip()] = value.strip()
    return data


def parse_os_release(path):
    if not path.exists():
        return None
    data = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value.strip().strip('"')
    return data


def parse_submodules(output):
    if not output:
        return []
    entries = []
    for line in output.splitlines():
        if not line.strip():
            continue
        status = line[0]
        rest = line[1:].strip()
        parts = rest.split()
        if len(parts) < 2:
            continue
        commit = parts[0]
        path = parts[1]
        description = " ".join(parts[2:]) if len(parts) > 2 else None
        entries.append(
            {
                "path": path,
                "commit": commit,
                "status": status,
                "description": description,
            }
        )
    return entries


def git_info():
    root = run_cmd(["git", "rev-parse", "--show-toplevel"])
    if not root:
        return None
    head = run_cmd(["git", "rev-parse", "HEAD"])
    branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    status = run_cmd(["git", "status", "--porcelain"]) or ""
    submodules = parse_submodules(
        run_cmd(["git", "submodule", "status", "--recursive"]) or ""
    )
    return {
        "root": root,
        "head": head,
        "branch": branch,
        "dirty": bool(status.strip()),
        "submodules": submodules,
    }


def git_component_info(path):
    path = Path(path)
    if not path.exists():
        return None
    head = run_cmd(["git", "-C", str(path), "rev-parse", "HEAD"])
    if not head:
        return None
    branch = run_cmd(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"])
    status = run_cmd(["git", "-C", str(path), "status", "--porcelain"]) or ""
    return {
        "path": str(path),
        "head": head,
        "branch": branch,
        "dirty": bool(status.strip()),
    }


def hash_file(path, algorithm):
    hasher = algorithm()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def collect_package_files(package_dir, exclude=None):
    if not package_dir or not package_dir.exists():
        return None
    exclude = exclude.resolve() if exclude else None
    files = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file():
            continue
        if exclude and path.resolve() == exclude:
            continue
        stat = path.stat()
        files.append(
            {
                "path": str(path.relative_to(package_dir)),
                "size_bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "sha256": hash_file(path, algorithm=hashlib.sha256),
                "sha512": hash_file(path, algorithm=hashlib.sha512),
            }
        )
    return files


def host_info(assets_dir):
    uname = platform.uname()
    cpu_freq = psutil.cpu_freq()
    return {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "platform": platform.platform(),
            "uname": uname._asdict(),
            "mac_ver": platform.mac_ver()[0],
            "libc_ver": {
                "libc": platform.libc_ver()[0],
                "version": platform.libc_ver()[1],
            },
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "compiler": platform.python_compiler(),
            "executable": sys.executable,
        },
        "cpu": {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "freq_mhz": None
            if cpu_freq is None
            else {
                "current": cpu_freq.current,
                "min": cpu_freq.min,
                "max": cpu_freq.max,
            },
        },
        "memory": psutil.virtual_memory()._asdict(),
        "disk": psutil.disk_usage(str(assets_dir))._asdict(),
        "os_release": parse_os_release(Path("/etc/os-release")),
        "ci": {
            "enabled": os.getenv("CI") == "true",
            "provider": "github-actions"
            if os.getenv("GITHUB_ACTIONS") == "true"
            else None,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Write build host manifest JSON.")
    parser.add_argument(
        "--assets-dir",
        default="assets",
        help="Path to assets directory.",
    )
    parser.add_argument(
        "--output",
        default="assets/manifest.json",
        help="Manifest output path.",
    )
    parser.add_argument(
        "--target-triple",
        default=None,
        help="Rust target triple for the build host.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Version included in this bundle.",
    )
    parser.add_argument(
        "--version-dir",
        default=None,
        help="Path to the version directory (e.g. v2.1.1).",
    )
    parser.add_argument(
        "--package-dir",
        default=None,
        help="Path to packaged assets directory (e.g. assets/v2.1.1).",
    )
    args = parser.parse_args()

    assets_dir = Path(args.assets_dir).resolve()
    package_dir = Path(args.package_dir).resolve() if args.package_dir else None
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rustc_info = parse_kv_lines(run_cmd(["rustc", "-vV"]))

    components = None
    if args.version_dir:
        version_dir = Path(args.version_dir)
        components = {
            "casper-node": git_component_info(version_dir / "casper-node"),
            "casper-sidecar": git_component_info(version_dir / "casper-sidecar"),
        }

    manifest = {
        "manifest_version": 1,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "build": {
            "version": args.version,
            "version_dir": args.version_dir,
            "target_triple": args.target_triple or rustc_info.get("host"),
            "assets_dir": str(assets_dir),
        },
        "host": host_info(assets_dir),
        "tools": {
            "rustc": rustc_info or None,
            "cargo": run_cmd(["cargo", "-V"]),
            "uv": run_cmd(["uv", "--version"]),
            "git": git_info(),
        },
        "components": components,
        "package_files": collect_package_files(package_dir, exclude=output_path),
    }

    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
