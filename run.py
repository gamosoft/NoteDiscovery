#!/usr/bin/env python3
"""
Quick start script for NoteDiscovery
Run this to start the application without Docker
"""

import sys
import os
import subprocess
from pathlib import Path

try:
    import colorama
    colorama.just_fix_windows_console()
except ImportError:
    colorama = None

def get_port():
    """Get port from: 1) ENV variable, 2) config.yaml, 3) default 8000"""
    # Priority 1: Environment variable
    if os.getenv("PORT"):
        return os.getenv("PORT")
    
    # Priority 2: config.yaml
    config_path = Path("config.yaml")
    if config_path.exists():
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config and 'server' in config and 'port' in config['server']:
                    return str(config['server']['port'])
        except Exception:
            pass  # Fall through to default
    
    # Priority 3: Default
    return "8000"

def main():
    # Make sure runtime deps are present before invoking uvicorn.
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        print("Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    Path("data").mkdir(parents=True, exist_ok=True)
    Path("plugins").mkdir(parents=True, exist_ok=True)

    port = get_port()

    # Short pre-launch banner. Detailed startup logs come from uvicorn /
    # backend.main below (INFO: / WARNING: / ERROR:), so the user can tell
    # exactly when the server is actually accepting connections.
    print(f"🚀 NoteDiscovery → http://localhost:{port}")
    print(f"   notes: ./data/   plugins: ./plugins/   stop: Ctrl+C")
    print()

    subprocess.call([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--reload",
        "--host", "0.0.0.0",
        "--port", port,
        "--timeout-graceful-shutdown", "2"
    ])

if __name__ == "__main__":
    main()

