#!/usr/bin/env python3
"""Download verified skill libraries and workspaces for the published four sizes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

try:
    from .fetch_asset import extract
except ImportError:  # Direct invocation: python scripts/download_data.py.
    from fetch_asset import extract


REPOSITORY = "yuhuo03/group-of-skills-data"
REVISION = "80773c48bed0471fc15dd680467b9fcd8becaed3"
SIZES = (200, 500, 1000, 2000)
# Archive bytes and SHA256 values from the published release manifest.
ARCHIVES = {
    "skills_200.tar.gz": (1284141, "8872f6088a92bcce1b68f9cfdf033190b2425b071eea3f438e98331635b0a634"),
    "skills_500.tar.gz": (4282003, "e740446f07baa4a53186780bd9f4e4939e30d283c8d21c6a7986285ed84cb2cb"),
    "skills_1000.tar.gz": (4474324, "48cf777043cea7547afa1f0082337428add0a4543c73c56a863c03dc1908faba"),
    "skills_2000.tar.gz": (29149810, "9a616f600488341263f4e931c8387140eb06349a957d498d98a5f5be90109a89"),
    "goskills_workspace_skills_200_v1.tar.gz": (9365609, "8a3f14d650bcc1b60c3bca5ab89f027dced763a92bb37889d0129422e1bd06b6"),
    "goskills_workspace_skills_500_v1.tar.gz": (70940080, "9c1340986115317ea43b0612e90cc3b773739a36296d5f168e69fae775f4f561"),
    "goskills_workspace_skills_1000_v1.tar.gz": (371461848, "c85ea669bf580bbd32fb586713948be137b945683d41a0a65fb68d6593567187"),
    "goskills_workspace_skills_2000_v1.tar.gz": (399586810, "f886c9719f5f6f37f4afcfaa689468415141f0293d4a61c1a12e089edff4872f"),
}


class _HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if urllib.parse.urlsplit(new_url).scheme != "https":
            raise urllib.error.URLError("Refusing a non-HTTPS download redirect")
        return super().redirect_request(request, response, code, message, headers, new_url)


def _open_url(url):
    return urllib.request.build_opener(_HTTPSRedirectHandler()).open(url, timeout=120)


def selected_archives(sizes=SIZES, assets="all"):
    if not sizes or any(size not in SIZES for size in sizes):
        raise ValueError("Sizes must be selected from 200, 500, 1000, 2000")
    if assets not in {"skills", "workspaces", "all"}:
        raise ValueError("Assets must be skills, workspaces, or all")
    names = []
    for size in SIZES:
        if size in sizes:
            if assets in {"skills", "all"}:
                names.append(f"skills_{size}.tar.gz")
            if assets in {"workspaces", "all"}:
                names.append(f"goskills_workspace_skills_{size}_v1.tar.gz")
    return names


def asset_url(name):
    if name not in ARCHIVES:
        raise ValueError(f"Unknown archive: {name}")
    return f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{REVISION}/{name}"


def destination(output, name):
    return Path(output) / name.removesuffix(".tar.gz")


def require_new(path):
    if os.path.lexists(path):
        raise FileExistsError(f"Destination already exists: {path}")


def _publish(extracted, target, record):
    # Exclusive reservation prevents replacing a destination created mid-download.
    target.mkdir(exist_ok=False)
    try:
        for child in extracted.iterdir():
            shutil.move(str(child), target / child.name)
        # Finish the receipt in staging, then publish it atomically and without
        # replacement. A hard interruption before this leaves no completion marker.
        staged_receipt = extracted / "DOWNLOAD_RECEIPT.json"
        with staged_receipt.open("x") as receipt:
            json.dump(record, receipt, indent=2)
            receipt.write("\n")
        os.link(staged_receipt, target / "DOWNLOAD_RECEIPT.json")
    except BaseException:
        shutil.rmtree(target)
        raise


def download_asset(name, output):
    url = asset_url(name)
    expected_bytes, expected_hash = ARCHIVES[name]
    target = destination(output, name)
    require_new(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {name} ({expected_bytes / 1024**2:.1f} MiB)", flush=True)
    with tempfile.TemporaryDirectory(prefix=".goskills-download-", dir=target.parent) as staging:
        archive = Path(staging) / "asset.tar.gz"
        digest = hashlib.sha256()
        received = 0
        next_progress = 32 * 1024**2
        with _open_url(url) as response, archive.open("xb") as stream:
            if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                raise ValueError("Download response must use HTTPS")
            while True:
                chunk = response.read(1024**2)
                if not chunk:
                    break
                received += len(chunk)
                if received > expected_bytes:
                    raise ValueError(f"Archive size mismatch for {name}: exceeds {expected_bytes} bytes")
                digest.update(chunk)
                stream.write(chunk)
                if received >= next_progress:
                    print(f"  {received / 1024**2:.1f} / {expected_bytes / 1024**2:.1f} MiB", flush=True)
                    next_progress += 32 * 1024**2
        if received != expected_bytes:
            raise ValueError(f"Archive size mismatch for {name}: expected {expected_bytes}, received {received}")
        if digest.hexdigest() != expected_hash:
            raise ValueError(f"Archive SHA256 mismatch for {name}")
        print(f"Verified {name}; extracting", flush=True)
        extracted = Path(staging) / "extracted"
        stats = extract(archive, extracted, strip=1)
        record = {
            "repository": REPOSITORY,
            "revision": REVISION,
            "url": url,
            "archive_sha256": expected_hash,
            "archive_bytes": received,
            "hash_pinned": True,
            **stats,
        }
        if (extracted / "DOWNLOAD_RECEIPT.json").exists():
            raise ValueError("Archive contains a reserved DOWNLOAD_RECEIPT.json")
        _publish(extracted, target, record)
    print(f"Ready: {target}", flush=True)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, choices=SIZES, default=list(SIZES))
    parser.add_argument("--assets", choices=("skills", "workspaces", "all"), default="all")
    parser.add_argument("--output", type=Path, default=Path("data/external"), help="Parent of new asset directories")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without network or filesystem writes")
    args = parser.parse_args(argv)
    try:
        names = selected_archives(args.sizes, args.assets)
        # Check the entire selection before any download begins.
        for name in names:
            require_new(destination(args.output, name))
        if args.dry_run:
            for name in names:
                size, digest = ARCHIVES[name]
                print(json.dumps({"url": asset_url(name), "bytes": size, "sha256": digest,
                                  "output": str(destination(args.output, name))}))
        else:
            for name in names:
                download_asset(name, args.output)
    except (OSError, ValueError, tarfile.TarError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
