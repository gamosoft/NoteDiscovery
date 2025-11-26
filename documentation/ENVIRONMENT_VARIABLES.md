# 🔧 Environment Variables

NoteDiscovery supports environment variables to override configuration settings, allowing different behavior in different deployment environments (local, staging, production).

## 📋 Available Environment Variables

### Core Settings

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PORT` | integer | `8000` | HTTP port for the application (Docker, run.py) |

> **Note**: Advanced server settings (CORS origins, debug mode) are configured via `config.yaml` only, not via environment variables. See [config.yaml](#advanced-server-configuration) for details.

### Authentication

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTHENTICATION_ENABLED` | boolean | `config.yaml` | Enable/disable authentication |
| `AUTHENTICATION_PASSWORD_HASH` | string | `config.yaml` | Bcrypt password hash |
| `AUTHENTICATION_SECRET_KEY` | string | `config.yaml` | Session secret key (for session security) |

### Demo Mode

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEMO_MODE` | boolean | `false` | Enable demo mode (enables rate limiting and other demo restrictions) |

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

