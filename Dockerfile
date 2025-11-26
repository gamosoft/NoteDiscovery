# Stage 1: Install dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt && \
    # Clean up unnecessary files to reduce image size
    find /install -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find /install -type f -name "*.pyc" -delete && \
    find /install -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /install -type d -name "*.dist-info" -exec rm -rf {}/RECORD {} + 2>/dev/null || true

# Stage 2: Final minimal image
FROM python:3.11-slim

WORKDIR /app

# Copy only installed packages (no pip cache, no build artifacts)
COPY --from=builder /install /usr/local

# Copy application files
COPY backend ./backend
COPY frontend ./frontend
COPY config.yaml .
COPY VERSION .
COPY plugins ./plugins
COPY themes ./themes
COPY generate_password.py .

# Create data directory
RUN mkdir -p data

# Expose port (default, can be overridden)
EXPOSE 8000

# Set default port (can be overridden via environment variable)
ENV PORT=8000

# Health check (uses PORT env var)
HEALTHCHECK --interval=60s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\", \"8000\")}/health')"

# Run the application (shell form to allow environment variable expansion)
CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT

