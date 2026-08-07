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
| `on_search` | Search is performed | `query`, `results` | ⚠️ In place only ([see below](#advanced-example-open-tasks)) |
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

## Advanced Example: Open Tasks

`plugins/open_tasks.py` (bundled) turns the search box into a task inbox. Search
for **`@task`** (or `@tasks`) and, instead of a normal full-text search, you get
every note that still has an unchecked checkbox:

```markdown
- [ ] Buy milk        ← found
- [x] Bread           ← ignored, already done
```

Each result shows the note plus up to three of its open tasks, and carries an
extra `open_tasks` field with the true count for API and MCP consumers.

**What counts as an open task:** a list item whose box is empty — `- [ ]`,
`* []`, `+ [ ]` or `1. [ ]`. `[x]`/`[X]` are done and never match. Checkboxes
inside fenced code blocks are skipped, as are hidden files and folders.

### The `on_search` trick

`on_search` is listed as non-modifying because **its return value is discarded**
— `PluginManager.run_hook()` only propagates returns for hooks that receive
`content`. But `results` is the *same list object* that `/api/search` paginates
afterwards, so replacing its contents in place does reach the response:

```python
TRIGGERS = {"@task", "@tasks"}

def on_search(self, query: str, results: list):
    if query.strip().lower() not in TRIGGERS:
        return                      # leave every other search alone
    replacement = self._scan(...)   # build the full list first
    results[:] = replacement        # in-place swap — `results.clear()` + extend works too
```

Build the replacement list **before** the swap. If the scan raises halfway
through, `results` is left untouched and the user still gets ordinary search
results (`run_hook` catches and logs the exception).

Two limits worth knowing:

- **You cannot control ordering.** `/api/search` always re-sorts by path after
  the hook runs.
- **The normal search still runs first.** The hook fires after `search_notes()`,
  so its work is discarded when you replace the results.

Because snippets are rendered as HTML in the sidebar, **escape any note content**
you put into a `context` field (`html.escape`), exactly as core search does.

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

