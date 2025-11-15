# 🔌 Plugin System

NoteDiscovery includes a powerful plugin system that lets you extend functionality without modifying core code.

## How Plugins Work

Plugins are Python files that live in the `plugins/` directory. They use **event hooks** to react to actions in the app:

### Available Hooks

| Hook | When Triggered | Parameters | Can Modify |
|------|----------------|------------|------------|
| `on_note_create` | New note is created | `note_path`, `initial_content` | ✅ Yes (return modified content) |
| `on_note_save` | Note is being saved | `note_path`, `content` | ✅ Yes (return transformed content, or None) |
| `on_note_load` | Note is loaded from disk | `note_path`, `content` | ✅ Yes (return transformed content, or None) |
| `on_note_delete` | Note is deleted | `note_path` | ❌ No |
| `on_search` | Search is performed | `query`, `results` | ❌ No |
| `on_app_startup` | App starts up | None | ❌ No |

## Creating a Plugin

### 1. Create a Python file

```bash
cd notediscovery/plugins
touch my_plugin.py
```

### 2. Define your plugin class

Every plugin must have a `Plugin` class with:
- `name` - Display name
- `version` - Version string
- `enabled` - Whether it's active (default: `True`)

### 3. Implement event hooks

Add methods for the events you want to handle.

## Basic Example: Note Logger

This simple plugin logs note activity to Docker logs (visible with `docker-compose logs -f`):

```python
"""
Note Logger Plugin
Logs all note operations to Docker logs for monitoring
"""

class Plugin:
    def __init__(self):
        self.name = "Note Logger"
        self.version = "1.0.0"
        self.enabled = True
    
    def on_note_save(self, note_path: str, content: str) -> str | None:
        """Log when a note is saved"""
        word_count = len(content.split())
        print(f"💾 Note saved: {note_path} ({word_count} words)")
        return None  # Don't modify content, just observe
    
    def on_note_delete(self, note_path: str):
        """Log when a note is deleted"""
        print(f"🗑️  Note deleted: {note_path}")
    
    def on_search(self, query: str, results: list):
        """Log search queries"""
        print(f"🔍 Search: '{query}' → {len(results)} results")
```

### How to see the logs

```bash
# View logs in real-time
docker-compose logs -f

# View logs for specific service
docker-compose logs -f notediscovery
```

## Activating Your Plugin

1. **Place the file** in `plugins/` directory
2. **Restart the app**: `docker-compose restart`
3. **Plugin auto-loads**: Plugins with `enabled = True` will automatically load

### Enable/Disable Plugins via API

Use the API to toggle plugins on/off:

**Linux/Mac:**
```bash
# Enable a plugin
curl -X POST http://localhost:8000/api/plugins/note_logger/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Disable a plugin
curl -X POST http://localhost:8000/api/plugins/note_logger/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

**Windows PowerShell:**
```powershell
# Enable a plugin
curl.exe -X POST http://localhost:8000/api/plugins/note_logger/toggle -H "Content-Type: application/json" -d "{\"enabled\": true}"

# Disable a plugin
curl.exe -X POST http://localhost:8000/api/plugins/note_logger/toggle -H "Content-Type: application/json" -d "{\"enabled\": false}"
```

**List all plugins (all platforms):**
```bash
curl http://localhost:8000/api/plugins
```

## Plugin State Persistence

Plugin states (enabled/disabled) are saved in `plugins/plugin_config.json` and persist between restarts.

---

💡 **Tip:** Use `print()` statements in plugins to log to Docker logs for debugging and monitoring!

