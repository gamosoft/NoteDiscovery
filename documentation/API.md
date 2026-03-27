# 📡 API Documentation

Base URL: `http://localhost:8000`

## 🗂️ Notes

### List All Notes
```http
GET /api/notes
GET /api/notes?limit=20&offset=0
```
Returns all notes with their metadata and folder structure.

**Optional Pagination:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | - | Max notes to return (omit for all) |
| `offset` | integer | 0 | Number of notes to skip |

When `limit` is provided, the response includes pagination metadata.

**Examples:**
```bash
# Get all notes (default)
curl http://localhost:8000/api/notes

# Get first 20 notes
curl "http://localhost:8000/api/notes?limit=20"

# Get notes 21-40
curl "http://localhost:8000/api/notes?limit=20&offset=20"
```

### Get Note Content
```http
GET /api/notes/{note_path}
```
Retrieve the content of a specific note, including metadata and backlinks.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_backlinks` | boolean | `true` | Include backlinks (notes that link to this note) |

**Example:**
```bash
curl http://localhost:8000/api/notes/folder/mynote.md
```

**Response:**
```json
{
  "path": "folder/mynote.md",
  "content": "# My Note\n\nNote content here...",
  "metadata": {
    "created": "2026-03-15T10:00:00+01:00",
    "modified": "2026-03-17T14:30:00+01:00",
    "size": 1234,
    "lines": 42
  },
  "backlinks": [
    {
      "path": "meetings/standup.md",
      "name": "standup",
      "references": [
        {
          "line_number": 15,
          "context": "...discussed [[mynote]]...",
          "type": "wikilink"
        }
      ]
    }
  ]
}
```

**Backlinks Response Fields:**

| Field | Description |
|-------|-------------|
| `path` | Path of the note that links to this note |
| `name` | Display name of the linking note |
| `references` | Array of link occurrences (max 3 per note) |
| `references[].line_number` | Line number where the link appears |
| `references[].context` | Text snippet around the link |
| `references[].type` | Link type: `wikilink` or `markdown` |

**Without Backlinks:**
```bash
curl "http://localhost:8000/api/notes/folder/mynote.md?include_backlinks=false"
```

### Create/Update Note
```http
POST /api/notes/{note_path}
Content-Type: application/json

{
  "content": "# My Note\nNote content here..."
}
```

**Response:**
```json
{
  "success": true,
  "path": "test.md",
  "message": "Note created successfully",
  "content": "# My Note\nNote content here..."
}
```

**Note:** When creating a new note, the `on_note_create` hook is triggered, allowing plugins to modify the initial content. The response includes the potentially modified content.

**Linux/Mac:**
```bash
curl -X POST http://localhost:8000/api/notes/test.md \
  -H "Content-Type: application/json" \
  -d '{"content": "# Hello World"}'
```

**Windows PowerShell:**
```powershell
curl.exe -X POST http://localhost:8000/api/notes/test.md -H "Content-Type: application/json" -d "{\"content\": \"# Hello World\"}"
```

### Delete Note
```http
DELETE /api/notes/{note_path}
```

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/notes/test.md
```

### Append to Note
```http
PATCH /api/notes/{note_path}
Content-Type: application/json

{
  "content": "Content to append...",
  "add_timestamp": true
}
```

Append content to an existing note without overwriting. Perfect for journals, logs, or collecting ideas incrementally.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | Content to append to the note |
| `add_timestamp` | boolean | No | If `true`, prepends a timestamp header (default: `false`) |

**Response:**
```json
{
  "success": true,
  "path": "daily-journal.md",
  "message": "Content appended successfully"
}
```

**Example with timestamp:**
```bash
curl -X PATCH http://localhost:8000/api/notes/daily-journal.md \
  -H "Content-Type: application/json" \
  -d '{"content": "Had a productive meeting about the roadmap.", "add_timestamp": true}'
```

This will append:
```markdown

---

**2024-03-13 14:30**

Had a productive meeting about the roadmap.
```

**Windows PowerShell:**
```powershell
curl.exe -X PATCH http://localhost:8000/api/notes/daily-journal.md -H "Content-Type: application/json" -d "{\"content\": \"New entry here\", \"add_timestamp\": true}"
```

### Move Note
```http
POST /api/notes/move
Content-Type: application/json

{
  "oldPath": "note.md",
  "newPath": "folder/note.md"
}
```

## 🎬 Media

### Get Media
```http
GET /api/media/{media_path}
```
Retrieve a media file (image, audio, video, PDF) with authentication protection.

**Example:**
```bash
curl http://localhost:8000/api/media/folder/_attachments/image-20240417093343.png
```

**Security Note:** This endpoint requires authentication and validates that:
- The media path is within the notes directory (prevents directory traversal)
- The file exists and is a valid media format
- The requesting user is authenticated (if auth is enabled)

### Upload Media
```http
POST /api/upload-media
Content-Type: multipart/form-data

file: <media file>
note_path: <path of note to attach to>
```

Upload a media file to the `_attachments` directory. Files are automatically organized per-folder and named with timestamps to prevent conflicts.

**Supported formats & size limits:**
| Type | Formats | Max Size |
|------|---------|----------|
| Images | JPG, PNG, GIF, WebP | 10 MB |
| Audio | MP3, WAV, OGG, M4A | 50 MB |
| Video | MP4, WebM, MOV, AVI | 100 MB |
| Documents | PDF | 20 MB |

**Response:**
```json
{
  "success": true,
  "path": "folder/_attachments/media-20240417093343.png",
  "filename": "media-20240417093343.png",
  "message": "Media uploaded successfully"
}
```

**Example (using curl):**
```bash
curl -X POST http://localhost:8000/api/upload-media \
  -F "file=@/path/to/file.mp3" \
  -F "note_path=folder/mynote.md"
```

**Windows PowerShell:**
```powershell
curl.exe -X POST http://localhost:8000/api/upload-media -F "file=@C:\path\to\video.mp4" -F "note_path=folder/mynote.md"
```

### Move Media
```http
POST /api/media/move
Content-Type: application/json

{
  "oldPath": "_attachments/image.png",
  "newPath": "folder/_attachments/image.png"
}
```

Move a media file to a different location. Supports drag & drop in the UI.

**Response:**
```json
{
  "success": true,
  "message": "Media moved successfully",
  "newPath": "folder/_attachments/image.png"
}
```

**Notes:**
- Media is stored in `_attachments` folders relative to the note's location
- Filenames are automatically timestamped (e.g., `media-20240417093343.mp3`)
- Media appears in the sidebar navigation and can be viewed/deleted directly
- Drag & drop files into the editor automatically uploads and inserts markdown
- All media access requires authentication when security is enabled

## 📁 Folders

### Create Folder
```http
POST /api/folders
Content-Type: application/json

{
  "path": "Projects/2025"
}
```

### Delete Folder
```http
DELETE /api/folders/{folder_path}
```
Deletes a folder and all its contents.

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/folders/Projects/Archive
```

### Move Folder
```http
POST /api/folders/move
Content-Type: application/json

{
  "oldPath": "OldFolder",
  "newPath": "NewFolder"
}
```

### Rename Folder
```http
POST /api/folders/rename
Content-Type: application/json

{
  "oldPath": "Projects",
  "newName": "Work"
}
```

## 🔍 Search

### Search Notes
```http
GET /api/search?q={query}
GET /api/search?q={query}&limit=10&offset=0
```

**Optional Pagination:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | - | Max results to return (omit for all) |
| `offset` | integer | 0 | Number of results to skip |

**Examples:**
```bash
# Search all matches
curl "http://localhost:8000/api/search?q=hello"

# Get first 10 results
curl "http://localhost:8000/api/search?q=hello&limit=10"
```

## 🎨 Themes

### List Themes
```http
GET /api/themes
```

### Get Theme CSS
```http
GET /api/themes/{theme_id}
```

**Example:**
```bash
curl http://localhost:8000/api/themes/dark
```

## 🔌 Plugins

Plugins can hook into various events in the application lifecycle.

### Available Plugin Hooks

| Hook | Triggered When | Can Modify Data |
|------|----------------|-----------------|
| `on_note_create` | New note is created | ✅ Yes (return modified content) |
| `on_note_save` | Note is being saved | ✅ Yes (return transformed content, or None) |
| `on_note_load` | Note is loaded | ✅ Yes (return transformed content, or None) |
| `on_note_delete` | Note is deleted | ❌ No |
| `on_search` | Search is performed | ❌ No |
| `on_app_startup` | App starts | ❌ No |

See [PLUGINS.md](PLUGINS.md) for full documentation on creating plugins.

### List Plugins
```http
GET /api/plugins
```

### Toggle Plugin
```http
POST /api/plugins/{plugin_name}/toggle
Content-Type: application/json

{
  "enabled": true
}
```

**Linux/Mac:**
```bash
curl -X POST http://localhost:8000/api/plugins/note_stats/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**Windows PowerShell:**
```powershell
curl.exe -X POST http://localhost:8000/api/plugins/note_stats/toggle -H "Content-Type: application/json" -d "{\"enabled\": true}"
```

### Calculate Note Stats
```http
GET /api/plugins/note_stats/calculate?content={markdown_content}
```

## 🔗 Graph

### Get Note Graph
```http
GET /api/graph
```
Returns the relationship graph between notes with link detection.

**Response:**
```json
{
  "nodes": [
    { "id": "folder/note.md", "label": "note" },
    { "id": "another.md", "label": "another" }
  ],
  "edges": [
    { "source": "folder/note.md", "target": "another.md", "type": "wikilink" }
  ]
}
```

**Link Detection:**
- **Wikilinks** - `[[note]]` or `[[note|display text]]` syntax (Obsidian-style)
- **Markdown links** - `[text](note.md)` standard internal links
- **Edge types** - `"wikilink"` or `"markdown"` to distinguish link source

## ⚙️ System

### Get Config
```http
GET /api/config
```
Returns application configuration.

### Get Stats
```http
GET /api/stats
```
Returns application statistics at a glance. Designed for dashboard widgets (e.g., Homepage) - lightweight and uses cached data.

**Response:**
```json
{
  "notes_count": 142,
  "folders_count": 12,
  "tags_count": 37,
  "templates_count": 5,
  "media_count": 23,
  "total_size_bytes": 2458624,
  "last_modified": "2026-03-17T14:32:00Z",
  "plugins_enabled": 3,
  "version": "0.19.1"
}
```

| Field | Description |
|-------|-------------|
| `notes_count` | Total number of markdown notes |
| `folders_count` | Total number of folders |
| `tags_count` | Number of unique tags across all notes |
| `templates_count` | Number of templates in `_templates` folder |
| `media_count` | Number of media files (images, etc.) |
| `total_size_bytes` | Total size of all files in bytes |
| `last_modified` | ISO timestamp of most recently modified note |
| `plugins_enabled` | Number of enabled plugins |
| `version` | Application version |

**Example ([Homepage](https://gethomepage.dev/) dashboard widget):**
```yaml
- NoteDiscovery:
    href: https://notediscovery.homelab.local
    icon: notediscovery
    container: homelab-notediscovery
    widget:
      type: customapi
      url: http://notediscovery:8000/api/stats
      refreshInterval: 60000
      mappings:
        - field: notes_count
          label: Notes
        - field: tags_count
          label: Tags
        - field: folders_count
          label: Folders
        - field: version
          label: Version
```

### Health Check
```http
GET /health
```
Returns system health status.

### Swagger UI (Interactive Docs)
```http
GET /api
```
Interactive API documentation with try-it-out functionality (Swagger UI).

---

## 🏷️ Tags

### List All Tags
`GET /api/tags`

Returns all tags found in notes with their usage counts.

**Response:**
```json
{
  "tags": {
    "python": 5,
    "tutorial": 3,
    "backend": 2
  }
}
```

### Get Notes by Tag
```http
GET /api/tags/{tag_name}
GET /api/tags/{tag_name}?limit=10&offset=0
```

Returns all notes that have a specific tag.

**Optional Pagination:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | - | Max notes to return (omit for all) |
| `offset` | integer | 0 | Number of notes to skip |

**Response:**
```json
{
  "tag": "python",
  "count": 5,
  "notes": [
    {
      "path": "tutorials/python-basics.md",
      "name": "python-basics",
      "folder": "tutorials",
      "tags": ["python", "tutorial"]
    }
  ]
}
```

---

## 📄 Templates

### List Templates
`GET /api/templates`

Returns all available note templates from the `_templates` folder.

**Response:**
```json
{
  "templates": [
    {
      "name": "meeting-notes",
      "path": "_templates/meeting-notes.md",
      "modified": "2025-11-26T10:30:00"
    },
    {
      "name": "daily-journal",
      "path": "_templates/daily-journal.md",
      "modified": "2025-11-26T10:25:00"
    }
  ]
}
```

### Get Template Content
`GET /api/templates/{template_name}`

Returns the content of a specific template.

**Parameters:**
- `template_name` - Template name (without .md extension)

**Response:**
```json
{
  "name": "meeting-notes",
  "content": "# Meeting Notes\n\nDate: {{date}}\n..."
}
```

### Create Note from Template
`POST /api/templates/create-note`

Creates a new note from a template with placeholder replacement.

**Request Body:**
```json
{
  "templateName": "meeting-notes",
  "notePath": "meetings/weekly-sync.md"
}
```

**Placeholders:**
- `{{date}}` - Current date (YYYY-MM-DD)
- `{{time}}` - Current time (HH:MM:SS)
- `{{datetime}}` - Current datetime
- `{{timestamp}}` - Unix timestamp
- `{{year}}` - Current year (YYYY)
- `{{month}}` - Current month (MM)
- `{{day}}` - Current day (DD)
- `{{title}}` - Note name without extension
- `{{folder}}` - Parent folder name

**Response:**
```json
{
  "success": true,
  "path": "meetings/weekly-sync.md",
  "message": "Note created from template successfully",
  "content": "# Meeting Notes\n\nDate: 2025-11-26\n..."
}
```

---

## 🔗 Sharing

Share notes publicly without requiring authentication.

### Create Share Link
```http
POST /api/share/{note_path}
Content-Type: application/json

{
  "theme": "dracula"
}
```
Creates a share token for the note. The `theme` is optional (defaults to "light").

**Response:**
```json
{
  "success": true,
  "token": "LRFEo86oSVeJ3Gju",
  "url": "http://localhost:8000/share/LRFEo86oSVeJ3Gju",
  "note_path": "folder/note.md"
}
```

### Get Share Status
```http
GET /api/share/{note_path}
```
Check if a note is currently shared.

**Response:**
```json
{
  "shared": true,
  "token": "LRFEo86oSVeJ3Gju",
  "url": "http://localhost:8000/share/LRFEo86oSVeJ3Gju",
  "theme": "dracula",
  "created": "2026-01-15T10:30:00+00:00"
}
```

### Revoke Share
```http
DELETE /api/share/{note_path}
```
Removes public access to the note.

### List Shared Notes
```http
GET /api/shared-notes
```
Returns paths of all currently shared notes.

**Response:**
```json
{
  "paths": ["folder/note.md", "another.md"]
}
```

### View Shared Note (Public)
```http
GET /share/{token}
```
Public endpoint - no authentication required. Returns the note as a standalone HTML page with the theme set when sharing was created.

---

## 📝 Response Format

All endpoints return JSON responses:

**Success:**
```json
{
  "success": true,
  "data": { ... }
}
```

**Error:**
```json
{
  "detail": "Error message"
}
```
---

💡 **Tip:** Visit `/api` for interactive Swagger UI documentation where you can try endpoints directly in your browser!

