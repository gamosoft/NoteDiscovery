# MCP Integration (AI Assistants)

NoteDiscovery includes a built-in **Model Context Protocol (MCP)** server that enables AI assistants like **Cursor**, **Claude Desktop**, and other MCP-compatible clients to interact with your notes.

## What is MCP?

MCP (Model Context Protocol) is an open standard that allows AI assistants to securely access external tools and data sources. With the NoteDiscovery MCP server, your AI assistant can:

- 🔍 **Search** through your notes
- 📖 **Read** note contents
- 🏷️ **Browse** by tags
- 📝 **Create** new notes
- ✏️ **Append** to existing notes (journals, logs)
- 📂 **Organize** notes (move, rename, folders)
- 📋 **Use templates** to create structured notes
- 🔗 **Explore** the knowledge graph
- 🔙 **Discover backlinks** (notes that link to a specific note)

## Quick Setup

### If You Use Docker

Add this to your `~/.cursor/mcp.json` (or Claude Desktop config):

```json
{
  "mcpServers": {
    "notediscovery": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "NOTEDISCOVERY_URL",
        "-e", "NOTEDISCOVERY_API_KEY",
        "ghcr.io/gamosoft/notediscovery:latest",
        "python", "-m", "mcp_server"
      ],
      "env": {
        "NOTEDISCOVERY_URL": "http://host.docker.internal:8000",
        "NOTEDISCOVERY_API_KEY": ""
      }
    }
  }
}
```

### If You Use Python

1. **Install NoteDiscovery** (if not already):
   ```bash
   pip install notediscovery
   # or from source:
   pip install .
   ```

2. **Add to your MCP config:**
   ```json
   {
     "mcpServers": {
       "notediscovery": {
         "command": "notediscovery-mcp",
         "env": {
           "NOTEDISCOVERY_URL": "http://localhost:8000",
           "NOTEDISCOVERY_API_KEY": ""
         }
       }
     }
   }
   ```

### Running from Source (No Install)

```json
{
  "mcpServers": {
    "notediscovery": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/NoteDiscovery",
      "env": {
        "PYTHONPATH": "/path/to/NoteDiscovery",
        "NOTEDISCOVERY_URL": "http://localhost:8000"
      }
    }
  }
}
```

> **Note:** The `PYTHONPATH` is required so Python can find the `mcp_server` module. On Windows, use backslashes: `"PYTHONPATH": "C:\\path\\to\\NoteDiscovery"`

### Advanced: 24×7 / Remote Access (mcp-proxy)

The setups above spawn the MCP server **per session** — your AI client starts a fresh container/process every time you open a chat and tears it down when you close it. That's the recommended default: zero setup, no auth surface, no long-lived process to maintain.

If you'd rather run the MCP server as a **long-lived service** so one host serves many devices, use the community tool [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) to wrap the stdio server and expose it over SSE:

```bash
# Make sure the image is fresh
docker pull ghcr.io/gamosoft/notediscovery:latest

# Run mcp-proxy in front of the stdio server
# (`--` separates mcp-proxy flags from the wrapped command — required so the
#  parser doesn't try to interpret `--rm`, `-i`, etc. as its own arguments)
mcp-proxy --port 3000 -- docker run --rm -i \
  -e NOTEDISCOVERY_URL=https://notediscovery.homelab.local \
  ghcr.io/gamosoft/notediscovery:latest python -m mcp_server
```

> If you get `unrecognized arguments` from mcp-proxy, your version may use `--sse-port` instead of `--port`. Run `mcp-proxy --help` to check.

The example above assumes a specific topology: mcp-proxy runs on your host, the MCP server spawns as a short-lived container per SSE connection, and a separately-running NoteDiscovery instance is reachable at `https://notediscovery.homelab.local`. That's just one valid placement — **NoteDiscovery and mcp-proxy don't need to live in the same place**. `NOTEDISCOVERY_URL` can point at any reachable URL, for example:

- Remote homelab / LAN server (as in the example above): `https://notediscovery.homelab.local`
- Same host via Docker's special hostname: `http://host.docker.internal:8000`
- Sibling service in the same `docker-compose.yml`: `http://notediscovery:8000`
- Native Python install on the same host: `http://localhost:8000`

If you want both in one stack (NoteDiscovery + mcp-proxy together), a `docker-compose.yml` with both as services on the same Docker network is the cleanest setup — use the Docker service name for `NOTEDISCOVERY_URL` (`http://notediscovery:8000`) rather than a host-bound URL, which keeps the traffic on the internal network and survives host networking changes.

> **Heads up on scope:** [`mcp-proxy`](https://github.com/sparfenyuk/mcp-proxy) is a community project maintained independently from NoteDiscovery, and its CLI flags, configuration options, and behavior can (and do) change between releases. This section shows the general integration pattern. for anything proxy-specific (CLI changes, TLS termination, auth in front of the proxy, multi-client behavior, daemonization, compose recipes, etc.) please consult their docs and issue tracker. If you hit something that looks NoteDiscovery-side (a tool returning unexpected data, the underlying MCP server crashing, missing capabilities) — just open an issue here. 🙂

Then point each client at the SSE endpoint — one shared config across all your devices:

```json
{
  "mcpServers": {
    "notediscovery": {
      "url": "http://your-host:3000/sse"
    }
  }
}
```

For production use, wrap `mcp-proxy` in a `systemd` unit or a `docker-compose` service with a restart policy so it survives reboots and crashes, or use a container.

#### Trade-offs vs. the default per-session setup

| | Per-session (default) | 24×7 with mcp-proxy |
|---|---|---|
| Setup complexity | None — JSON config and done | Persistent process to manage (systemd, docker-compose, etc.) |
| Startup cost | ~1–2s container cold start per session | None — server is always warm |
| Multi-device | Each device spawns its own | One shared instance |
| Network exposure | None (local pipes only) | HTTP endpoint — **you** own the auth, TLS, and firewalling |
| Concurrent clients | One per spawned container | Depends on how `mcp-proxy` is configured |
| State / leak resilience | Fresh process every session | Long-running — restart policy recommended |

**Per-session stdio is the right default** for single-user, single-machine setups. Reach for the 24×7 setup only if you genuinely need shared or remote access and you're comfortable owning the auth and network-exposure side of it (e.g., LAN-only, or behind a reverse proxy with authentication).

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NOTEDISCOVERY_URL` | Yes | `http://localhost:8000` | URL where NoteDiscovery is running |
| `NOTEDISCOVERY_API_KEY` | If auth enabled | - | API key from `config.yaml` |
| `NOTEDISCOVERY_TIMEOUT` | No | `30` | Request timeout in seconds |
| `NOTEDISCOVERY_MAX_RETRIES` | No | `3` | Max retry attempts for failed requests |

### URL Configuration by Setup

| Your Setup | `NOTEDISCOVERY_URL` |
|------------|---------------------|
| Local Python (`run.py`) | `http://localhost:8000` |
| Docker with `-p 8000:8000` | `http://host.docker.internal:8000` |
| Docker with `-p 3000:8000` | `http://host.docker.internal:3000` |
| Remote server | `https://notes.example.com` |

## Available Tools

The MCP server provides these tools to AI assistants:

### Search & Discovery

| Tool | Description |
|------|-------------|
| `search_notes` | Full-text search across all notes (supports pagination) |
| `list_notes` | List all notes with metadata (supports pagination) |
| `get_note` | Read a specific note's content |
| `get_recent_notes` | Get recently modified notes (last N days) |

### Organization

| Tool | Description |
|------|-------------|
| `list_tags` | List all tags with note counts |
| `get_notes_by_tag` | Find notes with a specific tag (supports pagination) |
| `get_graph` | Get knowledge graph data |
| `get_backlinks` | Get notes that link to a specific note (reverse links) |

### Note Management

| Tool | Description |
|------|-------------|
| `create_note` | Create or update a note |
| `append_to_note` | Append content to an existing note (great for journals/logs) |
| `move_note` | Move or rename a note |
| `delete_note` | Delete a note |
| `create_folder` | Create a new folder |

### Templates

| Tool | Description |
|------|-------------|
| `list_templates` | List available templates |
| `get_template` | Get template content |
| `create_note_from_template` | Create a note from a template (built-in placeholders only) |

### System

| Tool | Description |
|------|-------------|
| `health_check` | Verify server connectivity |
| `get_config` | Get server config (name, version, enabled features, autosave delay) |

## Tool Details

### Pagination with `limit` and `offset`

Some tools support optional pagination parameters for large vaults:

| Tool | Parameters | Description |
|------|------------|-------------|
| `search_notes` | `limit`, `offset` | Paginate search results |
| `list_notes` | `limit`, `offset` | Paginate notes list |
| `get_notes_by_tag` | `limit`, `offset` | Paginate notes by tag |

- `limit` - Maximum items to return (omit for all)
- `offset` - Number of items to skip (for pagination)

**Example prompts:**
- "Search for notes about Python, but just show me the first 5 results"
- "Show me the next 5 Python notes" (uses offset)

---

### `get_backlinks`

Find all notes that link TO a specific note (reverse links / backlinks). Useful for understanding how a note connects to your knowledge base.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the note to find backlinks for |

**Returns:** List of notes that contain links to the specified note, with context snippets showing where the link appears.

**Example prompts:**
- "What notes link to my Project Alpha note?"
- "Show me the backlinks for meeting-notes.md"
- "Find all notes that reference my API documentation"

---

### `append_to_note`

Append content to an existing note without overwriting. Perfect for journals, logs, or collecting ideas.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to existing note |
| `content` | string | Yes | Content to append |
| `add_timestamp` | boolean | No | Add timestamp header before content |

**Example prompt:** "Add this meeting summary to my daily-journal.md with a timestamp"

---

### `move_note`

Move or rename a note to a different location.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `old_path` | string | Yes | Current note path |
| `new_path` | string | Yes | New path (can include folder) |

**Example prompt:** "Move draft.md to published/final-article.md"

---

### `get_recent_notes`

Get recently modified notes. Useful for context about what you've been working on.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `days` | integer | No | 7 | Notes modified in last N days |
| `limit` | integer | No | 10 | Max notes to return |

**Example prompt:** "What was I working on this week?"

---

### `create_note_from_template`

Create a new note from a template. Built-in placeholders are substituted
server-side. Need to inject custom content? Call `update_note` after creation.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `template_name` | string | Yes | Template name (e.g., "meeting-notes") |
| `note_path` | string | Yes | Path for the new note |

**Built-in placeholders:** `{{title}}`, `{{date}}`, `{{time}}`, `{{datetime}}`,
`{{timestamp}}`, `{{year}}`, `{{month}}`, `{{day}}`, `{{folder}}`, plus the
`strftime` escape hatch — `{{date:FMT}}`, `{{time:FMT}}`, `{{datetime:FMT}}`
where `FMT` is a Python `strftime()` format string. See [TEMPLATES.md](TEMPLATES.md).

**Example prompt:** "Create a new meeting note for Project Alpha using the meeting-notes template"

## Usage Examples

Once configured, you can interact with your notes naturally:

> **User:** "What did I write about Kubernetes?"
> 
> **AI:** *Uses `search_notes` to find relevant notes, then `get_note` to read them*
> 
> "I found 3 notes about Kubernetes. In your 'devops/k8s-setup.md' note from last week, you documented..."

> **User:** "Create a new note summarizing our conversation"
> 
> **AI:** *Uses `create_note` to save the summary*
> 
> "Done! I've created 'meetings/ai-discussion-2024-03-13.md' with the summary."

> **User:** "Show me all notes tagged with #project"
> 
> **AI:** *Uses `get_notes_by_tag` to find them*
> 
> "You have 7 notes with the #project tag..."

> **User:** "Add this to my daily journal with a timestamp"
> 
> **AI:** *Uses `append_to_note` with `add_timestamp: true`*
> 
> "Done! I've appended your entry to 'daily-journal.md' with today's timestamp."

> **User:** "What was I working on last week?"
> 
> **AI:** *Uses `get_recent_notes` with `days: 7`*
> 
> "You modified 5 notes in the last week: project-roadmap.md, meeting-notes.md..."

> **User:** "Create a meeting note for the design review using my template"
> 
> **AI:** *Uses `create_note_from_template` with the meeting-notes template*
> 
> "Created 'meetings/design-review-2024-03-13.md' from your meeting-notes template."

> **User:** "What notes link to my Project Alpha document?"
> 
> **AI:** *Uses `get_backlinks` to find reverse links*
> 
> "3 notes reference Project Alpha: your meeting notes from March 12, the quarterly review, and the team standup notes..."

## Authentication

If you have authentication enabled in NoteDiscovery:

1. Generate an API key in `config.yaml`:
   ```yaml
   authentication:
     enabled: true
     api_key: "your-secure-api-key-here"
   ```

2. Add the key to your MCP config:
   ```json
   "env": {
     "NOTEDISCOVERY_URL": "http://localhost:8000",
     "NOTEDISCOVERY_API_KEY": "your-secure-api-key-here"
   }
   ```

## Troubleshooting

### "Connection refused" error

- Ensure NoteDiscovery is running
- Check the `NOTEDISCOVERY_URL` is correct
- For Docker: use `host.docker.internal` instead of `localhost`

### "Not authenticated" error

- Check that your API key is correct
- Ensure the API key in MCP config matches `config.yaml`

### MCP server not starting

- Check Cursor/Claude Desktop logs for errors
- Try running manually: `python -m mcp_server`
- Verify Python 3.10+ is installed

### Verify connectivity manually

```bash
# Set environment variables
export NOTEDISCOVERY_URL=http://localhost:8000
export NOTEDISCOVERY_API_KEY=your-key

# Run the MCP server (Ctrl+C to stop)
python -m mcp_server
```

Then in another terminal:
```bash
# Test the health endpoint directly
curl http://localhost:8000/health
```

## Architecture

```
┌─────────────────┐     stdio (JSON-RPC)     ┌─────────────────┐
│   AI Assistant  │ ◄──────────────────────► │   MCP Server    │
│ (Cursor/Claude) │                          │ (notediscovery- │
└─────────────────┘                          │      mcp)       │
                                             └────────┬────────┘
                                                      │
                                                      │ HTTP/REST
                                                      ▼
                                             ┌─────────────────┐
                                             │  NoteDiscovery  │
                                             │     Server      │
                                             │  (port 8000)    │
                                             └─────────────────┘
                                                      │
                                                      ▼
                                             ┌─────────────────┐
                                             │   Your Notes    │
                                             │  (./data/*.md)  │
                                             └─────────────────┘
```

The MCP server is a **separate process** that:
1. Communicates with AI assistants via stdio (stdin/stdout)
2. Translates MCP requests into HTTP API calls
3. Returns results back to the AI assistant

Your notes stay local. The MCP server just provides a bridge for AI access.

## Privacy & Security

- **Notes stay local**: The MCP server only accesses notes through NoteDiscovery's API
- **No external calls**: No data is sent to external services
- **API key protected**: Use authentication to control access
- **Read what you allow**: AI can only access notes NoteDiscovery serves

## File Structure

```
NoteDiscovery/
├── mcp_server/
│   ├── __init__.py      # Package entry point
│   ├── __main__.py      # Module runner
│   ├── server.py        # MCP protocol implementation
│   ├── client.py        # HTTP client for NoteDiscovery API
│   ├── config.py        # Configuration management
│   └── tools.py         # Tool definitions
└── ...
```

## Try it with a local LLM

For a batteries-included setup that runs NoteDiscovery alongside [Ollama](https://ollama.com) (local LLM runtime) and [Open WebUI](https://openwebui.com) (browser chat UI), see **[OLLAMA-STACK.md](../OLLAMA-STACK.md)** in the repo root. One `docker compose` command spins everything up, and you can point Cursor at both your notes (via this MCP server) and your local model.
