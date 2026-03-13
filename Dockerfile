# Stage 1: Minify frontend assets
FROM node:20-alpine AS minifier

WORKDIR /build

# Install minification tools (esbuild for JS, html-minifier-terser for HTML)
RUN npm install -g esbuild html-minifier-terser

# Copy frontend files
COPY frontend/ ./frontend/

# Minify JavaScript (esbuild is ~100x faster than terser)
RUN esbuild frontend/app.js --minify --outfile=frontend/app.js --allow-overwrite && \
    esbuild frontend/sw.js --minify --outfile=frontend/sw.js --allow-overwrite

# Minify HTML files (handles inline CSS and JS too)
RUN html-minifier-terser \
    --collapse-whitespace \
    --remove-comments \
    --remove-redundant-attributes \
    --minify-css true \
    --minify-js true \
    -o frontend/index.html \
    frontend/index.html && \
    html-minifier-terser \
    --collapse-whitespace \
    --remove-comments \
    --minify-css true \
    --minify-js true \
    -o frontend/login.html \
    frontend/login.html

# Stage 2: Install Python dependencies
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

# Stage 3: Final minimal image
FROM python:3.11-slim

WORKDIR /app

# Copy only installed packages (no pip cache, no build artifacts)
COPY --from=builder /install /usr/local

# Copy minified frontend from minifier stage
COPY --from=minifier /build/frontend ./frontend

# Copy other application files
COPY backend ./backend
COPY config.yaml .
COPY VERSION .
COPY plugins ./plugins
COPY themes ./themes
COPY locales ./locales

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
# Use exec to replace shell with uvicorn (receives SIGTERM directly for graceful shutdown)
CMD exec uvicorn backend.main:app --host 0.0.0.0 --port $PORT --timeout-graceful-shutdown 2
