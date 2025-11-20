"""
NoteDiscovery - Self-Hosted Markdown Knowledge Base
Main FastAPI application
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Form, Depends, APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import os
import yaml
import json
from pathlib import Path
from typing import List, Optional
import aiofiles
from datetime import datetime
import bcrypt

from .utils import (
    get_all_notes,
    get_note_content,
    save_note,
    delete_note,
    search_notes,
    parse_wiki_links,
    create_note_metadata,
    ensure_directories,
    create_folder,
    get_all_folders,
    move_note,
    move_folder,
    rename_folder,
    delete_folder,
    save_uploaded_image,
)
from .plugins import PluginManager
from .themes import get_available_themes, get_theme_css

# Load configuration
config_path = Path(__file__).parent.parent / "config.yaml"
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Initialize app
app = FastAPI(
    title=config['app']['name'],
    description=config['app']['tagline'],
    version=config['app']['version']
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware for authentication
app.add_middleware(
    SessionMiddleware,
    secret_key=config.get('security', {}).get('secret_key', 'insecure_default_key_change_this'),
    max_age=config.get('security', {}).get('session_max_age', 604800),  # 7 days default
    same_site='lax',
    https_only=False  # Set to True if using HTTPS
)

# Ensure required directories exist
ensure_directories(config)

# Initialize plugin manager
plugin_manager = PluginManager(config['storage']['plugins_dir'])

# Run app startup hooks
plugin_manager.run_hook('on_app_startup')

# Mount static files
static_path = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Mount data directory for serving images
data_path = Path(config['storage']['notes_dir'])
app.mount("/data", StaticFiles(directory=data_path), name="data")


# ============================================================================
# Custom Exception Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Custom exception handler for HTTP exceptions.
    Handles 401 errors specially:
    - For API requests: return JSON error
    - For page requests: redirect to login
    """
    # Only handle 401 errors specially
    if exc.status_code == 401:
        # Check if this is an API request
        if request.url.path.startswith('/api/'):
            return JSONResponse(
                status_code=401,
                content={"detail": exc.detail}
            )
        
        # For page requests, redirect to login
        return RedirectResponse(url='/login', status_code=303)
    
    # For all other HTTP exceptions, return default JSON response
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


# ============================================================================
# Authentication Helpers
# ============================================================================

def auth_enabled() -> bool:
    """Check if authentication is enabled in config"""
    return config.get('security', {}).get('enabled', False)


async def require_auth(request: Request):
    """Dependency to require authentication on protected routes"""
    if not auth_enabled():
        return  # Auth disabled, allow all
    
    if not request.session.get('authenticated'):
        # Always raise exception - route handlers will catch and redirect as needed
        raise HTTPException(status_code=401, detail="Not authenticated")


def verify_password(password: str) -> bool:
    """Verify password against stored hash"""
    password_hash = config.get('security', {}).get('password_hash', '')
    if not password_hash:
        return False
    
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception as e:
        print(f"Password verification error: {e}")
        return False


# ============================================================================
# Authentication Routes
# ============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    """Serve the login page"""
    if not auth_enabled():
        return RedirectResponse(url="/", status_code=303)
    
    # If already authenticated, redirect to home
    if request.session.get('authenticated'):
        return RedirectResponse(url="/", status_code=303)
    
    # Serve login page
    login_path = static_path / "login.html"
    async with aiofiles.open(login_path, 'r', encoding='utf-8') as f:
        content = await f.read()
    
    # Inject error message if present
    if error:
        content = content.replace('<!-- ERROR_CLASS_PLACEHOLDER -->', 'class="error"')
        content = content.replace('<!-- ERROR_MESSAGE_PLACEHOLDER -->', 
                                 f'<div class="error-message">{error}</div>')
    else:
        content = content.replace('<!-- ERROR_CLASS_PLACEHOLDER -->', '')
        content = content.replace('<!-- ERROR_MESSAGE_PLACEHOLDER -->', '')
    
    return content


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    """Handle login form submission"""
    if not auth_enabled():
        return RedirectResponse(url="/", status_code=303)
    
    # Verify password
    if verify_password(password):
        # Set session
        request.session['authenticated'] = True
        return RedirectResponse(url="/", status_code=303)
    else:
        # Redirect back to login with error message
        return RedirectResponse(url="/login?error=Incorrect+password.+Please+try+again.", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    """Log out the current user"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# ============================================================================
# Routers with Authentication
# ============================================================================

# Create API router with authentication dependency applied globally
api_router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)]  # Apply auth to ALL routes in this router
)

# Create pages router with authentication dependency applied globally
pages_router = APIRouter(
    dependencies=[Depends(require_auth)]  # Apply auth to ALL routes in this router
)


# ============================================================================
# Application Routes (with auth via router dependencies)
# ============================================================================

@pages_router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main application page"""
    index_path = static_path / "index.html"
    async with aiofiles.open(index_path, 'r', encoding='utf-8') as f:
        content = await f.read()
    return content


@api_router.get("")
async def api_documentation():
    """API Documentation - List all available endpoints"""
    return {
        "app": {
            "name": config['app']['name'],
            "version": config['app']['version'],
            "description": config['app']['tagline']
        },
        "endpoints": [
            {
                "method": "GET",
                "path": "/api",
                "description": "API documentation - lists all available endpoints",
                "response": "API documentation object"
            },
            {
                "method": "GET",
                "path": "/api/config",
                "description": "Get application configuration",
                "response": "{ name, tagline, version, searchEnabled }"
            },
            {
                "method": "GET",
                "path": "/api/themes",
                "description": "List all available themes",
                "response": "{ themes: [{ id, name, builtin }] }"
            },
            {
                "method": "GET",
                "path": "/api/themes/{theme_id}",
                "description": "Get CSS content for a specific theme",
                "parameters": {"theme_id": "Theme identifier (e.g., 'dark', 'light', 'dracula')"},
                "response": "{ css, theme_id }"
            },
            {
                "method": "GET",
                "path": "/api/notes",
                "description": "List all notes and folders",
                "response": "{ notes: [{ path, name, folder }], folders: [path] }"
            },
            {
                "method": "GET",
                "path": "/api/notes/{note_path}",
                "description": "Get content of a specific note",
                "parameters": {"note_path": "Path to note (e.g., 'test.md', 'folder/note.md')"},
                "response": "{ content }"
            },
            {
                "method": "POST",
                "path": "/api/notes/{note_path}",
                "description": "Create or update a note",
                "parameters": {"note_path": "Path to note"},
                "body": {"content": "Markdown content of the note"},
                "response": "{ success, message }"
            },
            {
                "method": "DELETE",
                "path": "/api/notes/{note_path}",
                "description": "Delete a note",
                "parameters": {"note_path": "Path to note"},
                "response": "{ success, message }"
            },
            {
                "method": "POST",
                "path": "/api/notes/move",
                "description": "Move a note to a different location",
                "body": {"oldPath": "Current note path", "newPath": "New note path"},
                "response": "{ success, oldPath, newPath }"
            },
            {
                "method": "POST",
                "path": "/api/folders",
                "description": "Create a new folder",
                "body": {"path": "Folder path (e.g., 'Projects', 'Work/2025')"},
                "response": "{ success, path }"
            },
            {
                "method": "POST",
                "path": "/api/folders/move",
                "description": "Move a folder to a different location",
                "body": {"oldPath": "Current folder path", "newPath": "New folder path"},
                "response": "{ success, oldPath, newPath }"
            },
            {
                "method": "POST",
                "path": "/api/folders/rename",
                "description": "Rename a folder",
                "body": {"oldPath": "Current folder path", "newPath": "New folder path"},
                "response": "{ success, oldPath, newPath }"
            },
            {
                "method": "GET",
                "path": "/api/search",
                "description": "Search notes by content",
                "parameters": {"q": "Search query string"},
                "response": "{ results: [{ path, name, folder, snippet }], query }"
            },
            {
                "method": "GET",
                "path": "/api/graph",
                "description": "Get graph data for note visualization (wiki links)",
                "response": "{ nodes: [{ id, label }], edges: [{ from, to }] }"
            },
            {
                "method": "GET",
                "path": "/api/plugins",
                "description": "List all loaded plugins",
                "response": "{ plugins: [{ id, name, version, enabled }] }"
            },
            {
                "method": "POST",
                "path": "/api/plugins/{plugin_name}/toggle",
                "description": "Enable or disable a plugin",
                "parameters": {"plugin_name": "Plugin identifier"},
                "body": {"enabled": "true/false"},
                "response": "{ success, plugin, enabled }"
            },
            {
                "method": "GET",
                "path": "/health",
                "description": "Health check endpoint",
                "response": "{ status: 'healthy', app, version }"
            }
        ],
        "notes": {
            "authentication": "Not required (add authentication in config.yaml if needed)",
            "base_url": "http://localhost:8000",
            "content_type": "application/json",
            "cors": "Enabled for all origins"
        },
        "examples": {
            "create_note": {
                "curl": "curl -X POST http://localhost:8000/api/notes/test.md -H 'Content-Type: application/json' -d '{\"content\": \"# Hello World\"}'",
                "description": "Create a new note named test.md"
            },
            "search_notes": {
                "curl": "curl http://localhost:8000/api/search?q=hello",
                "description": "Search for notes containing 'hello'"
            },
            "list_themes": {
                "curl": "curl http://localhost:8000/api/themes",
                "description": "Get all available themes"
            },
            "enable_plugin": {
                "curl": "curl -X POST http://localhost:8000/api/plugins/git_backup/toggle -H 'Content-Type: application/json' -d '{\"enabled\": true}'",
                "description": "Enable the git_backup plugin"
            }
        }
    }


@api_router.get("/config")
async def get_config():
    """Get app configuration for frontend"""
    return {
        "name": config['app']['name'],
        "tagline": config['app']['tagline'],
        "version": config['app']['version'],
        "searchEnabled": config['search']['enabled'],
        "security": {
            "enabled": config.get('security', {}).get('enabled', False)
        }
    }


@api_router.get("/themes")
async def list_themes():
    """Get all available themes"""
    themes_dir = Path(__file__).parent.parent / "themes"
    themes = get_available_themes(str(themes_dir))
    return {"themes": themes}


@app.get("/api/themes/{theme_id}") # Don't use the router here, as we want this route unsecured
async def get_theme(theme_id: str):
    """Get CSS for a specific theme"""
    themes_dir = Path(__file__).parent.parent / "themes"
    css = get_theme_css(str(themes_dir), theme_id)
    
    if not css:
        raise HTTPException(status_code=404, detail="Theme not found")
    
    return {"css": css, "theme_id": theme_id}


@api_router.post("/folders")
async def create_new_folder(data: dict):
    """Create a new folder"""
    try:
        folder_path = data.get('path', '')
        if not folder_path:
            raise HTTPException(status_code=400, detail="Folder path required")
        
        success = create_folder(config['storage']['notes_dir'], folder_path)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create folder")
        
        return {
            "success": True,
            "path": folder_path,
            "message": "Folder created successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/upload-image")
async def upload_image(file: UploadFile = File(...), note_path: str = Form(...)):
    """
    Upload an image file and save it to the attachments directory.
    Returns the relative path to the image for markdown linking.
    """
    try:
        # Validate file type
        allowed_types = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'}
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        
        # Get file extension
        file_ext = Path(file.filename).suffix.lower() if file.filename else ''
        
        if file.content_type not in allowed_types and file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: jpg, jpeg, png, gif, webp. Got: {file.content_type}"
            )
        
        # Read file data
        file_data = await file.read()
        
        # Validate file size (10MB max)
        max_size = 10 * 1024 * 1024  # 10MB in bytes
        if len(file_data) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: 10MB. Uploaded: {len(file_data) / 1024 / 1024:.2f}MB"
            )
        
        # Save the image
        image_path = save_uploaded_image(
            config['storage']['notes_dir'],
            note_path,
            file.filename,
            file_data
        )
        
        if not image_path:
            raise HTTPException(status_code=500, detail="Failed to save image")
        
        return {
            "success": True,
            "path": image_path,
            "filename": Path(image_path).name,
            "message": "Image uploaded successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/notes/move")
async def move_note_endpoint(data: dict):
    """Move a note to a different folder"""
    try:
        old_path = data.get('oldPath', '')
        new_path = data.get('newPath', '')
        
        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="Both oldPath and newPath required")
        
        success = move_note(config['storage']['notes_dir'], old_path, new_path)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to move note")
        
        # Run plugin hooks
        plugin_manager.run_hook('on_note_save', note_path=new_path, content='')
        
        return {
            "success": True,
            "oldPath": old_path,
            "newPath": new_path,
            "message": "Note moved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/folders/move")
async def move_folder_endpoint(data: dict):
    """Move a folder to a different location"""
    try:
        old_path = data.get('oldPath', '')
        new_path = data.get('newPath', '')
        
        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="Both oldPath and newPath required")
        
        success = move_folder(config['storage']['notes_dir'], old_path, new_path)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to move folder")
        
        return {
            "success": True,
            "oldPath": old_path,
            "newPath": new_path,
            "message": "Folder moved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/folders/rename")
async def rename_folder_endpoint(data: dict):
    """Rename a folder"""
    try:
        old_path = data.get('oldPath', '')
        new_path = data.get('newPath', '')
        
        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="Both oldPath and newPath required")
        
        success = rename_folder(config['storage']['notes_dir'], old_path, new_path)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to rename folder")
        
        return {
            "success": True,
            "oldPath": old_path,
            "newPath": new_path,
            "message": "Folder renamed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/folders/{folder_path:path}")
async def delete_folder_endpoint(folder_path: str):
    """Delete a folder and all its contents"""
    try:
        if not folder_path:
            raise HTTPException(status_code=400, detail="Folder path required")
        
        success = delete_folder(config['storage']['notes_dir'], folder_path)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete folder")
        
        return {
            "success": True,
            "path": folder_path,
            "message": "Folder deleted successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/notes")
async def list_notes():
    """List all notes with metadata"""
    try:
        notes = get_all_notes(config['storage']['notes_dir'])
        folders = get_all_folders(config['storage']['notes_dir'])
        return {"notes": notes, "folders": folders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/notes/{note_path:path}")
async def get_note(note_path: str):
    """Get a specific note's content"""
    try:
        content = get_note_content(config['storage']['notes_dir'], note_path)
        if content is None:
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Run on_note_load hook (can transform content, e.g., decrypt)
        transformed_content = plugin_manager.run_hook('on_note_load', note_path=note_path, content=content)
        if transformed_content is not None:
            content = transformed_content
        
        # Parse wiki links
        links = parse_wiki_links(content)
        
        return {
            "path": note_path,
            "content": content,
            "links": links,
            "metadata": create_note_metadata(config['storage']['notes_dir'], note_path)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/notes/{note_path:path}")
async def create_or_update_note(note_path: str, content: dict):
    """Create or update a note"""
    try:
        note_content = content.get('content', '')
        
        # Check if this is a new note (doesn't exist yet)
        existing_content = get_note_content(config['storage']['notes_dir'], note_path)
        is_new_note = existing_content is None
        
        # If creating a new note, run on_note_create hook to allow plugins to modify initial content
        if is_new_note:
            note_content = plugin_manager.run_hook_with_return(
                'on_note_create',
                note_path=note_path,
                initial_content=note_content
            )
        
        # Run on_note_save hook (can transform content, e.g., encrypt)
        transformed_content = plugin_manager.run_hook('on_note_save', note_path=note_path, content=note_content)
        if transformed_content is None:
            transformed_content = note_content
        
        success = save_note(config['storage']['notes_dir'], note_path, transformed_content)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save note")
        
        return {
            "success": True,
            "path": note_path,
            "message": "Note created successfully" if is_new_note else "Note saved successfully",
            "content": note_content  # Return the (potentially modified) content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/notes/{note_path:path}")
async def remove_note(note_path: str):
    """Delete a note"""
    try:
        success = delete_note(config['storage']['notes_dir'], note_path)
        
        if not success:
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Run plugin hooks
        plugin_manager.run_hook('on_note_delete', note_path=note_path)
        
        return {
            "success": True,
            "message": "Note deleted successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/search")
async def search(q: str):
    """Search notes by content"""
    try:
        if not config['search']['enabled']:
            raise HTTPException(status_code=403, detail="Search is disabled")
        
        results = search_notes(config['storage']['notes_dir'], q)
        
        # Run plugin hooks
        plugin_manager.run_hook('on_search', query=q, results=results)
        
        return {"results": results, "query": q}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/graph")
async def get_graph():
    """Get graph data for visualization"""
    try:
        notes = get_all_notes(config['storage']['notes_dir'])
        nodes = []
        edges = []
        
        # Build graph structure
        for note in notes:
            nodes.append({
                "id": note['path'],
                "label": note['name']
            })
            
            # Get links from this note
            content = get_note_content(config['storage']['notes_dir'], note['path'])
            if content:
                links = parse_wiki_links(content)
                for link in links:
                    edges.append({
                        "from": note['path'],
                        "to": link
                    })
        
        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/plugins")
async def list_plugins():
    """List all available plugins"""
    return {"plugins": plugin_manager.list_plugins()}


@api_router.get("/plugins/note_stats/calculate")
async def calculate_note_stats(content: str):
    """Calculate statistics for note content (if plugin enabled)"""
    try:
        plugin = plugin_manager.plugins.get('note_stats')
        if not plugin or not plugin.enabled:
            return {"enabled": False, "stats": None}
        
        stats = plugin.calculate_stats(content)
        return {"enabled": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/plugins/{plugin_name}/toggle")
async def toggle_plugin(plugin_name: str, enabled: dict):
    """Enable or disable a plugin"""
    try:
        is_enabled = enabled.get('enabled', False)
        if is_enabled:
            plugin_manager.enable_plugin(plugin_name)
        else:
            plugin_manager.disable_plugin(plugin_name)
        
        return {
            "success": True,
            "plugin": plugin_name,
            "enabled": is_enabled
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app": config['app']['name'],
        "version": config['app']['version']
    }


# Catch-all route for SPA (Single Page Application) routing
# This allows URLs like /folder/note to work for direct navigation
@pages_router.get("/{full_path:path}", response_class=HTMLResponse)
async def catch_all(full_path: str, request: Request):
    """
    Serve index.html for all non-API routes.
    This enables client-side routing (e.g., /folder/note)
    """
    # Skip if it's an API route or static file (shouldn't reach here, but just in case)
    if full_path.startswith('api/') or full_path.startswith('static/'):
        raise HTTPException(status_code=404, detail="Not found")
    
    # Serve index.html for all other routes
    index_path = static_path / "index.html"
    async with aiofiles.open(index_path, 'r', encoding='utf-8') as f:
        content = await f.read()
    return content


# ============================================================================
# Register Routers
# ============================================================================

# Register routers with the main app
# Authentication is applied via router dependencies
app.include_router(api_router)
app.include_router(pages_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=config['server']['host'],
        port=config['server']['port'],
        reload=config['server']['reload']
    )

