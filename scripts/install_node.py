"""Install an official Node 24 LTS binary locally, with SHA-256 verification."""

from __future__ import annotations

import hashlib
import json
import platform
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
BASE = "https://nodejs.org/dist"


def download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response:
        destination.write_bytes(response.read())


def main() -> None:
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64"}.get(platform.machine())
    if not system or not machine:
        raise SystemExit("Unsupported local Node platform; use an official Node 24 LTS installer.")
    TOOLS.mkdir(exist_ok=True)
    version_file = ROOT / ".node-version"
    if version_file.exists():
        version = "v" + version_file.read_text().strip().removeprefix("v")
    else:
        with urllib.request.urlopen(f"{BASE}/index.json", timeout=60) as response:
            releases = json.load(response)
        candidates = [r for r in releases if r["version"].startswith("v24.") and r["lts"]]
        if not candidates:
            raise SystemExit("No Node 24 LTS release found in the official index.")
        version = max(candidates, key=lambda r: tuple(int(x) for x in r["version"][1:].split(".")))[
            "version"
        ]
    name = f"node-{version}-{system}-{machine}"
    archive = TOOLS / f"{name}.tar.gz"
    checksums = TOOLS / f"{version}-SHASUMS256.txt"
    download(f"{BASE}/{version}/SHASUMS256.txt", checksums)
    expected = next(
        (
            line.split()[0]
            for line in checksums.read_text().splitlines()
            if line.split()[-1] == archive.name
        ),
        None,
    )
    if expected is None:
        raise SystemExit("Official checksum not found for this platform.")
    download(f"{BASE}/{version}/{archive.name}", archive)
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise SystemExit("Node archive checksum mismatch; not extracting.")
    with tarfile.open(archive) as bundle:
        bundle.extractall(TOOLS, filter="data")
    link = TOOLS / "node"
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise SystemExit(".tools/node already exists and is not a symlink; preserving it.")
    link.symlink_to(name, target_is_directory=True)
    version_file.write_text(version[1:] + "\n")
    archive.unlink()
    print(f"Installed {version} ({system}-{machine}); SHA-256 {actual}")


if __name__ == "__main__":
    main()
