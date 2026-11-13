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

**Optional Folder Filter:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `folder` | string | - | Only return notes under this folder |
| `recursive` | boolean | true | With `folder`, also include subfolders |

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
  "hash": "9f2c…e41a",
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

`hash` is the SHA-256 of the note as stored on disk (before any `on_note_load` plugin transforms it). Send it back as `base_hash` when saving to detect changes made in the meantime.

**Without Backlinks:**
```bash
curl "http://localhost:8000/api/notes/folder/mynote.md?include_backlinks=false"
```

### Create/Update Note
```http
POST /api/notes/{note_path}
Content-Type: application/json

{
  "content": "# My Note\nNote content here...",
  "base_hash": "9f2c…e41a"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `content` | yes | Full note content |
| `base_hash` | no | `hash` of the version this content was based on. If the file on disk no longer matches it, the note is not saved and `409` is returned. Omit it to always overwrite (previous behavior). |

**Response:**
```json
{
  "success": true,
  "path": "test.md",
  "message": "Note created successfully",
  "content": "# My Note\nNote content here...",
  "hash": "51b0…7c3d"
}
```

**Note:** When creating a new note, the `on_note_create` hook is triggered, allowing plugins to modify the initial content. The response includes the potentially modified content.

**Conflict (409):** the note changed on disk since `base_hash` was read (another tab, a sync tool, an AI agent). Nothing is written. The response carries the current hash: `GET` the note to reload it, or send the same content again with that hash to overwrite.
```json
{
  "detail": "Note changed on disk since it was loaded",
  "hash": "c07d…92b8"
}
```

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

### Replace Text in Note
```http
POST /api/notes/replace
Content-Type: application/json

{
  "path": "projects/alpha.md",
  "old_str": "Deadline: March",
  "new_str": "Deadline: April"
}
```

Replace one exact occurrence of a text in an existing note, without sending the whole note. `old_str` is matched against the content `GET /api/notes/{note_path}` returns. Nothing is written unless it appears exactly once.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the existing note |
| `old_str` | string | Yes | Exact text to replace. Must appear exactly once |
| `new_str` | string | Yes | Replacement text. An empty string deletes `old_str` |

**Errors:**
| Status | When |
|--------|------|
| `400` | `path` or `old_str` is empty, or `new_str` is missing |
| `404` | The note does not exist |
| `409` | `old_str` is not found, or is found more than once |

**Response:**
```json
{
  "success": true,
  "path": "projects/alpha.md",
  "message": "Note updated successfully",
  "hash": "<sha256 of the saved content>"
}
```

### Move Note
```http
POST /api/notes/move
Content-Type: application/json

{
  "oldPath": "note.md",
  "newPath": "folder/note.md",
  "reportBrokenLinks": true
}
```

`reportBrokenLinks` is optional and defaults to `false`. When `true`, the response adds `brokenLinksIn`: the notes with links to the old path that no longer work. Other notes do not change.

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

### Update drawing (PNG in place)

```http
PUT /api/media/{media_path}
Content-Type: image/png
```

Overwrites an **existing** file in the vault. The server only accepts targets whose filename matches **`drawing-*.png`** (lowercase `.png`). The body must be a valid **PNG** (magic bytes are checked). Used by the in-app drawing editor when saving.

**Requirements:**
- File must already exist (create new drawings via **New drawing** / `POST /api/upload-media` with `next_to_notes`, not via PUT).
- Path must stay within the notes directory (same rules as GET).

**Response:**
```json
{ "success": true, "path": "folder/drawing-20260101120000.png" }
```

**Example:**
```bash
curl -X PUT http://localhost:8000/api/media/myproject/drawing-20260101120000.png \
  -H "Content-Type: image/png" \
  --data-binary @sketch.png
```

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

**Query Parameters:**
- `require_empty` (optional): when `true`, returns `409` and deletes nothing if the folder is not empty. Defaults to `false`.

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
  "newPath": "NewFolder",
  "reportBrokenLinks": true
}
```

`reportBrokenLinks` works as in [Move Note](#-notes). It also checks the links inside the moved folder.

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

Matches note contents by case- and accent-insensitive substring, so `q=feat`
returns notes containing "Features" and `q=esparragos` returns notes containing
"Espárragos". Snippets keep the text as written. Each result carries the lines
that matched. A query of fewer than 2 characters returns no results: it would
match most of a vault and cannot use the search index.

**Optional Pagination:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | - | Max results to return (omit for all) |
| `offset` | integer | 0 | Number of results to skip |

**Optional Folder Filter:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `folder` | string | - | Only return results under this folder |
| `recursive` | boolean | true | With `folder`, also include subfolders |

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
| `on_search` | Search is performed | ✅ Yes (return a replacement result list, or None) |
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
GET /api/graph?include_system_folders=false
```
Returns the relationship graph between notes with link detection.

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `include_system_folders` | `true` | When `false`, notes stored under a folder whose name starts with `_` are omitted, along with every edge that starts or ends on one of those notes. `_attachments/readme.md`, `_templates/meeting.md`, and `work/_documentation/intro.md` are the same case. A file named `_draft.md` in a normal folder is still included. Omitting the parameter returns the full graph. |

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

---

## 📤 Export

### Export Note as HTML
```http
GET /api/export/{note_path}?theme={theme_name}&download={true|false}
```

Exports a note as a standalone HTML file with all dependencies embedded for offline viewing.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `note_path` | path | Path to the note (e.g., `folder/note.md`) |
| `theme` | query (optional) | Theme name for styling (defaults to `light`) |
| `download` | query (optional) | If `true` (default), returns as file download. If `false`, displays in browser with Print/Close buttons for print preview |

**Response:**
- `download=true`: Returns an HTML file with `Content-Disposition: attachment` header
- `download=false`: Returns inline HTML for browser display (print preview mode)

**Features:**
- Fully self-contained HTML with embedded CSS
- Images converted to base64 data URLs
- MathJax for LaTeX math rendering (supports `$...$`, `$$...$$`, `\(...\)`, `\[...\]`)
- Mermaid.js for diagram rendering
- Highlight.js for syntax highlighting
- Wikilinks converted to decorative spans
- YAML frontmatter stripped
- Responsive design with print support
- Print toolbar with Print/Close buttons (preview mode only)

**Rate Limit:** 30 requests/minute

**Example:**
```bash
# Export with default theme (downloads file)
curl -O http://localhost:8000/api/export/notes/Welcome.md

# Export with dark theme (downloads file)
curl -O "http://localhost:8000/api/export/docs/API.md?theme=dracula"

# Print preview (open in browser)
# http://localhost:8000/api/export/docs/API.md?theme=light&download=false
```

### Archive Folder as ZIP
```http
GET /api/archive?folder={folder_path}
```

Downloads a folder and everything under it as a ZIP file. Omit `folder` to archive the whole vault.

Unlike the HTML export above, this returns the **raw files** exactly as they are stored — notes, their `_attachments`, and anything else in the tree — so the archive can be unzipped into another vault or opened in any editor.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `folder` | query (optional) | Folder relative to the vault root (e.g., `Projects/Q3`). Omitted or empty archives the entire vault |

**Response:**
- `200` — `application/zip`, named after the folder (or the app name for a whole-vault archive). Paths inside the archive are relative to the requested folder
- `403` — the instance is running in demo mode, where archiving is disabled
- `404` — folder does not exist, is not a directory, or contains no files
- `413` — the files exceed `ARCHIVE_MAX_FOLDER_MB` (default 500). Archive a subfolder or raise the limit

**Notes:**
- Note content is not parsed, so media referenced from a *different* folder is not pulled in: archiving a folder gives you that folder
- Anything whose name begins with a `.` is left out, at any depth — dot-directories are not descended into at all, and a `folder` containing a dot-component is refused. That covers tooling state (`.git`, `.obsidian`) and the app's own `.share-tokens.json`, so **the archive holds your notes and attachments, not app state or credentials**. Handing it to someone else cannot leak working share links
- Symlinks are skipped, files and directories alike, so an archive can never contain anything from outside the vault
- Already-compressed files (images, audio, video, PDFs) are stored rather than deflated, which is roughly six times faster for the same size
- The response sets `Content-Encoding: identity` so the archive is not gzipped a second time in transit and keeps its `Content-Length`
- Disabled entirely when `DEMO_MODE` is on: notes can be written on a demo, so an open archive route would let anyone upload attachments and then pull the whole vault repeatedly on the host's bandwidth

**Rate Limit:** 10 requests/minute

**Example:**
```bash
# One folder
curl -OJ "http://localhost:8000/api/archive?folder=Projects/Q3"

# The whole vault
curl -OJ http://localhost:8000/api/archive
```

---

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

### Get Index Stats
```http
GET /api/index/stats
```
Returns internal counters and sizes for the in-memory note index. Useful for confirming the index is built and observing its growth — handy when debugging slow endpoints or verifying that incremental updates are firing on every save/delete.

The index is rebuilt on the first scan after each process start and updated incrementally on every save/delete/move. It lives in process memory only — no disk persistence.

**Response:**
```json
{
  "built": true,
  "search_built": false,
  "notes": 142,
  "folders": 12,
  "tags": 37,
  "links_forward_entries": 89,
  "links_backward_entries": 76,
  "wikilink_tokens": 134,
  "search_terms": 0,
  "counters": {
    "build_count": 1,
    "last_build_ms": 12.4,
    "last_built_at": "2026-03-17T14:32:00+00:00",
    "incremental_updates": 8,
    "fingerprint_short_circuits": 3,
    "search_build_count": 0,
    "last_search_build_ms": 0.0
  }
}
```

| Field | Description |
|-------|-------------|
| `built` | `true` after the first vault scan completes |
| `search_built` | `true` after the first `/api/search` request (search index is built lazily) |
| `notes` | Number of note records currently held in the index |
| `folders` | Number of folder paths |
| `tags` | Number of unique tags |
| `links_forward_entries` | Number of notes that link out to at least one other note |
| `links_backward_entries` | Number of notes that have at least one incoming backlink |
| `wikilink_tokens` | Number of unique wikilink tokens (used for loose backlink matching by stem name) |
| `search_terms` | Number of unique terms in the full-text inverted search index (0 until first search) |
| `counters.build_count` | Total number of full index rebuilds since process start |
| `counters.last_build_ms` | Wall-clock time of the most recent full rebuild |
| `counters.last_built_at` | ISO timestamp of the most recent full rebuild |
| `counters.incremental_updates` | Number of single-note updates applied (save/delete/rename) |
| `counters.fingerprint_short_circuits` | Times a re-scan was skipped because the vault hash matched the previous scan |
| `counters.search_build_count` | Total number of search-index rebuilds |
| `counters.last_search_build_ms` | Wall-clock time of the most recent search-index rebuild |

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

Returns all notes that have a specific tag. To filter by several tags, see [Get Notes by Several Tags](#get-notes-by-several-tags).

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

### Get Notes by Several Tags
```http
GET /api/tags-match?tags=python&tags=tutorial
GET /api/tags-match?tags=python&tags=tutorial&match=any
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tags` | string | - | Tag to filter by. Repeat it for each tag (required) |
| `match` | string | `all` | `all` for notes with every tag, `any` for notes with at least one |
| `limit` | integer | - | Max notes to return (omit for all) |
| `offset` | integer | 0 | Number of notes to skip |

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
- `{{date:FMT}}` / `{{time:FMT}}` / `{{datetime:FMT}}` - Custom [`strftime`](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes) format (e.g. `{{datetime:%Y%m%d%H%M%S}}` → `20251126153045`, `{{date:%A}}` → `Wednesday`); invalid format strings are left verbatim. See [TEMPLATES.md](TEMPLATES.md) for a recipe table.

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
  "theme": "dracula",
  "slug": "quarterly-report"
}
```
Creates a share token for the note. Both fields are optional: `theme` defaults to
"light", and without `slug` the token is generated at random.

A `slug` becomes the token itself. It must be 3-64 characters of letters, numbers,
hyphens and underscores, and must not match another link's token (compared without
regard to case). On a note that is already shared, a slug different from the current
token **renames the link and the previous URL stops working** - a note has one token,
so this is a move rather than a second link. Sending the note's current token, or no
slug at all, leaves an existing link untouched.

**Response:**
```json
{
  "success": true,
  "token": "LRFEo86oSVeJ3Gju",
  "url": "http://localhost:8000/share/LRFEo86oSVeJ3Gju",
  "note_path": "folder/note.md"
}
```

**Slug errors:** `400` for a name that could never work, `409` for one already in use.
The `reason` is a stable code (`too_short`, `too_long`, `invalid_chars`, `taken`) so
clients can localise the message.
```json
{
  "detail": { "reason": "taken", "message": "Share slug rejected: taken" }
}
```

### Check Share Slug
```http
GET /api/share-slug?slug=quarterly-report&note_path=folder/note
```
Reports whether a custom slug can be used, for validating input before saving.
`note_path` is optional; when given, that note's own current token is not treated as a
conflict. Advisory only - the create call validates again, since another request can
claim the same name in between.

**Response:**
```json
{
  "available": false,
  "reason": "taken"
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

