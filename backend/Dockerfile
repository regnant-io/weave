# Backend runs on Python 3.12 (stable wheels for the full scientific stack).
# architecture.md section 2: container-native from day one.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libs matplotlib/pandas need at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8000

# Seed on first boot if the DB is empty, then serve.
CMD ["sh", "-c", "python -m app.seed.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
