# 🔒 NoteDiscovery Authentication Guide

## Overview

NoteDiscovery includes a simple, secure authentication system for single-user deployments. When enabled, users must log in with a password before accessing the application.

## ✨ Features

- ✅ **Single User** - Perfect for personal/self-hosted use
- ✅ **Secure** - Passwords hashed with bcrypt
- ✅ **Session-based** - Stay logged in for 7 days (configurable)
- ✅ **Theme-aware** - Login page matches your selected theme
- ✅ **Simple Setup** - Just 3 steps to enable

---

## 🚀 Quick Setup

**⚠️ IMPORTANT:** Authentication is **disabled by default**. Follow these steps to enable it:

### Step 1: Generate a Password Hash

Choose one of these methods:

**Option A: Using Docker (Recommended - No local Python needed)**

If you're running NoteDiscovery in Docker:

```bash
# Docker Compose
docker-compose exec notediscovery /app/generate_password_hash.sh

# Or with docker run
docker exec -it notediscovery /app/generate_password_hash.sh
```

The script will prompt you for your password and output the hash.

**Option B: Using Local Python**

If you're running NoteDiscovery locally:

```bash
# Install bcrypt if not already installed
pip install bcrypt

# Run the password generator
python generate_password.py
```

Enter your desired password when prompted. The script will output a bcrypt hash.

**Copy the hash** - you'll need it for the next step.

### Step 2: Generate a Secret Key

Generate a random secret key for session encryption:

**Using Docker:**
```bash
docker-compose exec notediscovery python -c "import secrets; print(secrets.token_hex(32))"

# Or with docker run
docker exec -it notediscovery python -c "import secrets; print(secrets.token_hex(32))"
```

**Using Local Python:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Copy the key** - you'll need it for the next step.

### Step 3: Update `config.yaml`

Edit your `config.yaml` and update the security section:

```yaml
security:
  # Enable authentication
  enabled: true
  
  # Session secret key (paste the output from Step 3)
  secret_key: "your_generated_secret_key_here"
  
  # Password hash (paste the output from Step 2)
  password_hash: "$2b$12$..."
  
  # Session expiry in seconds (7 days by default)
  session_max_age: 604800
```

### Step 4: Restart the Application

```bash
# If running locally
uvicorn backend.main:app --reload

# If using Docker Compose
docker-compose restart

# Or with docker run
docker restart notediscovery
```

### Step 5: Test Login

Navigate to `http://localhost:8000` and you'll be redirected to the login page.

Enter the password you chose in Step 2.

---

## 🔐 Usage

### Logging In

1. Navigate to `http://localhost:8000`
2. You'll be **automatically redirected** to the login page if not authenticated
3. Enter your password (the one you generated in setup)
4. Click "🔓 Unlock"
5. You'll be redirected back to the main app

**Note:** The login page **automatically inherits the theme** you selected in the main app. It uses the same theme loading system as the main app (fetches CSS from `/api/themes` and stores preference in localStorage as `noteDiscoveryTheme`).

**What happens if I'm not logged in?**
- 🌐 **Page requests** (like `/`, `/MATHJAX`, etc.) → **Automatically redirected to login page**
- 🔌 **API requests** (like `/api/notes`) → **Return JSON error** `{"detail": "Not authenticated"}`

This smart routing ensures:
- ✅ Users always see the login page (never a JSON error)
- ✅ API calls get proper JSON errors (for programmatic access)
- ✅ No broken page loads or error messages

### Logging Out

**Option 1: Use the built-in logout button**

A logout button (🔒 Logout) automatically appears in the sidebar header when authentication is enabled. Simply click it to log out.

**Option 2: Navigate directly**

Visit `http://localhost:8000/logout` in your browser.

### Changing Password

1. Generate a new password hash:
   - **Docker**: `docker-compose exec notediscovery /app/generate_password_hash.sh`
   - **Local**: `python generate_password.py`
2. Update `password_hash` in `config.yaml` with the new hash
3. Restart the application:
   - **Docker**: `docker-compose restart`
   - **Local**: Restart uvicorn
4. All existing sessions will remain valid until they expire

### Session Expiry

- **Default**: 7 days (604800 seconds)
- **Custom**: Change `session_max_age` in `config.yaml`
- Sessions are cleared when you log out

---

## 🔒 Security Considerations

### ✅ What This Protects

- Unauthorized access to your notes
- Viewing, creating, editing, and deleting notes
- All API endpoints

### ⚠️ What This Doesn't Protect

This is a **simple authentication system** designed for **self-hosted, single-user** deployments. It is **NOT** suitable for:

- ❌ Multi-user environments
- ❌ Public internet exposure without HTTPS
- ❌ Production SaaS applications
- ❌ Compliance requirements (HIPAA, GDPR, etc.)

### 🛡️ Best Practices

1. **Use HTTPS** - Always run behind a reverse proxy (nginx, Caddy) with SSL/TLS
2. **Strong Password** - Use at least 12 characters with mixed case, numbers, and symbols
3. **Unique Secret Key** - Never reuse secret keys across applications
4. **Keep Config Secure** - Don't commit `config.yaml` with real credentials to version control
5. **VPN/Private Network** - Keep NoteDiscovery on a private network or behind a VPN

---

## 🚫 Disabling Authentication

To disable authentication and allow open access:

```yaml
security:
  enabled: false
```

Restart the application, and authentication will be bypassed.

---

## 🐛 Troubleshooting

### "Invalid Password" Error

- **Check password hash**: Ensure the hash in `config.yaml` matches your password
- **Regenerate hash**: Run `python generate_password.py` again
- **Check encoding**: Password must be UTF-8 encoded

### "Not authenticated" Error

- **Check session**: Your session may have expired (default: 7 days)
- **Clear cookies**: Clear your browser cookies and log in again
- **Check config**: Ensure `enabled: true` in `config.yaml`

### Login Page Not Showing

- **Check config**: Verify `enabled: true` in `config.yaml`
- **Check routes**: Visit `/login` directly
- **Check logs**: Look for errors in the console

### Can't Access `/logout`

- You must be logged in to access `/logout`
- Clear your browser cookies manually if needed

---

## 🎨 Customizing Login Page

The login page (`frontend/login.html`) can be customized:

- **Theme**: Automatically inherits the theme you selected in the main app (from localStorage)
- **Logo**: Uses `/static/logo.svg`
- **Styling**: Edit the CSS in the `<style>` section
- **Content**: Modify the HTML directly
- **Error Messages**: Displayed inline in red when login fails (no separate error page)

**Note:** The theme selector is intentionally hidden on the login page to keep it clean. Users will see the theme they selected in the main app.

---

## 📦 Docker Deployment

When using Docker, mount your `config.yaml` with credentials:

```yaml
services:
  notediscovery:
    image: ghcr.io/yourusername/notediscovery:latest
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./data:/app/data
    ports:
      - "8000:8000"
```

**Security Note**: Don't build credentials into the Docker image. Always mount them as a volume.

---

## 🤝 Multi-User Support

This authentication system is designed for **single-user** deployments. If you need multi-user support:

1. Run separate instances (one per user)
2. Use Docker containers with different ports
3. Use a reverse proxy for routing

For enterprise/multi-user needs, consider:
- OAuth 2.0 / OpenID Connect
- Database-backed user management
- Role-based access control (RBAC)

---

## 📝 Technical Details

### Password Hashing

- **Algorithm**: bcrypt
- **Rounds**: 12 (default)
- **Salt**: Automatically generated per password

### Session Management

- **Storage**: Server-side session cookies
- **Signing**: HMAC with secret key
- **Security**: HttpOnly, SameSite=Lax
- **Expiry**: Configurable (default 7 days)

### Dependencies

- `bcrypt` - Password hashing
- `itsdangerous` - Session signing
- `starlette` - Session middleware

---

## 📚 Additional Resources

- [bcrypt Documentation](https://github.com/pyca/bcrypt/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [OWASP Authentication Cheatsheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)

---

**Need Help?** Open an issue on [GitHub](https://github.com/yourusername/notediscovery/issues) or consult the [README.md](README.md).

