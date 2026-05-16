# ── Stage 1: Build ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/
COPY static/ ./static/
COPY skills/ ./skills/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY main.py ./

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Create writable directories
RUN mkdir -p /app/sandbox_workspace /app/chroma_db /app/user_skills /app/cached_skills && \
    chown -R appuser:appuser /app

# Environment defaults
ENV APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    LOG_FORMAT=json \
    LOG_LEVEL=INFO

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"] || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
