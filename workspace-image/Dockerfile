# Weave developer-workspace image.
#
# This is the runtime for `services/workspace` — where the assistant BUILDS
# software: installs dependencies, downloads assets, runs test suites, bundles
# apps. It is NOT the analysis sandbox (that one has no network and an import
# allowlist, and it must stay that way).
#
# Build once, then the backend reuses it for every exec:
#   docker build -t weave-workspace:latest ./workspace-image
#
# Containers are started with --rm, --cap-drop ALL, --security-opt
# no-new-privileges, a non-root user, and hard memory/CPU/PID limits. Only the
# bind-mounted /workspace survives a run.

FROM node:20-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    # Keep caches on the mounted volume so a rebuilt container still benefits
    # from a previous `npm install` in the same project.
    NPM_CONFIG_CACHE=/workspace/.cache/npm \
    PIP_CACHE_DIR=/workspace/.cache/pip \
    HOME=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      git curl ca-certificates unzip zip tar gzip \
      build-essential pkg-config \
      imagemagick ffmpeg \
      # Headless Chromium dependencies, so a generated app can be smoke-tested
      # or screenshotted without a second image.
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
      libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Debian marks the system Python as externally managed; the workspace is
# disposable, so allow plain `pip install` rather than forcing every generated
# project to create a venv first.
RUN python3 -m pip config set global.break-system-packages true || true

# Tools the model reaches for constantly. Preinstalling them means a first
# request doesn't spend 90s on npx cold-start.
RUN npm install -g --no-audit --no-fund \
      typescript@5 tsx@4 esbuild@0.24 vite@5 serve@14 \
    && npm cache clean --force

RUN python3 -m pip install --no-cache-dir \
      requests pytest black ruff pillow

# `node` (uid 1000) already exists in the base image and matches the uid the
# backend passes via --user, so bind-mounted files are writable without root.
WORKDIR /workspace

CMD ["bash"]
