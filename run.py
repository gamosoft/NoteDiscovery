#!/usr/bin/env python3
"""
Quick start script for NoteDiscovery
Run this to start the application without Docker
"""

import sys
import subprocess
from pathlib import Path

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
    
    print("✓ Dependencies installed")
    print("✓ Directories created")
    print("\n" + "="*50)
    print("🎉 NoteDiscovery is running!")
    print("="*50)
    print("\n📝 Open your browser to: http://localhost:8000")
    print("\n💡 Tips:")
    print("   - Press Ctrl+C to stop the server")
    print("   - Your notes are in ./data/")
    print("   - Plugins go in ./plugins/")
    print("\n" + "="*50 + "\n")
    
    # Run the application
    subprocess.call([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--reload",
        "--host", "0.0.0.0",
        "--port", "8000"
    ])

if __name__ == "__main__":
    main()

