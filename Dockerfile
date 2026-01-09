# Stage 1: Builder
FROM python:3.13-slim AS builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 
RUN pip install --upgrade pip 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final
FROM python:3.13-slim
RUN useradd -m -r appuser && mkdir /app && chown -R appuser /app
WORKDIR /app

# Copy dependencies
COPY --from=builder /usr/local/lib/python3.13/ /usr/local/lib/python3.13/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy code
COPY --chown=appuser:appuser . .

# We copy the entrypoint separately to make sure it has the right owner
COPY --chown=appuser:appuser entrypoint.sh /entrypoint.sh
# We make it executable so Linux is allowed to run it as a script
RUN chmod +x /entrypoint.sh

# Environment
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 

# Switch to root briefly to ensure entrypoint is executable if needed, 
# but usually, appuser is fine if chmod was run correctly.
USER appuser

# ENTRYPOINT tells Docker: "No matter what, run this script first."
# This is where your migrations happen automatically!
ENTRYPOINT ["/entrypoint.sh"]