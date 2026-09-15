# Backend runs on Python 3.12 (stable wheels for the full scientific stack).
# architecture.md section 2: container-native from day one.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ARG INSTALL_DOCKER_CLI=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libs matplotlib/pandas need at runtime + Docker CLI for workspace execution
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    ca-certificates \
    gnupg \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Install the Docker client only in the local-development image that receives
# the Docker socket. The production API has neither the socket nor this client.
RUN if [ "$INSTALL_DOCKER_CLI" = "true" ]; then \
    install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# The package-manager helpers only bootstrap the optional local Docker CLI.
# Remove them from the production runtime command surface after dependencies are
# installed; the local override retains them by building with INSTALL_DOCKER_CLI.
RUN if [ "$INSTALL_DOCKER_CLI" != "true" ]; then \
      apt-get purge -y --auto-remove curl gnupg lsb-release \
      && rm -rf /var/lib/apt/lists/* \
          /usr/local/lib/python3.12/site-packages/pip* \
          /usr/local/bin/pip*; \
    fi

RUN groupadd --gid 10001 weave \
    && useradd --uid 10001 --gid weave --create-home --shell /usr/sbin/nologin weave

COPY --chown=weave:weave . .
RUN mkdir -p /app/var && chown -R weave:weave /app/var

USER weave

EXPOSE 8000

# Deployed databases are migration-owned. Local SQLite keeps the zero-service
# create_all path so existing developer databases need no destructive bootstrap.
CMD ["sh", "-c", "case \"${WEAVE_ENVIRONMENT:-dev}\" in production|prod|staging) alembic upgrade head ;; *) python -m app.seed.seed ;; esac && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
