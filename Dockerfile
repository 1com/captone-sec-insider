# Production Dockerfile for EDGAR-SENTINEL v2 (Feature 018)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Install system build dependencies (OpenMP for LightGBM / XGBoost)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition
COPY pyproject.toml uv.lock ./

# Install python dependencies without development packages
RUN uv sync --frozen --no-dev --no-install-project

# Final runtime image
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

# Install runtime dependencies (OpenMP for LightGBM and curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source and configs
COPY src/ /app/src/
COPY config/ /app/config/
COPY pyproject.toml /app/pyproject.toml

# Install package in editable/wheel mode into existing venv
RUN /app/.venv/bin/pip install --no-deps -e .

# Create non-root user for security
RUN useradd -m -u 1000 sentinel && \
    mkdir -p /app/data && \
    chown -R sentinel:sentinel /app

USER sentinel

# Container environment
ENV HOST=0.0.0.0
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Production Health Check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/freshness || exit 1

# Launch the FastAPI equity research terminal
CMD ["sentinel", "serve", "--host", "0.0.0.0", "--port", "8080"]

