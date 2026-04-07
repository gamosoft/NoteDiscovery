"""
NoteDiscovery - Self-Hosted Markdown Knowledge Base
Main FastAPI application
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Form, Depends, APIRouter, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from starlette.middleware.sessions import SessionMiddleware
import os
import yaml
import json
from pathlib import Path
from typing import List, Optional
import aiofiles
from datetime import datetime
import bcrypt
import secrets
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .utils import (
    scan_notes_fast_walk,
    get_note_content,
    save_note,
    delete_note,
    search_notes,
    create_note_metadata,
    ensure_directories,
    create_folder,
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
    paginate,
    get_backlinks,
)
from .plugins import PluginManager
from .themes import get_available_themes, get_theme_css
from .share import (
    create_share_token,
    get_share_token,
    get_share_info,
    revoke_share_token,
    get_note_by_token,
    delete_token_for_note,
    update_token_path,
    get_all_shared_paths,
)
from .export import generate_export_html, embed_images_as_base64, convert_wikilinks_to_html, strip_frontmatter

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
# Read-only public mode (new)
if 'READ_ONLY_ENABLED' in os.environ:
    ro_enabled = os.getenv('READ_ONLY_ENABLED', 'false').lower() in ('true', '1', 'yes')
    config.setdefault('read_only', {})['enabled'] = ro_enabled
    print(f"🔓 Read-only public access: {'ENABLED' if ro_enabled else 'DISABLED'} (from READ_ONLY_ENABLED env var)")
else:
    print(f"🔓 Read-only public access: {'ENABLED' if config.get('read_only', {}).get('enabled', False) else 'DISABLED'} (from config.yaml)")
# Password configuration priority:
# 1. AUTHENTICATION_PASSWORD env var (hashed at startup)
# 2. authentication.password in config.yaml (hashed at startup)
# Default password is "admin" if nothing is configured
if 'AUTHENTICATION_PASSWORD' in os.environ:
    plain_password = os.getenv('AUTHENTICATION_PASSWORD', '').strip()
    if plain_password:
        config['authentication']['password_hash'] = bcrypt.hashpw(
            plain_password.encode('utf-8'), 
            bcrypt.gensalt()
        ).decode('utf-8')
        print("🔑 Password loaded from AUTHENTICATION_PASSWORD env var")
    else:
        print("⚠️  WARNING: AUTHENTICATION_PASSWORD env var is empty - ignoring")
elif config.get('authentication', {}).get('password', '').strip():
    plain_password = config['authentication']['password'].strip()
    config['authentication']['password_hash'] = bcrypt.hashpw(
        plain_password.encode('utf-8'), 
        bcrypt.gensalt()
    ).decode('utf-8')
    del config['authentication']['password']
    print("🔑 Password loaded from config.yaml")

# Allow secret key to be set via environment variable (for session security)
if 'AUTHENTICATION_SECRET_KEY' in os.environ:
    config['authentication']['secret_key'] = os.getenv('AUTHENTICATION_SECRET_KEY')
    print("🔐 Secret key loaded from AUTHENTICATION_SECRET_KEY env var")

# API key configuration for external integrations (MCP servers, scripts, etc.)
# Priority: AUTHENTICATION_API_KEY env var > authentication.api_key in config.yaml
if 'AUTHENTICATION_API_KEY' in os.environ:
    api_key_value = os.getenv('AUTHENTICATION_API_KEY', '').strip()
    if api_key_value:
        config['authentication']['api_key'] = api_key_value
        print("🔑 API key loaded from AUTHENTICATION_API_KEY env var")
    else:
        config['authentication']['api_key'] = ''
elif config.get('authentication', {}).get('api_key', '').strip():
    print("🔑 API key loaded from config.yaml")
else:
    config['authentication']['api_key'] = ''

# Warnings for missing authentication methods (only when auth is enabled)
if config.get('authentication', {}).get('enabled', False):
    _has_password = bool(config.get('authentication', {}).get('password_hash', ''))
    _has_api_key = bool(config.get('authentication', {}).get('api_key', '').strip())
    _secret_key = config.get('authentication', {}).get('secret_key', '')
    _is_default_secret = _secret_key in ('', 'change_this_to_a_random_secret_key_in_production')
    
    if not _has_password and not _has_api_key:
        print("🚨 CRITICAL: Authentication enabled but NO auth methods configured - ALL access will be denied!")
    else:
        if not _has_password:
            print("⚠️  WARNING: No password configured - web UI login will not work")
        if not _has_api_key:
            print("⚠️  WARNING: No API key configured - external integrations will require session cookies")
    
    if _is_default_secret:
        print("🚨 SECURITY WARNING: Using default secret_key - sessions can be forged! Change it in config.yaml")

# OpenAPI tag metadata for grouping endpoints in Swagger UI
tags_metadata = [
    {"name": "Notes", "description": "Create, read, update, delete notes"},
    {"name": "Folders", "description": "Folder management"},
    {"name": "Media", "description": "Media files (images, audio, video, PDF)"},
    {"name": "Search", "description": "Full-text search"},
    {"name": "Sharing", "description": "Public note sharing via tokens"},
    {"name": "Tags", "description": "Tag-based organization"},
    {"name": "Templates", "description": "Note templates"},
    {"name": "Themes", "description": "UI theme management"},
    {"name": "Locales", "description": "Internationalization (i18n)"},
    {"name": "Graph", "description": "Note relationship graph"},
    {"name": "Plugins", "description": "Plugin management"},
    {"name": "System", "description": "Health checks and configuration"},
]

# Initialize app
app = FastAPI(
    title=config['app']['name'],
    version=config['app']['version'],
    docs_url='/api', # Default is /docs
    redoc_url=None,    # Disable ReDoc at /redoc
    openapi_tags=tags_metadata
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

# ===========================================================
# =================
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
ALREADY_DONATED = os.getenv('ALREADY_DONATED', 'false').lower() in ('true', '1', 'yes')

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

# PWA Service Worker - must be served from root for proper scope
@app.get("/sw.js", include_in_schema=False)
@limiter.limit("30/minute")
async def service_worker(request: Request):
    """Serve the PWA service worker from root path for proper scope.
    Injects the app version from VERSION file for cache invalidation."""
    sw_path = static_path / "sw.js"
    if sw_path.exists():
        async with aiofiles.open(sw_path, 'r', encoding='utf-8') as f:
            content = await f.read()
        # Inject app version into cache name
        content = content.replace('__APP_VERSION__', version)
        return Response(content=content, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Service worker not found")


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

# Security schemes for API authentication (auto_error=False for optional auth)
# These are automatically added to OpenAPI docs (/api)
bearer_scheme = HTTPBearer(auto_error=False, description="Bearer token authentication")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="API key header authentication")


def auth_enabled() -> bool:
    """Check if authentication is enabled in config"""
    return config.get('authentication', {}).get('enabled', False)

def read_only_enabled() -> bool:
    """Check if public read-only mode is active"""
    return config.get('read_only', {}).get('enabled', False)

def get_api_key() -> str:
    """Get the configured API key (empty string if not set)"""
    return config.get('authentication', {}).get('api_key', '').strip()


def verify_api_key(provided_key: str) -> bool:
    """
    Verify an API key using constant-time comparison.
    
    Uses secrets.compare_digest to prevent timing attacks where an attacker
    could determine the correct key by measuring response times.
    
    Args:
        provided_key: The API key provided in the request
        
    Returns:
        True if the key is valid, False otherwise
    """
    configured_key = get_api_key()
    
    # No API key configured = API key auth disabled
    if not configured_key:
        return False
    
    # Empty provided key is always invalid
    if not provided_key:
        return False
    
    # Constant-time comparison to prevent timing attacks
    try:
        return secrets.compare_digest(provided_key.encode('utf-8'), configured_key.encode('utf-8'))
    except Exception:
        return False


async def require_auth(
    request: Request,
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Depends(api_key_header)
):
    """
    Dependency to require authentication on protected routes.
    
    Supports two authentication methods:
    1. Session-based auth (web UI login with password)
    2. API key auth (for external integrations like MCP servers)
    
    API key can be provided via:
    - Authorization: Bearer YOUR_API_KEY
    - X-API-Key: YOUR_API_KEY
    
    Raises:
        HTTPException: 401 if authentication fails
    """
    if not auth_enabled():
        return  # Auth disabled, allow all
    
    # Public read-only mode: anyone can read (GET/HEAD/OPTIONS), writes still need auth
    if read_only_enabled() and request.method.upper() in ("GET", "HEAD", "OPTIONS"):
        return  # public read access granted
    
    # Method 1: Check Bearer token (parsed by FastAPI's HTTPBearer)
    if bearer_credentials and verify_api_key(bearer_credentials.credentials):
        return  # Valid Bearer token - authenticated
    
    # Method 2: Check X-API-Key header (parsed by FastAPI's APIKeyHeader)
    if x_api_key and verify_api_key(x_api_key):
        return  # Valid API key header - authenticated
    
    # Method 3: Check session-based authentication (web UI)
    if request.session.get('authenticated'):
        return  # Valid session - authenticated
    
    # No valid authentication method - deny access
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

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
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
    
    # Inject app name throughout the login page
    app_name = config['app']['name']
    content = content.replace('NoteDiscovery', app_name)
    
    return content


@app.post("/login", include_in_schema=False)
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
        # Redirect back to login with error code (frontend will translate)
        return RedirectResponse(url="/login?error=incorrect_password", status_code=303)


@app.get("/logout", include_in_schema=False)
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

@api_router.get("/config", tags=["System"])
async def get_config():
    """Get app configuration for frontend"""
    return {
        "name": config['app']['name'],
        "version": config['app']['version'],
        "searchEnabled": config['search']['enabled'],
        "demoMode": DEMO_MODE,  # Expose demo mode flag to frontend
        "alreadyDonated": ALREADY_DONATED,  # Hide support buttons if true
        "authentication": {
            "enabled": config.get('authentication', {}).get('enabled', False)
        }
    }


@api_router.get("/themes", tags=["Themes"])
async def list_themes():
    """Get all available themes"""
    themes_dir = Path(__file__).parent.parent / "themes"
    themes = get_available_themes(str(themes_dir))
    return {"themes": themes}


@app.get("/api/themes/{theme_id}", tags=["Themes"]) # Don't use the router here, as we want this route unsecured
async def get_theme(theme_id: str):
    """Get CSS for a specific theme"""
    themes_dir = Path(__file__).parent.parent / "themes"
    css = get_theme_css(str(themes_dir), theme_id)
    
    if not css:
        raise HTTPException(status_code=404, detail="Theme not found")
    
    return {"css": css, "theme_id": theme_id}


# Locales endpoints (unauthenticated - needed for login page and initial load)
@app.get("/api/locales", tags=["Locales"])
async def get_available_locales():
    """Get list of available locales"""
    import json
    locales_dir = Path(__file__).parent.parent / "locales"
    locales = []
    
    if locales_dir.exists():
        for file in sorted(locales_dir.glob("*.json")):
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    meta = data.get('_meta', {})
                    locales.append({
                        "code": meta.get('code', file.stem),
                        "name": meta.get('name', file.stem),
                        "flag": meta.get('flag', '🌐')
                    })
            except (json.JSONDecodeError, IOError):
                # Skip invalid locale files
                continue
    
    return {"locales": locales}


@app.get("/api/locales/{locale_code}", tags=["Locales"])
async def get_locale(locale_code: str):
    """Get translations for a specific locale"""
    import json
    import re
    
    # Security: Validate locale_code to prevent path traversal
    # Only allow alphanumeric, hyphens, and underscores (e.g., "en", "pt-BR", "zh_CN")
    if not re.match(r'^[a-zA-Z0-9_-]+$', locale_code):
        raise HTTPException(status_code=400, detail="Invalid locale code")
    
    locales_dir = Path(__file__).parent.parent / "locales"
    locale_file = locales_dir / f"{locale_code}.json"
    
    # Security: Ensure resolved path is still within locales directory
    if not locale_file.resolve().is_relative_to(locales_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid locale code")
    
    if not locale_file.exists():
        raise HTTPException(status_code=404, detail="Locale not found")
    
    try:
        with open(locale_file, 'r', encoding='utf-8') as f:
            translations = json.load(f)
        return translations
    except (json.JSONDecodeError, IOError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to load locale: {str(e)}")


@api_router.post("/folders", tags=["Folders"])
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


@api_router.get("/media/{media_path:path}", tags=["Media"])
async def get_media(media_path: str):
    """
    Serve a media file (image, audio, video, PDF) with authentication protection.
    """
    try:
        from backend.utils import ALL_MEDIA_EXTENSIONS
        
        notes_dir = config['storage']['notes_dir']
        full_path = Path(notes_dir) / media_path
        
        # Security: Validate path is within notes directory
        if not validate_path_security(notes_dir, full_path):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Check file exists
        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        
        # Validate it's an allowed media file
        if full_path.suffix.lower() not in ALL_MEDIA_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Not an allowed media file")
        
        # Return the file
        return FileResponse(full_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to load media file"))


@api_router.post("/upload-media", tags=["Media"])
@limiter.limit("20/minute")
async def upload_media(request: Request, file: UploadFile = File(...), note_path: str = Form(...)):
    """
    Upload a media file (image, audio, video, PDF) and save it to the attachments directory.
    Returns the relative path for markdown linking.
    """
    try:
        from backend.utils import ALL_MEDIA_EXTENSIONS, get_media_type
        
        # Allowed MIME types for each category
        allowed_types = {
            # Images
            'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
            # Audio
            'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/m4a', 'audio/x-m4a',
            # Video
            'video/mp4', 'video/webm', 'video/quicktime', 'video/x-msvideo',
            # Documents
            'application/pdf',
        }
        
        # Get file extension
        file_ext = Path(file.filename).suffix.lower() if file.filename else ''
        
        if file.content_type not in allowed_types and file_ext not in ALL_MEDIA_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: images, audio (mp3), video (mp4), PDF. Got: {file.content_type}"
            )
        
        # Read file data
        file_data = await file.read()
        
        # Validate file size - different limits for different types
        media_type = get_media_type(file.filename) if file.filename else None
        
        # Size limits: images 10MB, audio 50MB, video 100MB, PDF 20MB
        size_limits = {
            'image': 10 * 1024 * 1024,
            'audio': 50 * 1024 * 1024,
            'video': 100 * 1024 * 1024,
            'document': 20 * 1024 * 1024,
        }
        max_size = size_limits.get(media_type, 10 * 1024 * 1024)
        
        if len(file_data) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size for {media_type or 'this type'}: {max_size // (1024*1024)}MB. Uploaded: {len(file_data) / 1024 / 1024:.2f}MB"
            )
        
        # Save the file (reusing image save function - it works for any file)
        file_path = save_uploaded_image(
            config['storage']['notes_dir'],
            note_path,
            file.filename,
            file_data
        )
        
        if not file_path:
            raise HTTPException(status_code=500, detail="Failed to save file")
        
        return {
            "success": True,
            "path": file_path,
            "filename": Path(file_path).name,
            "type": media_type,
            "message": f"{media_type.capitalize() if media_type else 'File'} uploaded successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to upload file"))


@api_router.post("/media/move", tags=["Media"])
@limiter.limit("30/minute")
async def move_media_endpoint(request: Request, data: dict):
    """Move a media file to a different folder"""
    try:
        from backend.utils import ALL_MEDIA_EXTENSIONS
        
        old_path = data.get('oldPath', '')
        new_path = data.get('newPath', '')
        
        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="Both oldPath and newPath required")
        
        notes_dir = config['storage']['notes_dir']
        old_full_path = Path(notes_dir) / old_path
        new_full_path = Path(notes_dir) / new_path
        
        # Security: Validate paths are within notes directory
        if not validate_path_security(notes_dir, old_full_path):
            raise HTTPException(status_code=403, detail="Invalid source path")
        if not validate_path_security(notes_dir, new_full_path):
            raise HTTPException(status_code=403, detail="Invalid destination path")
        
        # Validate it's a media file
        if old_full_path.suffix.lower() not in ALL_MEDIA_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Not a valid media file")
        
        # Check source exists
        if not old_full_path.exists():
            raise HTTPException(status_code=404, detail=f"Media file not found: {old_path}")
        
        # Check target doesn't exist
        if new_full_path.exists():
            raise HTTPException(status_code=409, detail=f"A file already exists at: {new_path}")
        
        # Create parent directory if needed
        new_full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Move the file
        import shutil
        shutil.move(str(old_full_path), str(new_full_path))
        
        return {"success": True, "message": "Media moved successfully", "newPath": new_path}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to move media file"))


@api_router.post("/notes/move", tags=["Notes"])
@limiter.limit("30/minute")
async def move_note_endpoint(request: Request, data: dict):
    """Move a note to a different folder"""
    try:
        old_path = data.get('oldPath', '')
        new_path = data.get('newPath', '')
        
        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="Both oldPath and newPath required")
        
        success, error_msg = move_note(config['storage']['notes_dir'], old_path, new_path)
        
        if not success:
            raise HTTPException(status_code=400, detail=error_msg or "Failed to move note")
        
        # Update share token path if note was shared
        update_token_path(config['storage']['notes_dir'], old_path, new_path)
        
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


@api_router.post("/folders/move", tags=["Folders"])
@limiter.limit("20/minute")
async def move_folder_endpoint(request: Request, data: dict):
    """Move a folder to a different location"""
    try:
        old_path = data.get('oldPath', '')
        new_path = data.get('newPath', '')
        
        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="Both oldPath and newPath required")
        
        success, error_msg = move_folder(config['storage']['notes_dir'], old_path, new_path)
        
        if not success:
            raise HTTPException(status_code=400, detail=error_msg or "Failed to move folder")
        
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


@api_router.post("/folders/rename", tags=["Folders"])
@limiter.limit("30/minute")
async def rename_folder_endpoint(request: Request, data: dict):
    """Rename a folder"""
    try:
        old_path = data.get('oldPath', '')
        new_path = data.get('newPath', '')
        
        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="Both oldPath and newPath required")
        
        success, error_msg = rename_folder(config['storage']['notes_dir'], old_path, new_path)
        
        if not success:
            raise HTTPException(status_code=400, detail=error_msg or "Failed to rename folder")
        
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


@api_router.delete("/folders/{folder_path:path}", tags=["Folders"])
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

@api_router.get("/tags", tags=["Tags"])
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


@api_router.get("/tags/{tag_name}", tags=["Tags"])
async def get_notes_by_tag_endpoint(
    tag_name: str,
    limit: Optional[int] = None,
    offset: int = 0
):
    """
    Get all notes that have a specific tag with optional pagination.

    Args:
        tag_name: The tag to filter by (case-insensitive)
        limit: Maximum number of notes to return (optional, no default limit)
        offset: Number of notes to skip (default: 0)

    Returns:
        List of notes matching the tag
    
    Examples:
        GET /api/tags/docker              -> All notes with #docker tag
        GET /api/tags/docker?limit=10     -> First 10 notes with #docker tag
    """
    try:
        notes = get_notes_by_tag(config['storage']['notes_dir'], tag_name)
        
        # Apply pagination with consistent sorting by path
        paginated = paginate(
            items=notes,
            limit=limit,
            offset=offset,
            sort_key=lambda x: x.get('path', '').lower()
        )
        
        response = {
            "tag": tag_name,
            "count": paginated.total,
            "notes": paginated.items
        }
        
        # Include pagination metadata only when limit is specified
        if limit is not None:
            response["pagination"] = paginated.to_dict()
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get notes by tag"))


# --- Template Endpoints ---

@api_router.get("/templates", tags=["Templates"])
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


@api_router.get("/templates/{template_name}", tags=["Templates"])
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


@api_router.post("/templates/create-note", tags=["Templates"])
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
        
        # Run on_note_create hook BEFORE saving (allows plugins to modify initial content)
        final_content = plugin_manager.run_hook_with_return(
            'on_note_create',
            note_path=note_path,
            initial_content=final_content
        )
        
        # Run on_note_save hook (can transform content, e.g., encrypt)
        transformed_content = plugin_manager.run_hook('on_note_save', note_path=note_path, content=final_content)
        if transformed_content is None:
            transformed_content = final_content
        
        # Save the note with the (potentially modified/transformed) content
        success = save_note(config['storage']['notes_dir'], note_path, transformed_content)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create note from template")
        
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

@api_router.get("/notes", tags=["Notes"])
async def list_notes(
    limit: Optional[int] = None,
    offset: int = 0
):
    """
    List all notes with metadata.
    
    Supports optional pagination for API consumers (MCP, scripts):
    - No parameters: Returns all notes (frontend compatibility)
    - With limit: Returns paginated results with metadata
    
    Args:
        limit: Maximum number of notes to return (optional, no default limit)
        offset: Number of notes to skip (default: 0)
    
    Examples:
        GET /api/notes              -> All notes
        GET /api/notes?limit=20     -> First 20 notes
        GET /api/notes?limit=20&offset=20 -> Notes 21-40
    """
    try:
        notes, folders = scan_notes_fast_walk(config['storage']['notes_dir'], include_media=True)
        
        # Apply pagination with consistent sorting by path for stable results
        result = paginate(
            items=notes,
            limit=limit,
            offset=offset,
            sort_key=lambda x: x.get('path', '').lower()
        )
        
        response = {
            "notes": result.items,
            "folders": folders
        }
        
        # Include pagination metadata only when limit is specified
        if limit is not None:
            response["pagination"] = result.to_dict()
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to list notes"))


@api_router.get("/notes/{note_path:path}", tags=["Notes"])
async def get_note(note_path: str, include_backlinks: bool = True):
    """Get a specific note's content with optional backlinks"""
    try:
        content = get_note_content(config['storage']['notes_dir'], note_path)
        if content is None:
            raise HTTPException(status_code=404, detail="Note not found")

        # Run on_note_load hook (can transform content, e.g., decrypt)
        transformed_content = plugin_manager.run_hook('on_note_load', note_path=note_path, content=content)
        if transformed_content is not None:
            content = transformed_content

        response = {
            "path": note_path,
            "content": content,
            "metadata": create_note_metadata(config['storage']['notes_dir'], note_path)
        }
        
        if include_backlinks:
            response["backlinks"] = get_backlinks(config['storage']['notes_dir'], note_path)
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to load note"))


@api_router.post("/notes/{note_path:path}", tags=["Notes"])
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


@api_router.patch("/notes/{note_path:path}", tags=["Notes"])
@limiter.limit("60/minute")
async def append_to_note(request: Request, note_path: str, data: dict):
    """
    Append content to an existing note without overwriting.
    
    Perfect for journals, logs, or collecting ideas incrementally.
    
    Args:
        note_path: Path to the note
        data: Dictionary with 'content' to append and optional 'add_timestamp' boolean
    """
    try:
        content_to_append = data.get('content', '')
        add_timestamp = data.get('add_timestamp', False)
        
        if not content_to_append:
            raise HTTPException(status_code=400, detail="Content to append is required")
        
        # Get existing content
        existing_content = get_note_content(config['storage']['notes_dir'], note_path)
        
        if existing_content is None:
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Build the appended content
        if add_timestamp:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            content_to_append = f"\n\n---\n\n**{timestamp}**\n\n{content_to_append}"
        else:
            content_to_append = f"\n\n{content_to_append}"
        
        new_content = existing_content + content_to_append
        
        # Run on_note_save hook
        transformed_content = plugin_manager.run_hook('on_note_save', note_path=note_path, content=new_content)
        if transformed_content is None:
            transformed_content = new_content
        
        success = save_note(config['storage']['notes_dir'], note_path, transformed_content)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to append to note")
        
        return {
            "success": True,
            "path": note_path,
            "message": "Content appended successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to append to note"))


@api_router.delete("/notes/{note_path:path}", tags=["Notes"])
@limiter.limit("30/minute")
async def remove_note(request: Request, note_path: str):
    """Delete a note"""
    try:
        success = delete_note(config['storage']['notes_dir'], note_path)
        
        if not success:
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Clean up any share token for this note
        delete_token_for_note(config['storage']['notes_dir'], note_path)
        
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


@api_router.get("/export/{note_path:path}", tags=["Export"])
@limiter.limit("30/minute")
async def export_note_to_html(request: Request, note_path: str, theme: Optional[str] = None, download: bool = True):
    """
    Export a note as a standalone HTML file.

    The HTML includes all necessary CSS, MathJax, Mermaid, and syntax highlighting
    for offline viewing. Images are embedded as base64.

    Query Parameters:
        theme: Optional theme name (defaults to current theme or 'light')
        download: If true (default), returns as file download. If false, displays in browser with print button.

    Returns:
        HTML file (download or inline based on download parameter)
    """
    try:
        notes_dir = Path(config['storage']['notes_dir'])
        
        # Read note content
        content = get_note_content(str(notes_dir), note_path)
        if content is None:
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Run on_note_load hook (can transform content, e.g., decrypt)
        transformed_content = plugin_manager.run_hook('on_note_load', note_path=note_path, content=content)
        if transformed_content is not None:
            content = transformed_content
        
        # Strip YAML frontmatter (like the preview does)
        content = strip_frontmatter(content)
        
        # Get note folder for resolving relative image paths
        note_file_path = notes_dir / note_path
        note_folder = note_file_path.parent
        
        # Embed images as base64
        content_with_images = embed_images_as_base64(content, note_folder, notes_dir)
        
        # Convert wikilinks to decorative HTML links
        content_with_links = convert_wikilinks_to_html(content_with_images)
        
        # Get theme CSS
        themes_dir = Path(__file__).parent.parent / "themes"
        theme_name = theme or 'light'
        theme_css = get_theme_css(str(themes_dir), theme_name)
        if not theme_css:
            theme_css = get_theme_css(str(themes_dir), "light")
            theme_name = "light"
        
        # Strip data-theme selector
        theme_css = theme_css.replace(f':root[data-theme="{theme_name}"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="light"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="dark"]', ':root')
        
        # Determine if dark theme
        is_dark = 'dark' in theme_name.lower() or theme_name in ['dracula', 'nord', 'monokai', 'cobalt2', 'gruvbox-dark']
        
        # Get note title
        title = Path(note_path).stem
        
        # Generate HTML (show print button only when not downloading)
        html_content = generate_export_html(
            title=title,
            content=content_with_links,
            theme_css=theme_css,
            is_dark=is_dark,
            show_print_button=not download
        )
        
        # Return as downloadable file or inline (for print preview)
        if download:
            filename = f"{title}.html"
            return Response(
                content=html_content,
                media_type="text/html",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                }
            )
        else:
            # Return inline for browser display (print preview)
            return HTMLResponse(content=html_content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to export note"))


@api_router.get("/search", tags=["Search"])
async def search(
    q: str,
    limit: Optional[int] = None,
    offset: int = 0
):
    """
    Search notes by content with optional pagination.
    
    Args:
        q: Search query string
        limit: Maximum number of results to return (optional, no default limit)
        offset: Number of results to skip (default: 0)
    
    Examples:
        GET /api/search?q=docker              -> All matching results
        GET /api/search?q=docker&limit=10     -> First 10 results
        GET /api/search?q=docker&limit=10&offset=10 -> Results 11-20
    """
    try:
        if not config['search']['enabled']:
            raise HTTPException(status_code=403, detail="Search is disabled")

        # Handle empty query gracefully
        if not q or not q.strip():
            return {
                "results": [],
                "query": q,
                "message": "No search term provided"
            }

        results = search_notes(config['storage']['notes_dir'], q)

        # Run plugin hooks
        plugin_manager.run_hook('on_search', query=q, results=results)

        # Apply pagination with consistent sorting by path
        paginated = paginate(
            items=results,
            limit=limit,
            offset=offset,
            sort_key=lambda x: x.get('path', '').lower()
        )
        
        response = {
            "results": paginated.items,
            "query": q
        }
        
        # Include pagination metadata only when limit is specified
        if limit is not None:
            response["pagination"] = paginated.to_dict()
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Search failed"))


@api_router.get("/graph", tags=["Graph"])
async def get_graph():
    """Get graph data for note visualization with wikilink and markdown link detection"""
    try:
        import re
        import urllib.parse
        notes, _folders = scan_notes_fast_walk(config['storage']['notes_dir'], include_media=False)
        nodes = []
        edges = []
        
        # Build set of valid note names/paths for matching
        note_paths = set()
        note_paths_lower = {}  # Map lowercase path -> actual path for case-insensitive matching
        note_names = {}  # Map name -> path for quick lookup
        
        for note in notes:
            if note.get('type') == 'note':
                note_paths.add(note['path'])
                note_paths.add(note['path'].replace('.md', ''))
                # Store lowercase path -> actual path mapping for case-insensitive matching
                note_paths_lower[note['path'].lower()] = note['path']
                note_paths_lower[note['path'].replace('.md', '').lower()] = note['path']
                # Store name -> path mapping (without extension)
                name = note['name'].replace('.md', '')
                note_names[name.lower()] = note['path']
                note_names[note['name'].lower()] = note['path']
        
        # Build graph structure with link detection
        for note in notes:
            if note.get('type') == 'note':
                nodes.append({
                    "id": note['path'],
                    "label": note['name'].replace('.md', '')
                })
                
                # Read note content to find links
                content = get_note_content(config['storage']['notes_dir'], note['path'])
                if content:
                    # Find wikilinks: [[target]] or [[target|display]]
                    wikilinks = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)
                    
                    # Find standard markdown internal links: [text](path) - any local path (not http/https)
                    # Match links that don't start with http://, https://, mailto:, #, etc.
                    markdown_links = re.findall(r'\[([^\]]+)\]\((?!https?://|mailto:|#|data:)([^\)]+)\)', content)
                    
                    # Get source note's folder for resolving relative links
                    # Use forward slashes consistently (note_paths uses forward slashes)
                    source_folder = str(Path(note['path']).parent).replace('\\', '/')
                    if source_folder == '.':
                        source_folder = ''
                    
                    # Process wikilinks
                    for target in wikilinks:
                        target = target.strip()
                        target_lower = target.lower()
                        
                        # Try to match target to an existing note
                        target_path = None
                        
                        # 1. Try resolving relative to source note's folder first
                        if source_folder and '/' not in target:
                            relative_path = f"{source_folder}/{target}"
                            relative_path_lower = relative_path.lower()
                            
                            if relative_path in note_paths:
                                target_path = relative_path if relative_path.endswith('.md') else relative_path + '.md'
                            elif relative_path + '.md' in note_paths:
                                target_path = relative_path + '.md'
                            elif relative_path_lower in note_paths_lower:
                                target_path = note_paths_lower[relative_path_lower]
                            elif relative_path_lower + '.md' in note_paths_lower:
                                target_path = note_paths_lower[relative_path_lower + '.md']
                        
                        # 2. Exact path match (absolute or already has folder)
                        if not target_path:
                            if target in note_paths:
                                target_path = target if target.endswith('.md') else target + '.md'
                            elif target + '.md' in note_paths:
                                target_path = target + '.md'
                            # 3. Case-insensitive path match (e.g., [[Folder/Note]] -> folder/note.md)
                            elif target_lower in note_paths_lower:
                                target_path = note_paths_lower[target_lower]
                            elif target_lower + '.md' in note_paths_lower:
                                target_path = note_paths_lower[target_lower + '.md']
                            # 4. Just note name (case-insensitive) - global match
                            elif target_lower in note_names:
                                target_path = note_names[target_lower]
                        
                        if target_path and target_path != note['path']:
                            edges.append({
                                "source": note['path'],
                                "target": target_path,
                                "type": "wikilink"
                            })
                    
                    # Process markdown links
                    for _, link_path in markdown_links:
                        # Skip anchor-only links and external protocols
                        if not link_path or link_path.startswith('#'):
                            continue
                            
                        # Remove anchor part if present (e.g., "note.md#section" -> "note.md")
                        link_path = link_path.split('#')[0]
                        if not link_path:
                            continue
                        
                        # Normalize path: remove ./ prefix, handle URL encoding
                        link_path = urllib.parse.unquote(link_path)
                        if link_path.startswith('./'):
                            link_path = link_path[2:]
                        
                        # Add .md extension if not present and doesn't have other extension
                        link_path_with_md = link_path if link_path.endswith('.md') else link_path + '.md'
                        
                        # Try to match target to an existing note
                        target_path = None
                        
                        # 1. First, try resolving relative to source note's folder
                        if source_folder and not link_path.startswith('/'):
                            relative_path = f"{source_folder}/{link_path}"
                            relative_path_with_md = f"{source_folder}/{link_path_with_md}"
                            relative_path_lower = relative_path.lower()
                            relative_path_with_md_lower = relative_path_with_md.lower()
                            
                            if relative_path in note_paths:
                                target_path = relative_path if relative_path.endswith('.md') else relative_path + '.md'
                            elif relative_path_with_md in note_paths:
                                target_path = relative_path_with_md
                            elif relative_path_lower in note_paths_lower:
                                target_path = note_paths_lower[relative_path_lower]
                            elif relative_path_with_md_lower in note_paths_lower:
                                target_path = note_paths_lower[relative_path_with_md_lower]
                        
                        # 2. Try exact path match from root (for absolute paths or notes at root)
                        if not target_path:
                            link_path_lower = link_path.lower()
                            link_path_with_md_lower = link_path_with_md.lower()
                            
                            if link_path in note_paths:
                                target_path = link_path if link_path.endswith('.md') else link_path + '.md'
                            elif link_path_with_md in note_paths:
                                target_path = link_path_with_md
                            # Case-insensitive path match
                            elif link_path_lower in note_paths_lower:
                                target_path = note_paths_lower[link_path_lower]
                            elif link_path_with_md_lower in note_paths_lower:
                                target_path = note_paths_lower[link_path_with_md_lower]
                        
                        # No global filename fallback for markdown links - they must resolve as paths
                        
                        if target_path and target_path != note['path']:
                            edges.append({
                                "source": note['path'],
                                "target": target_path,
                                "type": "markdown"
                            })
        
        # Remove duplicate edges
        seen = set()
        unique_edges = []
        for edge in edges:
            key = (edge['source'], edge['target'])
            if key not in seen:
                seen.add(key)
                unique_edges.append(edge)
        
        return {"nodes": nodes, "edges": unique_edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to generate graph data"))


@api_router.get("/plugins", tags=["Plugins"])
async def list_plugins():
    """List all available plugins"""
    return {"plugins": plugin_manager.list_plugins()}


@api_router.get("/plugins/note_stats/calculate", tags=["Plugins"])
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


@api_router.post("/plugins/{plugin_name}/toggle", tags=["Plugins"])
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


# ============================================================================
# Stats Endpoint (for dashboards)
# ============================================================================

@api_router.get("/stats", tags=["Stats"])
@limiter.limit("30/minute")
async def get_stats(request: Request):
    """
    Get application statistics at a glance.

    Designed for dashboard widgets (e.g., Homepage) - lightweight and cached.
    Returns counts of notes, folders, tags, templates, media, and other metadata.
    """
    try:
        notes_dir = config['storage']['notes_dir']
        
        # Get notes and folders (cached)
        notes, folders = scan_notes_fast_walk(notes_dir, include_media=True)
        
        # Separate notes from media
        note_items = [n for n in notes if n.get('type') == 'note']
        media_items = [n for n in notes if n.get('type') != 'note']
        
        # Count unique tags
        all_tags = set()
        for note in note_items:
            all_tags.update(note.get('tags', []))
        
        # Get templates count
        templates = get_templates(notes_dir)
        
        # Calculate total size
        total_size = sum(n.get('size', 0) for n in notes)
        
        # Get last modified (notes are already sorted by modified desc)
        last_modified = note_items[0].get('modified') if note_items else None
        
        # Count enabled plugins
        enabled_plugins = sum(1 for p in plugin_manager.plugins.values() if p.enabled)
        
        # Read version
        version = "unknown"
        version_file = Path(__file__).parent.parent / "VERSION"
        if version_file.exists():
            version = version_file.read_text().strip()
        
        return {
            "notes_count": len(note_items),
            "folders_count": len(folders),
            "tags_count": len(all_tags),
            "templates_count": len(templates),
            "media_count": len(media_items),
            "total_size_bytes": total_size,
            "last_modified": last_modified,
            "plugins_enabled": enabled_plugins,
            "version": version
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get stats"))


# ============================================================================
# Share Token Endpoints (authenticated)
# ============================================================================

@api_router.post("/share/{note_path:path}", tags=["Sharing"])
@limiter.limit("30/minute")
async def create_share(request: Request, note_path: str, data: dict = None):
    """
    Create a share token for a note.
    Returns the share URL that can be accessed without authentication.
    Optionally accepts { "theme": "theme-name" } to set the display theme.
    """
    try:
        notes_dir = config['storage']['notes_dir']
        
        # Get theme from request body (default to light)
        theme = "light"
        if data and isinstance(data, dict):
            theme = data.get('theme', 'light')
        
        # Add .md extension if not present
        if not note_path.endswith('.md'):
            note_path = f"{note_path}.md"
        
        # Check if note exists
        content = get_note_content(notes_dir, note_path)
        if content is None:
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Create or get existing token (with theme)
        token = create_share_token(notes_dir, note_path, theme)
        if not token:
            raise HTTPException(status_code=500, detail="Failed to create share token")
        
        # Build share URL
        base_url = str(request.base_url).rstrip('/')
        share_url = f"{base_url}/share/{token}"
        
        return {
            "success": True,
            "token": token,
            "url": share_url,
            "path": note_path,
            "theme": theme
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to create share"))


@api_router.get("/share/{note_path:path}", tags=["Sharing"])
@limiter.limit("120/minute")
async def get_share_status(request: Request, note_path: str):
    """
    Get the share status for a note.
    Returns whether the note is shared and its share URL if so.
    """
    try:
        notes_dir = config['storage']['notes_dir']
        
        # Add .md extension if not present
        if not note_path.endswith('.md'):
            note_path = f"{note_path}.md"
        
        # Get share info
        info = get_share_info(notes_dir, note_path)
        
        if info.get('shared'):
            base_url = str(request.base_url).rstrip('/')
            info['url'] = f"{base_url}/share/{info['token']}"
        
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get share status"))


@api_router.get("/shared-notes", tags=["Sharing"])
@limiter.limit("60/minute")
async def list_shared_notes(request: Request):
    """
    Get a list of all currently shared note paths.
    Used for displaying share indicators in the UI.
    """
    try:
        notes_dir = config['storage']['notes_dir']
        shared_paths = get_all_shared_paths(notes_dir)
        return {"paths": shared_paths}
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get shared notes"))


@api_router.delete("/share/{note_path:path}", tags=["Sharing"])
@limiter.limit("30/minute")
async def delete_share(request: Request, note_path: str):
    """
    Revoke sharing for a note (delete the share token).
    """
    try:
        notes_dir = config['storage']['notes_dir']
        
        # Add .md extension if not present
        if not note_path.endswith('.md'):
            note_path = f"{note_path}.md"
        
        # Revoke token
        success = revoke_share_token(notes_dir, note_path)
        
        return {
            "success": success,
            "message": "Share revoked" if success else "Note was not shared"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to revoke share"))


# ============================================================================
# Public Share Endpoint (no authentication required)
# ============================================================================

@app.get("/share/{token}", response_class=HTMLResponse, tags=["Sharing"])
@limiter.limit("60/minute")
async def view_shared_note(request: Request, token: str):
    """
    View a shared note by its token.
    No authentication required - anyone with the token can view.
    """
    try:
        notes_dir = Path(config['storage']['notes_dir'])
        
        # Look up note by token (returns dict with path and theme)
        share_info = get_note_by_token(str(notes_dir), token)
        if not share_info:
            raise HTTPException(status_code=404, detail="Shared note not found or link expired")
        
        note_path = share_info['path']
        theme = share_info.get('theme', 'light')
        
        # Read note content
        content = get_note_content(str(notes_dir), note_path)
        if content is None:
            # Note was deleted but token still exists - clean up
            delete_token_for_note(str(notes_dir), note_path)
            raise HTTPException(status_code=404, detail="Note no longer exists")
        
        # Strip YAML frontmatter (like the preview does)
        content = strip_frontmatter(content)
        
        # Get note folder for resolving relative image paths
        note_file_path = notes_dir / note_path
        note_folder = note_file_path.parent
        
        # Embed images as base64
        content_with_images = embed_images_as_base64(content, note_folder, notes_dir)
        
        # Convert wikilinks to decorative HTML links
        content_with_links = convert_wikilinks_to_html(content_with_images)
        
        # Use the theme that was set when sharing
        themes_dir = Path(__file__).parent.parent / "themes"
        theme_css = get_theme_css(str(themes_dir), theme)
        if not theme_css:
            theme_css = get_theme_css(str(themes_dir), "light")
            theme = "light"
        
        # Strip data-theme selector
        theme_css = theme_css.replace(f':root[data-theme="{theme}"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="light"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="dark"]', ':root')
        
        # Determine if dark theme
        is_dark = 'dark' in theme.lower() or theme in ['dracula', 'nord', 'monokai', 'cobalt2', 'gruvbox-dark']
        
        # Get note title
        title = Path(note_path).stem
        
        # Generate HTML
        html_content = generate_export_html(
            title=title,
            content=content_with_links,
            theme_css=theme_css,
            is_dark=is_dark
        )
        
        return HTMLResponse(content=html_content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to load shared note"))


@app.get("/health", tags=["System"])
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
@limiter.limit("120/minute")
async def catch_all(full_path: str, request: Request):
    """
    Serve index.html for all non-API routes (including root /).
    This enables client-side routing (e.g., /folder/note)
    """
    # Skip if it's an API route or static file (shouldn't reach here, but just in case)
    if full_path.startswith('api/') or full_path.startswith('static/'):
        raise HTTPException(status_code=404, detail="Not found")
    
    # Serve index.html with app name injected
    index_path = static_path / "index.html"
    async with aiofiles.open(index_path, 'r', encoding='utf-8') as f:
        content = await f.read()
    app_name = config['app']['name']
    return content.replace('<title>NoteDiscovery</title>', f'<title>{app_name}</title>')


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
