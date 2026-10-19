#!/usr/bin/env python3
"""Check patches and exercise the std-only FD writer without building a node.

All fixtures and compiled test executables live in a TemporaryDirectory, which
is removed on success or failure. No Cargo target directory is created.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading


ROOT = Path(__file__).resolve().parent.parent
FD_ENV = "CASPER_DEVNET_EXPERIMENTAL_PRINT_FD"
RUNTIME = "execution_engine/src/runtime/mod.rs"
MAIN = "node/src/app/main.rs"
WRITER = "execution_engine/src/runtime/print_output.rs"

HARNESS = r'''
mod print_output;

fn main() -> std::io::Result<()> {
    print_output::initialize()?;
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--close-inherited") {
        use std::os::fd::RawFd;
        extern "C" { fn close(fd: RawFd) -> i32; }
        let fd: RawFd = std::env::var("CASPER_DEVNET_EXPERIMENTAL_PRINT_FD")
            .unwrap().parse().unwrap();
        // A successful close also proves initialization left this descriptor open.
        assert_eq!(unsafe { close(fd) }, 0);
        return print_output::write_line("owned duplicate");
    }
    if args.first().map(String::as_str) == Some("--expect-write-error") {
        assert!(print_output::write_line("disconnected").is_err());
        return Ok(());
    }
    if args.first().map(String::as_str) == Some("--threads") {
        let threads: Vec<_> = (0..8).map(|worker| std::thread::spawn(move || {
            for line in 0..50 {
                print_output::write_line(&format!("{worker}:{line}"))?;
            }
            Ok::<_, std::io::Error>(())
        })).collect();
        for thread in threads { thread.join().unwrap()?; }
        return Ok(());
    }
    for text in args { print_output::write_line(&text)?; }
    Ok(())
}
'''


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, timeout=30, **kwargs)


def environment(fd=None):
    env = os.environ.copy()
    env.pop(FD_ENV, None)
    if fd is not None:
        env[FD_ENV] = str(fd)
    return env


def pipe_output(binary, *args):
    read_fd, write_fd = os.pipe()
    chunks = []
    with os.fdopen(read_fd, "rb") as reader:
        thread = threading.Thread(target=lambda: chunks.append(reader.read()), daemon=True)
        process = None
        try:
            process = subprocess.Popen(
                [str(binary), *args], env=environment(write_fd), pass_fds=(write_fd,),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        finally:
            os.close(write_fd)
        thread.start()
        try:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            assert stdout == b"", stdout
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            thread.join(timeout=5)
        assert not thread.is_alive(), "inherited write descriptor leaked"
    return b"".join(chunks)


def check_writer(binary):
    result = run([str(binary), "hello", "", "Zażółć\nsecond line"], env=environment())
    assert result.stdout == "hello\n\nZażółć\nsecond line\n".encode()
    assert pipe_output(binary, "hello", "", "Zażółć\nsecond line") == result.stdout
    # Larger than a pipe buffer, exercising short writes with a concurrent reader.
    large = "x" * 80_000
    assert pipe_output(binary, large) == (large + "\n").encode()
    assert pipe_output(binary, "--close-inherited") == b"owned duplicate\n"
    lines = pipe_output(binary, "--threads").decode().splitlines()
    assert len(lines) == 400
    assert set(lines) == {f"{worker}:{line}" for worker in range(8) for line in range(50)}

    for value in ("", "-1", "not-an-fd", "2147483648", "1073741823", "\udcff"):
        result = subprocess.run(
            [str(binary), "must not print"], env=environment(value),
            capture_output=True, timeout=10,
        )
        assert result.returncode != 0, value
        assert result.stdout == b"", value
        assert FD_ENV.encode() in result.stderr, result.stderr

    # A closed pipe reader returns an I/O error rather than panicking or SIGPIPE.
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        run([str(binary), "--expect-write-error"],
            env=environment(write_fd), pass_fds=(write_fd,))
    finally:
        os.close(write_fd)
    # A valid but read-only descriptor also reports an I/O error.
    with open(os.devnull, "rb") as read_only:
        run([str(binary), "--expect-write-error"],
            env=environment(read_only.fileno()), pass_fds=(read_only.fileno(),))

    # A regular inherited file preserves its existing content/offset.
    with tempfile.TemporaryFile() as destination:
        destination.write(b"before\n")
        destination.flush()
        run([str(binary), "after"],
            env=environment(destination.fileno()), pass_fds=(destination.fileno(),))
        destination.seek(0)
        assert destination.read() == b"before\nafter\n"


def check_version(version):
    source = ROOT / version / "casper-node"
    patches = ROOT / version / "patches"
    with tempfile.TemporaryDirectory(prefix=f"casper-print-{version}-") as directory:
        fixture = Path(directory)
        # Use pristine pinned files, so checks also work after a local build applied patches.
        for relative in (RUNTIME, MAIN):
            destination = fixture / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(run([
                "git", "-C", str(source), "show", f"HEAD:{relative}",
            ]).stdout)
        run(["git", "init", "-q", str(fixture)])
        apply = ["bash", str(ROOT / "scripts/apply-node-patches.sh"), str(fixture), str(patches)]
        run(apply)
        applied = {relative: (fixture / relative).read_bytes() for relative in (RUNTIME, MAIN, WRITER)}
        result = run(apply)
        assert b"Already applied" in result.stdout
        assert all((fixture / relative).read_bytes() == content for relative, content in applied.items())
        assert b"initialize_print_output()?;" in applied[MAIN]
        assert b"Debug output must not change contract execution" in applied[RUNTIME]

        shutil.copyfile(fixture / WRITER, fixture / "print_output.rs")
        (fixture / "main.rs").write_text(HARNESS)
        binary = fixture / "check-print-output"
        run(["rustc", "--edition=2021", str(fixture / "main.rs"), "-o", str(binary)])
        check_writer(binary)

        # Refuse partial application without overwriting unrelated/local changes.
        (fixture / WRITER).write_text("// local modification\n")
        result = subprocess.run(apply, capture_output=True, timeout=10)
        assert result.returncode != 0
        assert (fixture / WRITER).read_text() == "// local modification\n"
        assert (fixture / RUNTIME).read_bytes() == applied[RUNTIME]
        print(f"{version}: patch application/reapplication/conflicts and FD writer checks passed")


def main():
    supported = run(["bash", str(ROOT / "build.sh"), "--list-versions"], text=True).stdout.splitlines()
    versions = sys.argv[1:] or supported
    if any(version not in supported for version in versions):
        sys.exit("Unsupported version; use build.sh --list-versions")
    for version in versions:
        check_version(version)
    print("Temporary fixtures/binaries removed; no node build or Cargo target directory created.")


if __name__ == "__main__":
    main()
