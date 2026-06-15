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
# It must run against a live database (docker-compose entrypoint / Cloud Run Job handles it).
# Cloud Run 以環境變數 PORT（預設 8080）告知監聽埠；以 shell 形式啟動才能展開 $PORT。
# docker-compose 會以自身 command/entrypoint 覆寫此 CMD（指定 --port 8000）。
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
