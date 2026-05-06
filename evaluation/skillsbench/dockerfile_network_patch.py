#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


LOCAL_MIRROR_ARG = "SKILLSBENCH_LOCAL_MIRROR_BASE"
NODESOURCE_ARG = "SKILLSBENCH_NODESOURCE_BASE"
NETWORK_MARKER_START = "# BEGIN SKILLSBENCH NETWORK PATCH"
NETWORK_MARKER_END = "# END SKILLSBENCH NETWORK PATCH"

NODESOURCE_LITERAL = "https://deb.nodesource.com"
NODESOURCE_ENV = f"${{{NODESOURCE_ARG}:-{NODESOURCE_LITERAL}}}"

NETWORK_BLOCK = "\n".join(
    [
        NETWORK_MARKER_START,
        f'ARG {LOCAL_MIRROR_ARG}=""',
        f'ARG {NODESOURCE_ARG}="{NODESOURCE_LITERAL}"',
        f"ENV {LOCAL_MIRROR_ARG}=${{{LOCAL_MIRROR_ARG}}}",
        f"ENV {NODESOURCE_ARG}=${{{NODESOURCE_ARG}}}",
        "RUN if [ -n \"$SKILLSBENCH_LOCAL_MIRROR_BASE\" ]; then \\",
        "  for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do \\",
        "    [ -f \"$source_file\" ] || continue; \\",
        "    sed -i \"s|http://archive.ubuntu.com/ubuntu|${SKILLSBENCH_LOCAL_MIRROR_BASE}/ubuntu|g; s|http://security.ubuntu.com/ubuntu|${SKILLSBENCH_LOCAL_MIRROR_BASE}/ubuntu-security|g\" \"$source_file\"; \\",
        "  done; \\",
        "  { \\",
        "    echo 'Acquire::Retries \"3\";'; \\",
        "    echo 'Acquire::http::No-Cache \"true\";'; \\",
        "    echo 'Acquire::https::No-Cache \"true\";'; \\",
        "  } >/etc/apt/apt.conf.d/99skillsbench-network; \\",
        "fi",
        NETWORK_MARKER_END,
    ]
)


def _is_ubuntu_dockerfile(text: str) -> bool:
    return bool(re.search(r"(?mi)^FROM\s+ubuntu(?::|\s)", text))


def _patch_apt_commands(text: str) -> str:
    """Make apt installs tolerant of unsigned mirror metadata in benchmark containers."""
    text = re.sub(
        r"apt-get update(?!\s+-o\s+Acquire::AllowInsecureRepositories=true)",
        (
            "apt-get update "
            "-o Acquire::AllowInsecureRepositories=true "
            "-o Acquire::AllowDowngradeToInsecureRepositories=true"
        ),
        text,
    )
    text = re.sub(
        r"apt-get install -y(?![^&;\n]*--allow-unauthenticated)",
        "apt-get install -y --allow-unauthenticated",
        text,
    )
    return text


def patch_dockerfile_text(text: str) -> str:
    if not _is_ubuntu_dockerfile(text):
        return _patch_apt_commands(text)

    cleaned = re.sub(
        rf"{re.escape(NETWORK_MARKER_START)}.*?{re.escape(NETWORK_MARKER_END)}\n?",
        "",
        text,
        flags=re.DOTALL,
    )
    cleaned = cleaned.replace(NODESOURCE_ENV, NODESOURCE_LITERAL)
    cleaned = cleaned.replace(NODESOURCE_LITERAL, NODESOURCE_ENV)

    if re.search(r"(?m)^ENV\s+DEBIAN_FRONTEND=", cleaned):
        return _patch_apt_commands(re.sub(
            r"(?m)^(ENV\s+DEBIAN_FRONTEND=.*)$",
            rf"\1\n\n{NETWORK_BLOCK}",
            cleaned,
            count=1,
        ))

    return _patch_apt_commands(re.sub(
        r"(?m)^(FROM\s+ubuntu[^\n]*)$",
        rf"\1\n\n{NETWORK_BLOCK}",
        cleaned,
        count=1,
    ))


def patch_dockerfile_path(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    updated = patch_dockerfile_text(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")


def patch_tree(root: Path) -> int:
    patched = 0
    for dockerfile in sorted(root.rglob("environment/Dockerfile")):
        before = dockerfile.read_text(encoding="utf-8")
        after = patch_dockerfile_text(before)
        if after != before:
            dockerfile.write_text(after, encoding="utf-8")
            patched += 1
    return patched


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch generated SkillsBench Dockerfiles to route apt traffic via a host mirror."
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Directory containing generated tasks or environment/Dockerfile trees.",
    )
    args = parser.parse_args()
    patched = patch_tree(args.root)
    print(f"patched_dockerfiles={patched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
