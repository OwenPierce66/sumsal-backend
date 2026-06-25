# Stage 1: Builder
# Pinning bookworm specifically to avoid the memory-heavy 'Trixie/Testing' repositories
FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

# Accept an argument to decide which requirements to use (default to false)
ARG DEV=false

# Prevent Python from writing .pyc files and keep stdout unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 

# Install system build dependencies (needed for psycopg2 and other C-extensions)
# Added cache mount for apt to speed up system installs and reduce memory pressure
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip 
COPY requirements.txt .
COPY requirements-dev.txt .

# Install dependencies to a temporary location (Conditional Dev Install)
# Added cache mount for pip. This prevents the 11,000 lines of re-downloading
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$DEV" = "true" ]; \
    then pip install --no-cache-dir --prefix=/install -r requirements-dev.txt; \
    else pip install --no-cache-dir --prefix=/install -r requirements.txt; \
    fi


# Stage 2: Final (Production Image)
FROM python:3.13-slim-bookworm

# Create a non-privileged system user
RUN useradd -m -r appuser

WORKDIR /app

# Install runtime system dependencies (only the bare minimum for Postgres)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    netcat-openbsd \
    gettext \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python packages from builder
COPY --from=builder /install /usr/local

# Copy code with correct ownership
COPY --chown=appuser:appuser . .

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH"

# Switch to non-root user
USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
