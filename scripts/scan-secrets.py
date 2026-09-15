#!/usr/bin/env python3
"""Fail CI when the tracked tree contains a credential-shaped literal."""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 2_000_000
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".woff", ".woff2"}
KEY = re.compile(
    r"(?ix)\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"app[_-]?secret|private[_-]?key|password)\b\s*[:=]\s*[\"']?([^\s\"'#]{12,})"
)
PROVIDER = re.compile(
    r"(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{30,}|"
    r"AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,})"
)
PLACEHOLDER = re.compile(
    r"(?i)(example|placeholder|replace|change|your[_-]|dummy|test|demo|password|"
    r"secret|token|generate|localhost|none|null|settings\.|os\.getenv|environ|"
    r"<[^>]+>|\$\{)"
)


def entropy(value: str) -> float:
    if not value:
        return 0.0
    return -sum((value.count(c) / len(value)) * math.log2(value.count(c) / len(value))
                for c in set(value))


def main() -> int:
    names = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True,
    ).splitlines()
    findings: list[str] = []
    for name in names:
        path = ROOT / name
        if (not path.is_file() or path.stat().st_size > MAX_FILE
                or path.suffix.lower() in SKIP_SUFFIXES):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if PROVIDER.search(line):
                findings.append(f"{name}:{number}: provider credential pattern")
            for match in KEY.finditer(line):
                value = match.group(2)
                if not PLACEHOLDER.search(value) and entropy(value) >= 3.4:
                    findings.append(f"{name}:{number}: literal {match.group(1)}")
    for finding in sorted(set(findings)):
        print(finding)
    if findings:
        print("credential-shaped literals found; replace them with environment references")
        return 1
    print("tracked-tree credential scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
