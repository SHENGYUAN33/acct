# ── Stage 1: dependency builder ──────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /install

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.12/site-packages"

# Copy installed packages from builder
COPY --from=builder /install /install

WORKDIR /app

# Copy project source (uploads/ and .env* excluded via .dockerignore)
COPY . .

# Ensure uploads directory exists (Volume mount will overlay contents)
RUN mkdir -p /app/uploads

EXPOSE 8000

# alembic upgrade head is intentionally NOT run here.
# It must run against a live database, so docker-compose entrypoint handles it.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
