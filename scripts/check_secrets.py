"""Fail CI when committed files contain common high-confidence secret patterns."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[opurs]_[A-Za-z0-9_]{36,}\b"),
    "literal database password": re.compile(
        r"postgres(?:ql)?(?:\+\w+)?://[^\s:/]+:(?!\$\{|replace-|example)[^\s@]+@"
    ),
}
SKIP = {".env.example", "scripts/check_secrets.py"}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if path.as_posix() in SKIP or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path}: possible {label}")
    if findings:
        print("\n".join(findings))
        return 1
    print("No high-confidence secret patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
