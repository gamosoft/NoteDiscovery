"""
NoteDiscovery MCP Server

A Model Context Protocol (MCP) server that enables AI assistants
to interact with NoteDiscovery notes.

Usage:
    # As module
    python -m mcp_server

    # As installed CLI
    notediscovery-mcp

Environment Variables:
    NOTEDISCOVERY_URL: NoteDiscovery server URL (default: http://localhost:8000)
    NOTEDISCOVERY_API_KEY: API key for authentication (optional)
"""

__version__ = "1.0.0"
__author__ = "NoteDiscovery"

from .server import main

__all__ = ["main", "__version__"]
