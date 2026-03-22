# =============================================================================
# Stage 1: Install dependencies
# =============================================================================
FROM python:3.12-slim AS deps

# Set environment variables for deterministic builds
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy only dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# =============================================================================
# Stage 2: Production application
# =============================================================================
FROM python:3.12-slim AS app

# Security: Create a non-root user
RUN groupadd --gid 1000 polyclaw && \
    useradd --uid 1000 --gid polyclaw --shell /bin/bash --create-home polyclaw

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Non-root user
    HOME=/home/polyclaw \
    PATH=/home/polyclaw/.local/bin:$PATH

WORKDIR /app

# Copy installed dependencies from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=polyclaw:polyclaw polyclaw/ ./polyclaw/
COPY --chown=polyclaw:polyclaw alembic/ ./alembic/
COPY --chown=polyclaw:polyclaw pyproject.toml ./

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Switch to non-root user
USER polyclaw

# Expose application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run as non-root user
ENTRYPOINT ["uvicorn", "polyclaw.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
