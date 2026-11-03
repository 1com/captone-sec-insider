# Production Dockerfile for EDGAR-SENTINEL v2 (Feature 018)
FROM ghcr.io/astral-sh/uv:latest AS uv_bin

FROM debian:bookworm-slim AS builder

# Install uv from the official binary
COPY --from=uv_bin /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON=3.14
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python

# Install dependencies first for layer caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --python 3.14

# Copy source code and install project into virtualenv
COPY src/ /app/src/
COPY config/ /app/config/
COPY pyproject.toml uv.lock README.md /app/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --python 3.14

# Final runtime image
FROM debian:bookworm-slim AS runner

WORKDIR /app

# Install runtime dependencies (OpenMP for LightGBM/XGBoost, curl for healthcheck, ca-certificates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python standalone binaries from builder
COPY --from=builder /opt/uv/python /opt/uv/python
RUN chmod -R a+rx /opt/uv/python

# Copy virtual environment and project code from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/config /app/config
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH"

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
