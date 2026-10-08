"""
NoteDiscovery - Self-Hosted Markdown Knowledge Base
Main FastAPI application
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Form, Depends, APIRouter, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from starlette.middleware.sessions import SessionMiddleware
from starlette.background import BackgroundTask
import os
import re
import mimetypes
import tempfile
import time
import yaml
import json
import logging
import zipfile
from pathlib import Path
from typing import List, Optional
from html import escape as html_escape
from urllib.parse import quote_plus, parse_qs, urlparse
import hashlib
import aiofiles
from datetime import datetime
import bcrypt
import secrets
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger("uvicorn.error")

from .utils import (
    scan_notes_fast_walk,
    ensure_index_built,
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
    _scan_cache_invalidate,
    validate_path_security,
    resolve_vault_folder,
    collect_folder_files,
    get_all_tags,
    get_notes_by_tag,
    get_templates,
    get_template_content,
    apply_template_placeholders,
    paginate,
    get_backlinks,
)
from . import note_index
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
    is_slug_available,
    validate_slug,
    ShareSlugError,
)
from .export import generate_export_html, embed_images_as_base64, convert_wikilinks_to_html, strip_frontmatter
from .mcp_http import build_mcp_router

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

# App name: APP_NAME env var > app.name in config.yaml. An empty value is
# treated as unset (matches Docker convention and DEFAULT_THEME below), since a
# blank name would leave the UI and the login page unlabeled.
_app_name_source = "config.yaml"
if os.environ.get('APP_NAME', '').strip():
    config['app']['name'] = os.environ['APP_NAME'].strip()
    _app_name_source = "APP_NAME env var"
logger.info("App name: %s (from %s)", config['app']['name'], _app_name_source)

# Environment variable overrides for authentication settings
# Allows different configs for local vs production deployments
if 'AUTHENTICATION_ENABLED' in os.environ:
    auth_enabled = os.getenv('AUTHENTICATION_ENABLED', 'false').lower() in ('true', '1', 'yes')
    config['authentication']['enabled'] = auth_enabled
    logger.info("Authentication %s (from AUTHENTICATION_ENABLED env var)", 'ENABLED' if auth_enabled else 'DISABLED')
else:
    logger.info("Authentication %s (from config.yaml)", 'ENABLED' if config.get('authentication', {}).get('enabled', False) else 'DISABLED')

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
        logger.info("Password loaded from AUTHENTICATION_PASSWORD env var")
    else:
        logger.warning("AUTHENTICATION_PASSWORD env var is empty - ignoring")
elif config.get('authentication', {}).get('password', '').strip():
    plain_password = config['authentication']['password'].strip()
    config['authentication']['password_hash'] = bcrypt.hashpw(
        plain_password.encode('utf-8'), 
        bcrypt.gensalt()
    ).decode('utf-8')
    del config['authentication']['password']
    logger.info("Password loaded from config.yaml")

# Allow secret key to be set via environment variable (for session security)
if 'AUTHENTICATION_SECRET_KEY' in os.environ:
    config['authentication']['secret_key'] = os.getenv('AUTHENTICATION_SECRET_KEY')
    logger.info("Secret key loaded from AUTHENTICATION_SECRET_KEY env var")

# API key configuration for external integrations (MCP servers, scripts, etc.)
# Priority: AUTHENTICATION_API_KEY env var > authentication.api_key in config.yaml
if 'AUTHENTICATION_API_KEY' in os.environ:
    api_key_value = os.getenv('AUTHENTICATION_API_KEY', '').strip()
    if api_key_value:
        config['authentication']['api_key'] = api_key_value
        logger.info("API key loaded from AUTHENTICATION_API_KEY env var")
    else:
        config['authentication']['api_key'] = ''
elif config.get('authentication', {}).get('api_key', '').strip():
    logger.info("API key loaded from config.yaml")
else:
    config['authentication']['api_key'] = ''

# Warnings for missing authentication methods (only when auth is enabled)
if config.get('authentication', {}).get('enabled', False):
    _has_password = bool(config.get('authentication', {}).get('password_hash', ''))
    _has_api_key = bool(config.get('authentication', {}).get('api_key', '').strip())
    _secret_key = config.get('authentication', {}).get('secret_key', '')
    _is_default_secret = _secret_key in ('', 'change_this_to_a_random_secret_key_in_production')
    
    if not _has_password and not _has_api_key:
        logger.critical("Authentication enabled but NO auth methods configured - ALL access will be denied!")
    else:
        if not _has_password:
            logger.warning("No password configured - web UI login will not work")
        if not _has_api_key:
            logger.warning("No API key configured - external integrations will require session cookies")
    
    if _is_default_secret:
        logger.critical("Using default secret_key - sessions can be forged! Change it in config.yaml")

# MCP over Streamable HTTP at /mcp (opt-in)
# Priority: MCP_ENABLED env var > mcp.enabled in config.yaml
config['mcp'] = config.get('mcp') or {}
if 'MCP_ENABLED' in os.environ:
    config['mcp']['enabled'] = os.getenv('MCP_ENABLED', 'false').lower() in ('true', '1', 'yes')

# Storage paths: env vars override config.yaml. Logged either way so the
# resolved location is visible at startup.
_notes_source = "config.yaml"
if 'NOTES_DIR' in os.environ:
    config['storage']['notes_dir'] = os.getenv('NOTES_DIR')
    _notes_source = "NOTES_DIR env var"
logger.info("Notes directory: %s (from %s)", config['storage']['notes_dir'], _notes_source)

_plugins_source = "config.yaml"
if 'PLUGINS_DIR' in os.environ:
    config['storage']['plugins_dir'] = os.getenv('PLUGINS_DIR')
    _plugins_source = "PLUGINS_DIR env var"
logger.info("Plugins directory: %s (from %s)", config['storage']['plugins_dir'], _plugins_source)

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
# Starlette swaps the wildcard for the requesting Origin once a cookie is present,
# so "*" plus credentials would allow credentialed reads from any origin.
_allow_credentials = "*" not in allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS allowed origins: %s", allowed_origins)

# The vendored libraries are served from here rather than a CDN, so nothing
# compresses them for us. The threshold leaves small responses alone, where the
# gzip header would cost more than it saves.
app.add_middleware(GZipMiddleware, minimum_size=1000)

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
    logger.error(error_details)
    
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

# Upload size limits (in MB) - configurable via environment variables
UPLOAD_MAX_IMAGE_MB = int(os.getenv('UPLOAD_MAX_IMAGE_MB', '10'))
UPLOAD_MAX_AUDIO_MB = int(os.getenv('UPLOAD_MAX_AUDIO_MB', '50'))
UPLOAD_MAX_VIDEO_MB = int(os.getenv('UPLOAD_MAX_VIDEO_MB', '100'))
UPLOAD_MAX_PDF_MB = int(os.getenv('UPLOAD_MAX_PDF_MB', '20'))
UPLOAD_MAX_NOTE_MB = int(os.getenv('UPLOAD_MAX_NOTE_MB', '10'))

# Ceiling on a folder/vault zip archive, measured on the files going in. Checked
# before any zipping starts so an oversized request fails at once instead of
# after spending the CPU. Raise it if your vault is bigger than this and you are
# happy to wait: the work is roughly 100 MB/s, and the archive needs that much
# free temp disk while it is being built.
ARCHIVE_MAX_FOLDER_MB = int(os.getenv('ARCHIVE_MAX_FOLDER_MB', '500'))

# Shortest query the search endpoint will act on. A single character matches
# most of a vault and cannot use the search index, so answering it means reading
# every note for a result nobody wants. Mirrored by SEARCH_MIN_QUERY_LENGTH in
# frontend/app.js, which stops sending those queries in the first place.
SEARCH_MIN_QUERY_LENGTH = 2

# Autosave debounce in milliseconds (applies to note typing AND drawing PNG autosave).
try:
    _autosave_raw = int(os.getenv(
        'AUTOSAVE_DELAY_MS',
        str(config.get('ui', {}).get('autosave_delay_ms', 1000))
    ))
except (TypeError, ValueError):
    _autosave_raw = 1000
AUTOSAVE_DELAY_MS = max(250, min(60000, _autosave_raw))

# Themes directory (single source of truth reused by /api/themes, exports, share view,
# and the default-theme validation below).
THEMES_DIR = Path(__file__).parent.parent / "themes"

# Default UI theme for browsers that do not have a saved preference yet.
# Priority: DEFAULT_THEME env var > ui.default_theme in config.yaml > 'light'.
# Invalid values are logged with their source and coerced back to 'light' so a
# bad config can never lock users out of the UI. Empty-string env var is treated
# as unset (matches Docker convention and how NOTES_DIR/PLUGINS_DIR behave above).
_theme_source = "config.yaml"
if os.environ.get('DEFAULT_THEME'):
    _theme_raw = os.environ['DEFAULT_THEME']
    _theme_source = "DEFAULT_THEME env var"
else:
    _theme_raw = config.get('ui', {}).get('default_theme') or 'light'
DEFAULT_THEME = str(_theme_raw).strip() or 'light'
if not get_theme_css(str(THEMES_DIR), DEFAULT_THEME):
    logger.warning(
        "Configured default theme %r (from %s) was not found in %s; falling back to 'light'",
        DEFAULT_THEME,
        _theme_source,
        THEMES_DIR,
    )
    DEFAULT_THEME = 'light'
else:
    logger.info("Default theme: %s (from %s)", DEFAULT_THEME, _theme_source)

# Optional public origin for share links. When set, create/status share URLs use
# this instead of request.base_url (and the frontend prefers it over
# window.location.origin). Empty = current behavior.
# Priority: SHARE_PUBLIC_ORIGIN env var > server.share_public_origin in config.yaml.
def _normalize_share_public_origin(raw: str) -> str:
    """Return scheme://host[:port] or '' if unset/invalid."""
    value = (raw or '').strip()
    if not value:
        return ''
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    return f"{parsed.scheme}://{parsed.netloc}"

_share_origin_source = "config.yaml"
if os.environ.get('SHARE_PUBLIC_ORIGIN', '').strip():
    _share_origin_raw = os.environ['SHARE_PUBLIC_ORIGIN']
    _share_origin_source = "SHARE_PUBLIC_ORIGIN env var"
else:
    _share_origin_raw = config.get('server', {}).get('share_public_origin') or ''
SHARE_PUBLIC_ORIGIN = _normalize_share_public_origin(_share_origin_raw)
if (_share_origin_raw or '').strip() and not SHARE_PUBLIC_ORIGIN:
    logger.warning(
        "Configured share_public_origin %r (from %s) is not a valid http(s) URL; ignoring",
        _share_origin_raw.strip(),
        _share_origin_source,
    )
elif SHARE_PUBLIC_ORIGIN:
    logger.info("Share public origin: %s (from %s)", SHARE_PUBLIC_ORIGIN, _share_origin_source)

if DEMO_MODE:
    # Enable rate limiting for demo deployments
    limiter = Limiter(key_func=get_remote_address, default_limits=["200/hour"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    logger.info("DEMO MODE enabled - Rate limiting active")
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
plugin_manager = PluginManager(
    config['storage']['plugins_dir'],
    notes_dir=config['storage']['notes_dir'],
    config=config,
)

# Run app startup hooks
plugin_manager.dispatch('on_app_startup')


mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")

# Mount static files
static_path = Path(__file__).parent.parent / "frontend"


class VersionedStaticFiles(StaticFiles):
    """StaticFiles that lets browsers keep version-addressed assets indefinitely.

    Two kinds of URL can never change content for a given address: anything asked
    for with a ?v=<release> query (our own scripts, see _render_app_name_html) and
    the vendored bundler chunks, whose filenames embed a content hash. Caching
    those forever removes a revalidation round trip per file on every page load,
    which for a Mermaid diagram alone is two dozen of them. The HTML that names
    them always revalidates, so an upgraded client still picks up new URLs at once.

    Everything else keeps the default last-modified revalidation.
    """

    IMMUTABLE = "public, max-age=31536000, immutable"

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        content_hashed = scope.get("path", "").startswith("/vendor/mermaid/chunks/")
        if "v" in query or content_hashed:
            response.headers["Cache-Control"] = self.IMMUTABLE
        return response


app.mount("/static", VersionedStaticFiles(directory=static_path), name="static")


def _check_vendored_assets() -> None:
    """Warn if the UI references browser libraries that were never downloaded.

    Reads the expected set out of index.html rather than keeping a second list in
    sync, so adding a library or changing its path cannot silently escape this.
    Only entry points are checked, not every font or lazy-loaded chunk.
    """
    index_file = static_path / "index.html"
    if not index_file.exists():
        return

    try:
        markup = index_file.read_text(encoding="utf-8")
    except OSError:
        return

    referenced = set(re.findall(r'["\']/static/(vendor/[^"\']+)["\']', markup))
    missing = sorted(path for path in referenced if not (static_path / path).exists())
    if not missing:
        logger.info("Vendored browser libraries: %d present", len(referenced))
        return

    logger.warning(
        "%d of %d vendored browser libraries are missing - the web UI will not load",
        len(missing), len(referenced),
    )
    for path in missing[:5]:
        logger.warning("    missing: frontend/%s", path)
    if len(missing) > 5:
        logger.warning("    ... and %d more", len(missing) - 5)
    logger.warning("    Fix with: python scripts/vendor_assets.py")


_check_vendored_assets()


# __APP_VERSION__ lands in a query string in index.html and in the service worker's
# copy of that same URL. Both must resolve to identical text or the worker precaches
# an address the page never asks for, so they share this one encoded value.
version_token = quote_plus(version)


# The app name is admin-controlled configuration rather than user input, but it
# still has to be escaped for the context it lands in: an unescaped quote or
# angle bracket in the name would corrupt the HTML attribute or JSON string
# literal it is substituted into.
def _render_app_name_html(content: str) -> str:
    """Substitute __APP_NAME__ and __APP_VERSION__ placeholders in an HTML document.

    The version turns our own scripts into per-release URLs. Without it an upgraded
    client can pair new HTML with the previous app.js still held by the service
    worker, which breaks the page until a manual reload.
    """
    content = content.replace('__APP_NAME__', html_escape(config['app']['name'], quote=True))
    return content.replace('__APP_VERSION__', version_token)


def _render_app_name_json(content: str) -> str:
    """Substitute __APP_NAME__ placeholders inside JSON string literals."""
    return content.replace('__APP_NAME__', json.dumps(config['app']['name'])[1:-1])


def _html_page_response(content: str, request: Request) -> Response:
    """Serve a rendered page that always revalidates but rarely re-downloads.

    no-cache stops a browser from pairing a cached page with scripts from a
    different release; the ETag, taken from the rendered bytes themselves, turns
    that revalidation into a 304 whenever nothing actually changed.
    """
    etag = '"' + hashlib.sha256(content.encode('utf-8')).hexdigest()[:16] + '"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if_none_match = request.headers.get("if-none-match", "")
    if etag in [tag.strip().removeprefix("W/") for tag in if_none_match.split(",")]:
        return Response(status_code=304, headers=headers)
    return HTMLResponse(content=content, headers=headers)


# PWA manifest - served from root rather than /static because the service worker
# serves /static/ cache-first, which would pin a stale app name.
@app.get("/manifest.json", include_in_schema=False)
# Fetched on every page load alongside /sw.js, so this tracks the catch-all page limit.
@limiter.limit("120/minute")
async def pwa_manifest(request: Request):
    """Serve the PWA manifest with the configured app name injected."""
    manifest_path = static_path / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")
    async with aiofiles.open(manifest_path, 'r', encoding='utf-8') as f:
        content = await f.read()
    return Response(content=_render_app_name_json(content), media_type="application/manifest+json")


# PWA Service Worker - must be served from root for proper scope
@app.get("/sw.js", include_in_schema=False)
# Fetched on every page load alongside /manifest.json.
@limiter.limit("120/minute")
async def service_worker(request: Request):
    """Serve the PWA service worker from root path for proper scope.
    Injects the app version from VERSION file for cache invalidation."""
    sw_path = static_path / "sw.js"
    if sw_path.exists():
        async with aiofiles.open(sw_path, 'r', encoding='utf-8') as f:
            content = await f.read()
        # Same token as index.html: it names the cache and the precached app.js URL
        content = content.replace('__APP_VERSION__', version_token)
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
        # Check if this is an API request (MCP clients need the 401 too)
        if request.url.path.startswith('/api/') or request.url.path == '/mcp':
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
        logger.error("Password verification error: %s", e)
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
    content = _render_app_name_html(content)
    content = content.replace('__DEFAULT_THEME__', DEFAULT_THEME)
    
    return _html_page_response(content, request)


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
async def logout_get_not_allowed():
    """Reject GET so the SPA catch-all cannot serve the app here, and so
    <img src="/logout"> cannot clear the session (use POST instead)."""
    return Response(status_code=405, headers={"Allow": "POST"})


@app.post("/logout", include_in_schema=False)
async def logout(request: Request):
    """Log out the current user.

    POST-only so a third-party page cannot force logout via a GET (e.g. <img src>).
    """
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
        "autosaveDelayMs": AUTOSAVE_DELAY_MS,  # Debounce for note/drawing autosave
        "defaultTheme": DEFAULT_THEME,  # Used when the browser has no saved preference
        "uploadMaxNoteMb": UPLOAD_MAX_NOTE_MB,  # Client-side size cap for .md drops
        # Empty string when unset; frontend falls back to window.location.origin
        "sharePublicOrigin": SHARE_PUBLIC_ORIGIN,
        "authentication": {
            "enabled": config.get('authentication', {}).get('enabled', False)
        }
    }


@api_router.get("/themes", tags=["Themes"])
async def list_themes():
    """Get all available themes"""
    themes = get_available_themes(str(THEMES_DIR))
    return {"themes": themes}


@app.get("/api/themes/{theme_id}", tags=["Themes"]) # Don't use the router here, as we want this route unsecured
async def get_theme(theme_id: str):
    """Get CSS for a specific theme"""
    css = get_theme_css(str(THEMES_DIR), theme_id)
    
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


@api_router.put("/media/{media_path:path}", tags=["Media"])
@limiter.limit("120/minute")
async def put_media(media_path: str, request: Request):
    """
    Overwrite an existing media file in place (used for saving drawing PNGs).
    Only files named drawing-*.png are accepted to avoid accidental overwrites.
    """
    try:
        from backend.utils import ALL_MEDIA_EXTENSIONS

        notes_dir = config['storage']['notes_dir']
        full_path = Path(notes_dir) / media_path

        if not validate_path_security(notes_dir, full_path):
            raise HTTPException(status_code=403, detail="Access denied")

        name_lower = full_path.name.lower()
        if not (name_lower.startswith('drawing-') and name_lower.endswith('.png')):
            raise HTTPException(
                status_code=400,
                detail="Only drawing PNG files (drawing-*.png) can be updated in place",
            )

        if full_path.suffix.lower() not in ALL_MEDIA_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Not an allowed media file")

        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        body = await request.body()
        max_size = UPLOAD_MAX_IMAGE_MB * 1024 * 1024
        if len(body) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {UPLOAD_MAX_IMAGE_MB}MB",
            )

        # Reject non-PNG payloads (defense in depth; path already restricts to .png)
        if len(body) < 8 or body[:8] != b"\x89PNG\r\n\x1a\n":
            raise HTTPException(status_code=400, detail="Body must be a valid PNG image")

        try:
            with open(full_path, 'wb') as f:
                f.write(body)
        except OSError as e:
            raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to save file"))

        return {"success": True, "path": media_path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to update media file"))


@api_router.post("/upload-media", tags=["Media"])
@limiter.limit("20/minute")
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    note_path: str = Form(""),
    content_folder: str = Form(""),
    next_to_notes: str = Form(""),
):
    """
    Upload a media file (image, audio, video, PDF) and save it to the attachments directory,
    or (when next_to_notes=1) save a new drawing PNG next to markdown notes in content_folder.
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
        
        # Size limits (configurable via UPLOAD_MAX_*_MB environment variables)
        size_limits = {
            'image': UPLOAD_MAX_IMAGE_MB * 1024 * 1024,
            'audio': UPLOAD_MAX_AUDIO_MB * 1024 * 1024,
            'video': UPLOAD_MAX_VIDEO_MB * 1024 * 1024,
            'document': UPLOAD_MAX_PDF_MB * 1024 * 1024,
        }
        max_size = size_limits.get(media_type, UPLOAD_MAX_IMAGE_MB * 1024 * 1024)
        
        if len(file_data) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size for {media_type or 'this type'}: {max_size // (1024*1024)}MB. Uploaded: {len(file_data) / 1024 / 1024:.2f}MB"
            )
        
        if (next_to_notes or "").strip() == "1":
            is_png = file.content_type in ("image/png",) or (file.filename and file.filename.lower().endswith(".png"))
            if not is_png:
                raise HTTPException(
                    status_code=400,
                    detail="next_to_notes requires a PNG file",
                )
            file_path = save_uploaded_image(
                config["storage"]["notes_dir"],
                "",
                file.filename or "drawing.png",
                file_data,
                sibling_folder=content_folder or "",
            )
            if not file_path:
                raise HTTPException(status_code=500, detail="Failed to save drawing")
            out_name = Path(file_path).name
            media_type = get_media_type(out_name) or "drawing"
            return {
                "success": True,
                "path": file_path,
                "filename": out_name,
                "type": media_type,
                "message": "Drawing created",
            }
        
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
        _scan_cache_invalidate()

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
        plugin_manager.dispatch('on_note_save', note_path=new_path, content='')
        
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
        final_content = plugin_manager.dispatch(
            'on_note_create',
            note_path=note_path,
            initial_content=final_content
        )
        
        # Run on_note_save hook (can transform content, e.g., encrypt)
        transformed_content = plugin_manager.dispatch('on_note_save', note_path=note_path, content=final_content)
        
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
        content = plugin_manager.dispatch('on_note_load', note_path=note_path, content=content)

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
# This is the autosave endpoint. With autosave_delay_ms at its 1000ms default a single
# editing session can approach one request per second on its own, so the limit has to
# sit well clear of that or active typing starts failing to save.
@limiter.limit("300/minute")
async def create_or_update_note(request: Request, note_path: str, content: dict):
    """Create or update a note"""
    try:
        note_content = content.get('content', '')
        
        # Check if this is a new note (doesn't exist yet)
        existing_content = get_note_content(config['storage']['notes_dir'], note_path)
        is_new_note = existing_content is None
        
        # If creating a new note, run on_note_create hook to allow plugins to modify initial content
        if is_new_note:
            note_content = plugin_manager.dispatch(
                'on_note_create',
                note_path=note_path,
                initial_content=note_content
            )
        
        # Run on_note_save hook (can transform content, e.g., encrypt)
        transformed_content = plugin_manager.dispatch('on_note_save', note_path=note_path, content=note_content)
        
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
        transformed_content = plugin_manager.dispatch('on_note_save', note_path=note_path, content=new_content)
        
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
        plugin_manager.dispatch('on_note_delete', note_path=note_path)
        
        return {
            "success": True,
            "message": "Note deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to delete note"))


# Shared by the archive route and the startup sweep that clears its leftovers.
ARCHIVE_TEMP_PREFIX = 'notediscovery-archive-'

# Already-compressed formats. Deflating these again costs six times the CPU and
# saves nothing: on a 110 MB test vault, storing them instead took the zip from
# 6.7s to 1.1s and grew the archive by 0.1 MB.
STORED_ARCHIVE_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif',
    '.mp3', '.m4a', '.ogg', '.oga', '.opus', '.flac',
    '.mp4', '.webm', '.mov', '.mkv', '.avi',
    '.pdf', '.zip', '.gz', '.bz2', '.xz', '.7z', '.rar',
}


# Kept off the /export/ prefix on purpose: /export/{note_path} uses a path
# converter that swallows everything after it, so any sibling route there is only
# reachable by being declared first and can be broken by reordering.
#
# Deliberately sync rather than async. Zipping blocks, so on the event loop it
# would freeze every other request for the duration; as a plain def, FastAPI runs
# it in a worker thread and the app stays responsive while it works.
@api_router.get("/archive", tags=["Export"])
@limiter.limit("10/minute")
def download_folder_archive(request: Request, folder: str = ""):
    """
    Download a folder and everything under it as a zip file.

    The vault on disk is the source of truth: notes, their `_attachments` and any
    other files come out exactly as they are stored, so the archive can be
    unzipped into another vault or read in any editor. Note content is not
    parsed, which means media a note links to from a *different* folder is not
    pulled in — exporting a folder gives you that folder.

    Symlinks, dot-files and dot-directories are skipped. Disabled in demo mode.

    Query Parameters:
        folder: Folder to archive, relative to the vault root. Omit it (or pass an
                empty value) to archive the whole vault.

    Returns:
        A zip file, with paths inside it relative to the requested folder.
    """
    # Notes can be written in demo mode, so without this anyone could upload
    # attachments and then ask for a zip of the whole vault ten times a minute, on
    # the demo's bandwidth. Nothing about trying the app out needs its content
    # downloaded. This also puts the rate limit above out of reach, since limits
    # only apply in demo mode; it stays for the day this guard is lifted.
    if DEMO_MODE:
        raise HTTPException(status_code=403, detail="Archiving is disabled in demo mode")

    notes_dir = config['storage']['notes_dir']
    folder_path = (folder or '').strip().strip('/')

    folder_dir = resolve_vault_folder(notes_dir, folder_path)
    if folder_dir is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    files, total_bytes = collect_folder_files(notes_dir, folder_dir)
    if not files:
        raise HTTPException(status_code=404, detail="Folder has no files to archive")

    if total_bytes > ARCHIVE_MAX_FOLDER_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Folder is {total_bytes / (1024 * 1024):.0f} MB, which is over the "
                f"{ARCHIVE_MAX_FOLDER_MB} MB limit. Archive a subfolder instead, "
                f"or raise ARCHIVE_MAX_FOLDER_MB."
            ),
        )

    # Built on disk, not in memory: a vault-sized archive has no business in RAM,
    # and a real file lets FileResponse send a Content-Length so browsers can show
    # download progress.
    handle = tempfile.NamedTemporaryFile(prefix=ARCHIVE_TEMP_PREFIX, suffix='.zip', delete=False)
    handle.close()
    archive_path = Path(handle.name)

    try:
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file_path, arcname in files:
                try:
                    archive.write(file_path, arcname, compress_type=(
                        zipfile.ZIP_STORED if file_path.suffix.lower() in STORED_ARCHIVE_EXTENSIONS
                        else zipfile.ZIP_DEFLATED
                    ))
                except OSError:
                    # The response only carries a generic message, so name the file
                    # here: one unreadable file fails the whole archive and the owner
                    # needs to know which one to fix.
                    logger.error("Folder archive aborted, cannot read %s", file_path)
                    raise
    except Exception as e:
        archive_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to archive folder"))

    logger.info(
        "Folder archive: %s | %d files | %.1f MB in | %.1f MB out",
        folder_path or '(vault root)', len(files),
        total_bytes / (1024 * 1024), archive_path.stat().st_size / (1024 * 1024),
    )

    # The vault root has no folder name to borrow, so it takes the app's. Also
    # catches ".", which Path reduces to no name at all.
    label = Path(folder_path).name or config['app']['name']
    return FileResponse(
        archive_path,
        media_type='application/zip',
        filename=f'{label}.zip',
        # Declaring an encoding is how Starlette's GZipMiddleware is told to leave a
        # response alone. Without it every download is gzipped again, which on a zip
        # costs CPU to make the payload slightly larger, and drops the Content-Length
        # the browser needs to show download progress.
        headers={'Content-Encoding': 'identity'},
        # Deleted once the response has been sent, however that turns out.
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


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
        content = plugin_manager.dispatch('on_note_load', note_path=note_path, content=content)
        
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
        theme_name = theme or 'light'
        theme_css = get_theme_css(str(THEMES_DIR), theme_name)
        if not theme_css:
            theme_css = get_theme_css(str(THEMES_DIR), "light")
            theme_name = "light"
        
        # Strip data-theme selector
        theme_css = theme_css.replace(f':root[data-theme="{theme_name}"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="light"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="dark"]', ':root')
        
        # Determine if dark theme
        is_dark = 'dark' in theme_name.lower() or theme_name in ['dracula', 'nord', 'monokai', 'cobalt2', 'gruvbox-dark']
        
        # Get note title
        title = Path(note_path).stem
        
        # A download has to render anywhere, so it keeps the CDN URLs; the print
        # preview is served by us and can use the vendored copies.
        html_content = generate_export_html(
            title=title,
            content=content_with_links,
            theme_css=theme_css,
            is_dark=is_dark,
            show_print_button=not download,
            local_assets=not download
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

        # Below the floor, skip the vault read but still run the hooks, so a
        # plugin answering a short trigger of its own keeps working.
        if len(q.strip()) < SEARCH_MIN_QUERY_LENGTH:
            results = []
        else:
            results = search_notes(config['storage']['notes_dir'], q)

        # Run plugin hooks — a plugin may return a replacement result set
        hooked = plugin_manager.dispatch('on_search', query=q, results=results)
        plugin_replaced = hooked is not results
        results = hooked

        # Core results are sorted by path so pagination is reproducible between
        # requests (search_notes emits them in mtime order, which shifts as notes
        # are edited). A plugin that returns its own list has chosen an order —
        # relevance, due date — so keep it, and with it the responsibility for
        # making that order stable across calls.
        paginated = paginate(
            items=results,
            limit=limit,
            offset=offset,
            sort_key=None if plugin_replaced else (lambda x: x.get('path', '').lower())
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
    """Graph data (nodes + resolved wikilink/markdown edges) for the visualizer."""
    try:
        if not note_index.get_index().is_built():
            scan_notes_fast_walk(config['storage']['notes_dir'], include_media=False)
        nodes_paths, edges_tuples = note_index.get_graph_data()
        return {
            "nodes": [{"id": p, "label": Path(p).stem} for p in nodes_paths],
            "edges": [{"source": s, "target": t, "type": et} for (s, t, et) in edges_tuples],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to generate graph data"))


@api_router.get("/plugins", tags=["Plugins"])
async def list_plugins():
    """List all available plugins"""
    return {"plugins": plugin_manager.list_plugins()}


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
# Index observability — internal counters & sizes for debugging
#
# Useful for confirming the index is doing what we expect (build_count >0,
# search_terms not empty, fingerprint_short_circuits incrementing on idle
# warm scans). Not rate-limited — cheap, no I/O, dict lookups only.
# ============================================================================

@api_router.get("/index/stats", tags=["System"])
async def get_index_stats():
    return note_index.stats()


# ============================================================================
# Stats Endpoint (for dashboards)
# ============================================================================

@api_router.get("/stats", tags=["Stats"])
@limiter.limit("30/minute")
async def get_stats(request: Request):
    """At-a-glance counts for dashboard widgets (Homepage etc.).

    All vault aggregates are read from the in-memory index — no file walk on
    the request path. Templates / plugins / version are looked up directly."""
    try:
        notes_dir = config['storage']['notes_dir']
        ensure_index_built(notes_dir)
        s = note_index.summary()

        templates_count = len(get_templates(notes_dir))
        enabled_plugins = sum(1 for p in plugin_manager.plugins.values() if p.enabled)

        version = "unknown"
        version_file = Path(__file__).parent.parent / "VERSION"
        if version_file.exists():
            version = version_file.read_text().strip()

        return {
            "notes_count": s["notes_count"],
            "folders_count": s["folders_count"],
            "tags_count": s["tags_count"],
            "templates_count": templates_count,
            "media_count": s["media_count"],
            "total_size_bytes": s["total_size_bytes"],
            "last_modified": s["last_modified"],
            "plugins_enabled": enabled_plugins,
            "version": version,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get stats"))


# ============================================================================
# Share Token Endpoints (authenticated)
# ============================================================================

def _share_base_url(request: Request) -> str:
    """Origin used when building share links for the API response.

    Prefer SHARE_PUBLIC_ORIGIN when configured so API consumers (and the UI
    before _localizeShareUrl runs) see the public host. Otherwise use the
    request's base URL as before.
    """
    if SHARE_PUBLIC_ORIGIN:
        return SHARE_PUBLIC_ORIGIN
    return str(request.base_url).rstrip('/')


@api_router.post("/share/{note_path:path}", tags=["Sharing"])
@limiter.limit("30/minute")
async def create_share(request: Request, note_path: str, data: dict = None):
    """
    Create a share token for a note.
    Returns the share URL that can be accessed without authentication.
    Optionally accepts { "theme": "theme-name" } to set the display theme, and
    { "slug": "custom-name" } to choose the token instead of generating one. On a
    note that is already shared, a different slug renames the link and the previous
    URL stops working.
    """
    try:
        notes_dir = config['storage']['notes_dir']
        
        # Get theme from request body (default to light)
        theme = "light"
        slug = None
        if data and isinstance(data, dict):
            theme = data.get('theme', 'light')
            # Absent and blank both mean "generate one", so the UI can send the field
            # unconditionally.
            if data.get('slug') not in (None, ''):
                slug = data.get('slug')
        
        # Add .md extension if not present
        if not note_path.endswith('.md'):
            note_path = f"{note_path}.md"
        
        # Check if note exists
        content = get_note_content(notes_dir, note_path)
        if content is None:
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Create or get existing token (with theme)
        try:
            token = create_share_token(notes_dir, note_path, theme, slug)
        except ShareSlugError as e:
            # 409 for a name someone else holds, 400 for a name that could never work.
            raise HTTPException(
                status_code=409 if e.reason == 'taken' else 400,
                detail={"reason": e.reason, "message": f"Share slug rejected: {e.reason}"},
            )
        if not token:
            raise HTTPException(status_code=500, detail="Failed to create share token")
        
        # Build share URL
        share_url = f"{_share_base_url(request)}/share/{token}"
        
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
            info['url'] = f"{_share_base_url(request)}/share/{info['token']}"
        
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_message(e, "Failed to get share status"))


@api_router.get("/share-slug", tags=["Sharing"])
@limiter.limit("120/minute")
async def check_share_slug(request: Request, slug: str, note_path: str = ""):
    """
    Report whether a custom share slug is usable, so the share dialog can say so
    before the user commits to it. Advisory: the POST validates again, since another
    request can claim the same name in between.

    The limit is generous because the UI calls this while the user types.
    """
    try:
        candidate = validate_slug(slug)
    except ShareSlugError as e:
        return {"available": False, "reason": e.reason}

    # A note's own current token is not a conflict, so editing a link and saving it
    # unchanged is not reported as taken.
    owner_path = note_path or None
    if owner_path and not owner_path.endswith('.md'):
        owner_path = f"{owner_path}.md"

    notes_dir = config['storage']['notes_dir']
    if not is_slug_available(notes_dir, candidate, owner_path):
        return {"available": False, "reason": "taken"}
    return {"available": True, "reason": None}


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
        theme_css = get_theme_css(str(THEMES_DIR), theme)
        if not theme_css:
            theme_css = get_theme_css(str(THEMES_DIR), "light")
            theme = "light"
        
        # Strip data-theme selector
        theme_css = theme_css.replace(f':root[data-theme="{theme}"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="light"]', ':root')
        theme_css = theme_css.replace(':root[data-theme="dark"]', ':root')
        
        # Determine if dark theme
        is_dark = 'dark' in theme.lower() or theme in ['dracula', 'nord', 'monokai', 'cobalt2', 'gruvbox-dark']
        
        # Get note title
        title = Path(note_path).stem
        
        # Served by this instance, so the vendored libraries are reachable
        html_content = generate_export_html(
            title=title,
            content=content_with_links,
            theme_css=theme_css,
            is_dark=is_dark,
            local_assets=True
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
    return _html_page_response(_render_app_name_html(content), request)


# ============================================================================
# Register Routers
# ============================================================================

# Register routers with the main app
# Authentication is applied via router dependencies
# Plugin routes go on api_router so they inherit the same auth dependency;
# mounted last so a plugin cannot shadow a core endpoint.
api_router.include_router(plugin_manager.build_router())
app.include_router(api_router)

# Mounted before pages_router so its catch-all GET doesn't shadow /mcp.
# The tool client calls back in with the API key, so auth needs one.
if config['mcp'].get('enabled', False):
    if auth_enabled() and not get_api_key():
        logger.warning("MCP endpoint NOT enabled: authentication is on but no API key is configured")
    else:
        app.include_router(build_mcp_router(get_api_key, require_auth, allowed_origins))
        logger.info("MCP Streamable HTTP endpoint enabled at /mcp")

app.include_router(pages_router)


# ============================================================================
# Startup warmup
# ============================================================================
# Pre-build the note index off the request path. Mid-warmup requests are safe
# (bulk_set is serialized and short-circuits on the fingerprint).
# Success is logged from inside bulk_set so we get a single line for both
# the initial build and any subsequent rebuilds triggered by external changes.
@app.on_event("startup")
def _sweep_stale_archives() -> None:
    """Delete archives left behind by downloads that never finished.

    The temp file is removed by a background task once the response has been sent,
    but Starlette runs that after the body loop rather than in a finally, so a
    client that cancels mid-download leaves the archive on disk. Anything older
    than an hour cannot belong to a live request.
    """
    cutoff = time.time() - 3600
    for stale in Path(tempfile.gettempdir()).glob(f'{ARCHIVE_TEMP_PREFIX}*.zip'):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
                logger.info("Removed stale archive %s", stale.name)
        except OSError:
            pass  # Being tidy is not worth failing startup over.


@app.on_event("startup")
def _warmup_note_index() -> None:
    import threading

    def _build() -> None:
        try:
            ensure_index_built(config['storage']['notes_dir'])
        except Exception as exc:
            logger.warning("Vault index rebuild failed (will retry on first request): %s", exc)

    threading.Thread(target=_build, name="note-index-warmup", daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=config['server']['host'],
        port=config['server']['port'],
        reload=config['server']['reload']
    )
