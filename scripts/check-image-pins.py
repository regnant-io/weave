"""Fail a release when a production image can move without a code change."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

for dockerfile in ROOT.rglob("Dockerfile"):
    for number, line in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("FROM "):
            image = line.split()[1]
            if "@sha256:" not in image:
                errors.append(f"{dockerfile.relative_to(ROOT)}:{number}: unpinned FROM {image}")


def service_image(path: Path, service: str) -> str | None:
    """Read the image under one top-level Compose service without PyYAML."""
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\s*\n(?P<body>(?:^    .*\n?)*)",
        text,
    )
    if not match:
        return None
    image = re.search(r"(?m)^    image:\s*(\S+)", match.group("body"))
    return image.group(1) if image else None


for compose, services in (
    (ROOT / "docker-compose.yml", ("postgres", "redis")),
    (ROOT / "docker-compose.production.yml", ("caddy",)),
):
    for service in services:
        image = service_image(compose, service)
        if not image or "@sha256:" not in image:
            errors.append(f"{compose.name}: production service {service!r} is not digest-pinned")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("production container images are digest-pinned")
