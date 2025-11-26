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
import re
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .utils import (
    get_all_notes,
    get_note_content,
    save_note,
    delete_note,
    search_notes,
    create_note_metadata,
    ensure_directories,
    create_folder,
    get_all_folders,
    move_note,
    move_folder,
    rename_folder,
    delete_folder,
    save_uploaded_image,
    validate_path_security,
    get_all_tags,
    get_notes_by_tag,
    get_templates,
    get_template_content,
    apply_template_placeholders,
)
from .plugins import PluginManager
from .themes import get_available_themes, get_theme_css

# Load configuration
config_path = Path(__file__).parent.parent / "config.yaml"
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Load version from VERSION file (single source of truth)
version_path = Path(__file__).parent.parent / "VERSION"
if not version_path.exists():
    raise FileNotFoundError("VERSION file not found. Please create it with the current version number.")
with open(version_path, 'r', encoding='utf-8') as f:
    version = f.read().strip()
    config['app']['version'] = version

# Environment variable overrides for authentication settings
# Allows different configs for local vs production deployments
if 'AUTHENTICATION_ENABLED' in os.environ:
    auth_enabled = os.getenv('AUTHENTICATION_ENABLED', 'false').lower() in ('true', '1', 'yes')
    config['authentication']['enabled'] = auth_enabled
    print(f"🔐 Authentication {'ENABLED' if auth_enabled else 'DISABLED'} (from AUTHENTICATION_ENABLED env var)")
else:
    print(f"🔐 Authentication {'ENABLED' if config.get('authentication', {}).get('enabled', False) else 'DISABLED'} (from config.yaml)")

# Allow password hash to be set via environment variable (useful for demos)
if 'AUTHENTICATION_PASSWORD_HASH' in os.environ:
    config['authentication']['password_hash'] = os.getenv('AUTHENTICATION_PASSWORD_HASH')
    print("🔑 Password hash loaded from AUTHENTICATION_PASSWORD_HASH env var")

# Allow secret key to be set via environment variable (for session security)
if 'AUTHENTICATION_SECRET_KEY' in os.environ:
    config['authentication']['secret_key'] = os.getenv('AUTHENTICATION_SECRET_KEY')
    print("🔐 Secret key loaded from AUTHENTICATION_SECRET_KEY env var")

# Initialize app
app = FastAPI(
    title=config['app']['name'],
    description=config['app']['tagline'],
    version=config['app']['version']
)

# CORS middleware configuration
# Use config.yaml to control allowed origins (default: ["*"] for self-hosted simplicity)
allowed_origins = config.get('server', {}).get('allowed_origins', ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
print(f"🌐 CORS allowed origins: {allowed_origins}")

# ============================================================================
# Security Helpers
# ============================================================================

def safe_error_message(error: Exception, user_message: str = "An error occurred") -> str:
    """
    Return safe error message for API responses.
    In debug mode, returns full error details.
    In production, returns generic message and logs full details server-side.
    
    Args:
        error: The caught exception
        user_message: User-friendly message to show in production
    
    Returns:
        Safe error message string
    """
    error_details = f"{type(error).__name__}: {str(error)}"
    
    # Always log the full error server-side
    print(f"⚠️  [ERROR] {error_details}")
    
    # In debug mode, return detailed error to help with development
    if config.get('server', {}).get('debug', False):
        return error_details
    
    # In production, return generic message (full details already logged)
    return user_message

# Session middleware for authentication
# Security: Session ID is regenerated after login to prevent session fixation attacks
app.add_middleware(
    SessionMiddleware,
    secret_key=config.get('authentication', {}).get('secret_key', 'insecure_default_key_change_this'),
    max_age=config.get('authentication', {}).get('session_max_age', 604800),  # 7 days default
    same_site='lax',  # Prevents CSRF attacks
    https_only=False  # Set to True if using HTTPS in production
)

# Demo mode - Centralizes all demo-specific restrictions
# When DEMO_MODE=true, enables rate limiting and other demo protections
# Add additional demo restrictions here as needed (e.g., disable certain features)
DEMO_MODE = os.getenv('DEMO_MODE', 'false').lower() in ('true', '1', 'yes')

if DEMO_MODE:
    # Enable rate limiting for demo deployments
    limiter = Limiter(key_func=get_remote_address, default_limits=["200/hour"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    print("🎭 DEMO MODE enabled - Rate limiting active")
else:
    # Production/self-hosted mode - no restrictions
    # Create a dummy limiter that doesn't actually limit
    class DummyLimiter:
        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    limiter = DummyLimiter()

# Ensure required directories exist
ensure_directories(config)

# Initialize plugin manager
plugin_manager = PluginManager(config['storage']['plugins_dir'])

# Run app startup hooks
plugin_manager.run_hook('on_app_startup')

# Mount static files
static_path = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=static_path), name="static")


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
    return config.get('authentication', {}).get('enabled', False)


async def require_auth(request: Request):
    """Dependency to require authentication on protected routes"""
    if not auth_enabled():
        return  # Auth disabled, allow all
    
    if not request.session.get('authenticated'):
        # Always raise exception - route handlers will catch and redirect as needed
        raise HTTPException(status_code=401, detail="Not authenticated")


def verify_password(password: str) -> bool:
    """Verify password against stored hash"""
    password_hash = config.get('authentication', {}).get('password_hash', '')
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
        # Session regeneration: Clear old session to prevent session fixation attacks
        # This forces the creation of a new session ID after successful authentication
        request.session.clear()
        
        # Set authenticated flag in the NEW session
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
                "path": "/api/tags",
                "description": "Get all tags used across all notes with their counts",
                "response": "{ tags: { tag_name: count, ... } }"
            },
            {
                "method": "GET",
                "path": "/api/tags/{tag_name}",
                "description": "Get all notes that have a specific tag",
                "parameters": {"tag_name": "Tag to filter by (case-insensitive)"},
                "response": "{ tag, count, notes: [{ path, name, folder, tags }] }"
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
                "description": "Get graph data for note visualization",
                "response": "{ nodes: [{ id, label }], edges: [ { source, target }] }"
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
        "demoMode": DEMO_MODE,  # Expose demo mode flag to frontend
        "authentication": {
            "enabled": config.get('authentication', {}).get('enabled', False)
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
@limiter.limit("30/minute")
async def create_new_folder(request: Request, data: dict):
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to create folder"))


@api_router.get("/images/{image_path:path}")
async def get_image(image_path: str):
    """
    Serve an image file with authentication protection.
    """
    try:
        notes_dir = config['storage']['notes_dir']
        full_path = Path(notes_dir) / image_path
        
        # Security: Validate path is within notes directory
        if not validate_path_security(notes_dir, full_path):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Check file exists and is an image
        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Validate it's an image file
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        if full_path.suffix.lower() not in allowed_extensions:
            raise HTTPException(status_code=400, detail="Not an image file")
        
        # Return the file
        return FileResponse(full_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to load image"))


@api_router.post("/upload-image")
@limiter.limit("20/minute")
async def upload_image(request: Request, file: UploadFile = File(...), note_path: str = Form(...)):
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
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to upload image"))


@api_router.post("/notes/move")
@limiter.limit("30/minute")
async def move_note_endpoint(request: Request, data: dict):
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to move note"))


@api_router.post("/folders/move")
@limiter.limit("20/minute")
async def move_folder_endpoint(request: Request, data: dict):
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to move folder"))


@api_router.post("/folders/rename")
@limiter.limit("30/minute")
async def rename_folder_endpoint(request: Request, data: dict):
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to rename folder"))


@api_router.delete("/folders/{folder_path:path}")
@limiter.limit("20/minute")
async def delete_folder_endpoint(request: Request, folder_path: str):
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to delete folder"))


# --- Tags Endpoints ---

@api_router.get("/tags")
async def list_tags():
    """
    Get all tags used across all notes with their counts.
    
    Returns:
        Dictionary mapping tag names to note counts
    """
    try:
        tags = get_all_tags(config['storage']['notes_dir'])
        return {"tags": tags}
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to load tags"))


@api_router.get("/tags/{tag_name}")
async def get_notes_by_tag_endpoint(tag_name: str):
    """
    Get all notes that have a specific tag.
    
    Args:
        tag_name: The tag to filter by (case-insensitive)
        
    Returns:
        List of notes matching the tag
    """
    try:
        notes = get_notes_by_tag(config['storage']['notes_dir'], tag_name)
        return {
            "tag": tag_name,
            "count": len(notes),
            "notes": notes
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get notes by tag"))


# --- Template Endpoints ---

@api_router.get("/templates")
@limiter.limit("120/minute")
async def list_templates(request: Request):
    """
    List all available templates from _templates folder.
    
    Returns:
        List of template metadata
    """
    try:
        templates = get_templates(config['storage']['notes_dir'])
        return {"templates": templates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to list templates"))


@api_router.get("/templates/{template_name}")
@limiter.limit("120/minute")
async def get_template(request: Request, template_name: str):
    """
    Get content of a specific template.
    
    Args:
        template_name: Name of the template (without .md extension)
        
    Returns:
        Template name and content
    """
    try:
        content = get_template_content(config['storage']['notes_dir'], template_name)
        
        if content is None:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return {
            "name": template_name,
            "content": content
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get template"))


@api_router.post("/templates/create-note")
@limiter.limit("60/minute")
async def create_note_from_template(request: Request, data: dict):
    """
    Create a new note from a template with placeholder replacement.
    
    Args:
        data: Dictionary containing templateName and notePath
        
    Returns:
        Success status, path, and created content
    """
    try:
        template_name = data.get('templateName', '')
        note_path = data.get('notePath', '')
        
        if not template_name or not note_path:
            raise HTTPException(status_code=400, detail="Template name and note path required")
        
        # Get template content
        template_content = get_template_content(config['storage']['notes_dir'], template_name)
        
        if template_content is None:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # Apply placeholder replacements
        final_content = apply_template_placeholders(template_content, note_path)
        
        # Save the note
        success = save_note(config['storage']['notes_dir'], note_path, final_content)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create note from template")
        
        # Run plugin hooks
        plugin_manager.run_hook('on_note_create', note_path=note_path, initial_content=final_content)
        
        return {
            "success": True,
            "path": note_path,
            "message": "Note created from template successfully",
            "content": final_content
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to create note from template"))


# --- Notes Endpoints ---

@api_router.get("/notes")
async def list_notes():
    """List all notes with metadata"""
    try:
        notes = get_all_notes(config['storage']['notes_dir'])
        folders = get_all_folders(config['storage']['notes_dir'])
        return {"notes": notes, "folders": folders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to list notes"))


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
        
        return {
            "path": note_path,
            "content": content,
            "metadata": create_note_metadata(config['storage']['notes_dir'], note_path)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to load note"))


@api_router.post("/notes/{note_path:path}")
@limiter.limit("60/minute")
async def create_or_update_note(request: Request, note_path: str, content: dict):
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to save note"))


@api_router.delete("/notes/{note_path:path}")
@limiter.limit("30/minute")
async def remove_note(request: Request, note_path: str):
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to delete note"))


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
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Search failed"))


@api_router.get("/graph")
async def get_graph():
    """Get graph data for note visualization (currently only returns nodes, link detection not implemented)"""
    try:
        notes = get_all_notes(config['storage']['notes_dir'])
        nodes = []
        edges = []
        note_ids = {note["path"] for note in notes}

        # Build graph structure - only nodes for now
        for note in notes:
            if note.get('type') == 'note':  # Only include actual notes
                nodes.append({
                    "id": note['path'],
                    "label": note['name']
                })

                content = get_note_content(
                    config['storage']['notes_dir'],
                    note['path']
                )

                # regex matches [*](*.md) case-insensitive
                pattern = re.compile(r'\[[^]]+\]\(([^)]+\.md)\)', re.IGNORECASE)
                for match in pattern.finditer(content):
                    target = match.group(1)
                    # Only add if it is an existing note
                    # will have to adjust if support for relative links is added
                    if target in note_ids:
                        edges.append({
                            "source": note['path'],
                            "target": target
                        })

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to generate graph data"))


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
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to calculate note statistics"))


@api_router.post("/plugins/{plugin_name}/toggle")
@limiter.limit("10/minute")
async def toggle_plugin(request: Request, plugin_name: str, enabled: dict):
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
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to toggle plugin"))


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

