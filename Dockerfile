# Digest-pinned hermetic base (resolved 3.12.7-slim-bookworm). Refresh with:
#   python scripts/pin_hashes.py
FROM python:3.12.7-slim-bookworm@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for better layer caching
COPY pyproject.toml .
COPY setup.py .
COPY README.md .
COPY requirements.lock .

# Install Python dependencies from the hash-pinned lockfile (reproducible,
# hash-checked). Fail loudly; do not swallow pip errors.
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && \
    pip install --no-cache-dir -e . --no-deps

# Copy application code (only what the app needs)
COPY deepans_code/ deepans_code/
COPY apps/ apps/
COPY Deepancode.json .
COPY opencode.json .
COPY claude-fable-5.md .

# Create non-root user
RUN useradd -m -u 1000 deepans && \
    mkdir -p /home/deepans/.deepans-code && \
    chown -R deepans:deepans /home/deepans/.deepans-code /app

USER deepans

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import deepans_code; print('ok')" || exit 1

# CLI app: no ports exposed by default. Override CMD to run API/WS servers.
# Default entrypoint
ENTRYPOINT ["deepans-code"]
