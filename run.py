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
    print("🚀 Starting NoteDiscovery...\n")
    
    # Check if requirements are installed
    try:
        import fastapi
        import uvicorn
    except ImportError:
        print("📦 Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    
    # Create data directories
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("plugins").mkdir(parents=True, exist_ok=True)
    
    # Get port from config or environment
    port = get_port()
    # Load read_only flag (new)
    read_only_enabled = "false"
    config_path = Path("config.yaml")
    if config_path.exists():
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                ro = config.get('read_only', {})
                if ro.get('enabled') is True:
                    read_only_enabled = "true"
        except Exception:
            pass
    os.environ["READ_ONLY_ENABLED"] = read_only_enabled
    print(f"🔓 Read-only public access: {'ENABLED' if read_only_enabled == 'true' else 'disabled'}")    
    print("✓ Dependencies installed")
    print("✓ Directories created")
    print("\n" + "="*50)
    print("🎉 NoteDiscovery is running!")
    print("="*50)
    print(f"\n📝 Open your browser to: http://localhost:{port}")
    print("\n💡 Tips:")
    print("   - Press Ctrl+C to stop the server")
    print("   - Your notes are in ./data/")
    print("   - Plugins go in ./plugins/")
    print(f"   - Change port with: PORT={port} python run.py")
    print("\n" + "="*50 + "\n")
    
    # Run the application
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

