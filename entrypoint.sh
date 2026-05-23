#!/bin/sh
# entrypoint.sh - Ensures config.yaml is a file, not a directory
# Docker bind mount creates a directory if host path does not exist

if [ -d "/app/config.yaml" ]; then
    echo "⚠️  config.yaml is a directory (created by Docker bind mount). Recreating file..."
    rm -rf /app/config.yaml
    cp /app/config.yaml.default /app/config.yaml
    echo "✅ config.yaml recreated from image default"
fi

exec "$@"
