# 🔧 Environment Variables

NoteDiscovery supports environment variables to override configuration settings, allowing different behavior in different deployment environments (local, staging, production).

## 📋 Available Environment Variables

### Core Settings

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PORT` | integer | `8000` | HTTP port for the application (Docker, run.py) |
| `APP_NAME` | string | `NoteDiscovery` | Name shown in the UI, the login page, the browser title and the API docs. Overrides `app.name` in `config.yaml`. |
| `SHARE_PUBLIC_ORIGIN` | string | _(empty)_ | Optional. When set, share links in the dialog / QR / clipboard (and API `url` fields) use this origin instead of the browser or request host. Example: `https://notes.example.com`. Overrides `server.share_public_origin` in `config.yaml`. |
| `FORWARDED_ALLOW_IPS` | string | `127.0.0.1` | Reverse proxy deployments only. Set to `*` so `X-Forwarded-Proto` and `X-Forwarded-For` are trusted and the app sees the real scheme and client IP. Read by uvicorn, not by NoteDiscovery. |

> **Note**: Advanced server settings (CORS origins, debug mode) are configured via `config.yaml` only, not via environment variables. See [config.yaml](#advanced-server-configuration) for details.

#### Example: Public share links while browsing on LAN

```bash
# Docker
docker run -e SHARE_PUBLIC_ORIGIN=https://notes.example.com ...

# Docker Compose
environment:
  - SHARE_PUBLIC_ORIGIN=https://notes.example.com
```

Equivalent in `config.yaml`:

```yaml
server:
  share_public_origin: "https://notes.example.com"
```

Leave unset (or empty) to keep the current behavior: share URLs follow the host you are browsing on.

#### Example: Naming your instance

```bash
# Docker
docker run -e APP_NAME="My Notes" ...

# Docker Compose
environment:
  - APP_NAME=My Notes
```

Equivalent in `config.yaml`:

```yaml
app:
  name: "My Notes"
```

### Storage

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `NOTES_DIR` | string | `./data` | Path to the notes vault |
| `PLUGINS_DIR` | string | `./plugins` | Path to the plugins directory |

The resolved paths are logged at startup so you can confirm what's in use:

```
INFO:     Notes directory: /home/me/MyVault (from NOTES_DIR env var)
INFO:     Plugins directory: ./plugins (from config.yaml)
```

#### Example: Pointing at an existing vault

```bash
# Local
NOTES_DIR=/home/me/MyVault python run.py

# Docker
docker run -e NOTES_DIR=/vault -v /home/me/MyVault:/vault ...
```

### Authentication

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTHENTICATION_ENABLED` | boolean | `config.yaml` | Enable/disable authentication |
| `AUTHENTICATION_PASSWORD` | string | `admin` | Password (hashed automatically at startup) |
| `AUTHENTICATION_SECRET_KEY` | string | `config.yaml` | Session secret key (for session security) |
| `AUTHENTICATION_API_KEY` | string | - | API key for external integrations (MCP, scripts) |

#### Example: Setting password via environment variable

```bash
# Docker
docker run -e AUTHENTICATION_ENABLED=true -e AUTHENTICATION_PASSWORD=mysecretpassword ...

# Docker Compose (in .env file or docker-compose.yml)
AUTHENTICATION_PASSWORD=mysecretpassword
```

### MCP

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MCP_ENABLED` | boolean | `false` | Serve MCP over Streamable HTTP at `/mcp`. Requires `AUTHENTICATION_API_KEY` when authentication is enabled. See [MCP.md](MCP.md#remote-access-streamable-http) |
| `MCP_LOOPBACK_URL` | string | `http://127.0.0.1:<listening port>` | URL the `/mcp` endpoint uses to call back into NoteDiscovery for tool calls. Only needed for unusual setups (e.g. listening on a unix socket) |

### Demo Mode

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEMO_MODE` | boolean | `false` | Enable demo mode (enables rate limiting and other demo restrictions) |

### Support

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ALREADY_DONATED` | boolean | `false` | Hides the support buttons in the Settings pane |

> ⚠️ **Disclaimer:** No verification exists. But legend says that setting this to `true` without donating causes your next `git push` to fail silently. Just once. When it matters most.
>
> Haven't donated yet? [☕ Buy me a coffee](https://ko-fi.com/gamosoft) - it takes 30 seconds and makes my day!

### Upload Limits

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UPLOAD_MAX_IMAGE_MB` | integer | `10` | Maximum image upload size in MB |
| `UPLOAD_MAX_AUDIO_MB` | integer | `50` | Maximum audio upload size in MB |
| `UPLOAD_MAX_VIDEO_MB` | integer | `100` | Maximum video upload size in MB |
| `UPLOAD_MAX_PDF_MB` | integer | `20` | Maximum PDF upload size in MB |
| `UPLOAD_MAX_NOTE_MB` | integer | `10` | Maximum size of `.md` files imported via drag & drop |

#### Example: Allowing larger video uploads

```bash
# Docker
docker run -e UPLOAD_MAX_VIDEO_MB=500 ...

# Docker Compose
environment:
  - UPLOAD_MAX_VIDEO_MB=500
```

### Archive Limits

Applies to folder and whole-vault ZIP downloads (`GET /api/archive`).

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ARCHIVE_MAX_FOLDER_MB` | integer | `500` | Largest folder (or whole vault) that will be zipped, measured on the files going in. Requests over the limit are refused with a `413` before any work starts |

Zipping runs at roughly 100 MB/s and needs that much free temp disk while the archive is built, so raise this only if you are happy to wait for a bigger vault.

### User Interface

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTOSAVE_DELAY_MS` | integer | `1000` | Autosave debounce in milliseconds (applies to note typing and drawing autosave). Server-clamped to 250–60000ms. |
| `DEFAULT_THEME` | string | `light` | Theme served to new browsers that have not saved a preference yet. Use a theme ID from `themes/` (the CSS filename without `.css`). Invalid values are logged and fall back to `light`. |

> **Priority:** A user's previously-selected theme is stored in `localStorage` and always takes precedence over `DEFAULT_THEME`. This setting only affects fresh sessions.

#### Example: Slower autosave for very large notes

```bash
# Docker
docker run -e AUTOSAVE_DELAY_MS=5000 ...

# Docker Compose
environment:
  - AUTOSAVE_DELAY_MS=5000
```

#### Example: Default new browsers to the Dracula theme

```bash
# Docker
docker run -e DEFAULT_THEME=dracula ...

# Docker Compose
environment:
  - DEFAULT_THEME=dracula
```

Equivalent in `config.yaml`:

```yaml
ui:
  autosave_delay_ms: 5000
  default_theme: "dracula"
```

## 🎯 Configuration Priority

Configuration is loaded in this order (later overrides earlier):

1. **`config.yaml`** - Default configuration file
2. **Environment Variables** - Runtime overrides
3. **Command Line** - Highest priority (if applicable)

## 🔧 Advanced Server Configuration

The following settings are available in `config.yaml` only (not via environment variables):

### CORS (Cross-Origin Resource Sharing)

```yaml
server:
  # List of allowed origins for CORS
  # Default: ["*"] allows all origins (fine for self-hosted)
  # Production: specify your domains
  allowed_origins: ["*"]
  
  # Examples for production:
  # allowed_origins: ["http://localhost:8000", "https://yourdomain.com"]
  # allowed_origins: ["https://*.yourdomain.com"]  # Wildcard subdomain
```

**Security Note:**
- `["*"]` is **safe for self-hosted** deployments on private networks
- For **public deployments**, specify exact origins to prevent unauthorized API access
- This prevents CSRF attacks when authentication is enabled

### Debug Mode

```yaml
server:
  # Enable detailed error messages in API responses
  # Default: false (production-safe)
  # Set to true for development/troubleshooting
  debug: false
```

**⚠️ CRITICAL**: Never enable `debug: true` in production!

When `debug: true`:
- Full error stack traces are returned to users
- Internal paths and system details are exposed
- Security vulnerabilities may be revealed

When `debug: false` (recommended):
- Generic error messages are returned
- Full error details are logged server-side only
- Production-safe error handling

---

## 📚 Related Documentation

- **Authentication**: [AUTHENTICATION.md](AUTHENTICATION.md)
- **API Rate Limiting**: [API.md](API.md#rate-limiting)

---

**Pro Tip:** Use environment variables for **deployment-specific** settings, and `config.yaml` for **application defaults**. This keeps your configuration flexible and maintainable! 🎯
