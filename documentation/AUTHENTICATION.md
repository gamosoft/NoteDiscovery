# 🔒 NoteDiscovery Authentication Guide

## ⚠️ **IMPORTANT: Default Password Warning**

> **The default `config.yaml` includes authentication disabled by default, with password: `admin`**
>
> 🔴 **CHANGE THIS if you're exposing NoteDiscovery to a network!**
>
> The default configuration is provided for **quick testing only**. Follow the setup guide below to set your own secure password and secret key.

---

## Overview

NoteDiscovery includes a simple, secure authentication system for single-user deployments. When enabled, users must log in with a password before accessing the application.

## ✨ Features

- ✅ **Single User** - Perfect for personal/self-hosted use
- ✅ **Secure** - Passwords hashed with bcrypt
- ✅ **Session-based** - Stay logged in for 7 days (configurable)

---

## 🚀 Quick Setup

**Default Configuration:**
- Authentication is **enabled by default**
- Default password is `admin`
- Default secret key is insecure

**⚠️ IMPORTANT:** For production or network-exposed deployments, **change both the password and secret key immediately**.

---

### 🧪 **Quick Test (Use Default Password)**

For **local testing only**, you can use the default configuration:

1. Start NoteDiscovery (Docker or locally)
2. Navigate to `http://localhost:8000`
3. Log in with password: `admin`

**⚠️ Only use this for local testing on your own machine!**

---

### 🔒 **Production Setup (Change Password & Secret Key)**

For any deployment exposed to a network, follow these steps:

### Step 1: Generate a Password Hash

Choose your environment:

**Docker Users:**

```bash
# Docker Compose
docker-compose exec notediscovery python generate_password.py

# Or with docker run
docker exec -it notediscovery python generate_password.py
```

**Local Users:**

```bash
# Install bcrypt if not already installed
pip install bcrypt

# Run the password generator
python generate_password.py
```

The script will:
1. Prompt you for your password (input is hidden)
2. Ask you to confirm it
3. Generate a bcrypt hash
4. Display the hash with instructions

**Copy the hash** - you'll need it for Step 3.

### Step 2: Generate a Secret Key

Generate a random secret key for session encryption:

**Docker Users:**
```bash
docker-compose exec notediscovery python -c "import secrets; print(secrets.token_hex(32))"

# Or with docker run
docker exec -it notediscovery python -c "import secrets; print(secrets.token_hex(32))"
```

**Local Users:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Copy the key** - you'll need it for Step 3.

### Step 3: Update `config.yaml`

Edit your `config.yaml` and update the authentication section:

```yaml
authentication:
  # Enable authentication
  enabled: true
  
  # Session secret key (paste the output from Step 2)
  secret_key: "your_generated_secret_key_here"
  
  # Password hash (paste the output from Step 1)
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

1. **Use HTTPS** - Always run behind a reverse proxy (Traefik, nginx, Caddy) with SSL/TLS
2. **Strong Password** - Use at least 12 characters with mixed case, numbers, and symbols
3. **Unique Secret Key** - Never reuse secret keys across applications
4. **Keep Config Secure** - Don't commit `config.yaml` with real credentials to version control
5. **VPN/Private Network** - Keep NoteDiscovery on a private network or behind a VPN

---

## 🚫 Disabling Authentication

To disable authentication and allow open access:

```yaml
authentication:
  enabled: false
```

Restart the application, and authentication will be bypassed.