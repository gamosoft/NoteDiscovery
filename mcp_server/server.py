"""
MCP Server implementation for NoteDiscovery.

Implements the Model Context Protocol (MCP), enabling AI assistants to
interact with NoteDiscovery notes. The dispatch logic is transport-agnostic:
`run()` serves it over stdio, and the backend serves it over Streamable HTTP
at /mcp (see backend/mcp_http.py).

This implementation uses only Python stdlib for minimal dependencies.
"""

import json
import re
import sys
import traceback
from typing import Any, Optional

from . import __version__
from .config import load_config, MCPConfig
from .client import NoteDiscoveryClient, APIResponse
from .tools import TOOLS, get_tool_names


# MCP protocol versions we can speak, newest first. The tool result shape is
# the same across all of them, so negotiation is just picking one.
SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)

# Server info: version comes from the package (resolved against the VERSION
# file at repo root, or importlib.metadata when pip-installed).
SERVER_INFO = {
    "name": "notediscovery-mcp",
    "version": __version__,
}


class MCPServer:
    """
    MCP Server that bridges AI assistants with NoteDiscovery.
    
    Implements the MCP protocol (JSON-RPC 2.0). `handle_message` is
    transport-agnostic; `run` serves it over stdio.
    """

    def __init__(self, config: MCPConfig, require_initialize: bool = True) -> None:
        """
        Initialize the MCP server.

        Args:
            config: MCP configuration
            require_initialize: Reject tool requests until `initialize` has been
                received. Stateless transports (HTTP) create a fresh server per
                request, so they turn this off.
        """
        self.config = config
        self.client = NoteDiscoveryClient(config)
        self._initialized = not require_initialize

    def _log(self, message: str) -> None:
        """Log message to stderr (not stdout which is for MCP protocol)."""
        print(f"[notediscovery-mcp] {message}", file=sys.stderr)

    def _response(self, id: Any, result: Any = None, error: Optional[dict] = None) -> dict:
        """
        Build a JSON-RPC response.

        Args:
            id: Request ID
            result: Result data (for success)
            error: Error object (for failure)
        """
        response: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": id,
        }

        if error is not None:
            response["error"] = error
        else:
            response["result"] = result

        return response

    def _error(self, code: int, message: str, data: Any = None) -> dict:
        """Create a JSON-RPC error object."""
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return error
    
    # =========================================================================
    # MCP Protocol Handlers
    # =========================================================================
    
    def handle_initialize(self, params: dict) -> dict:
        """Handle initialize request."""
        self._initialized = True
        self._log(f"Initialized with client: {params.get('clientInfo', {}).get('name', 'unknown')}")

        # Echo the client's version if we speak it, otherwise offer our newest
        requested = params.get("protocolVersion")
        if requested in SUPPORTED_PROTOCOL_VERSIONS:
            version = requested
        else:
            version = SUPPORTED_PROTOCOL_VERSIONS[0]

        return {
            "protocolVersion": version,
            "serverInfo": SERVER_INFO,
            "capabilities": {
                "tools": {},  # We support tools
            },
        }
    
    def handle_initialized(self, params: dict) -> None:
        """Handle initialized notification."""
        self._log(f"Connected to NoteDiscovery at {self.config.base_url}")
    
    def handle_list_tools(self, params: dict) -> dict:
        """Handle tools/list request."""
        return {"tools": TOOLS}
    
    def handle_call_tool(self, params: dict) -> dict:
        """
        Handle tools/call request.
        
        Dispatches to the appropriate tool handler based on tool name.
        """
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        
        self._log(f"Calling tool: {name}")
        
        # Dispatch to tool handler
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Unknown tool: {name}. Available tools: {', '.join(get_tool_names())}",
                }],
                "isError": True,
            }
        
        try:
            result = handler(arguments)
            return {
                "content": [{
                    "type": "text",
                    "text": result,
                }],
            }
        except Exception as e:
            self._log(f"Tool error: {e}")
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error executing {name}: {str(e)}",
                }],
                "isError": True,
            }
    
    # =========================================================================
    # Tool Implementations
    # =========================================================================
    
    def _validate_path(self, path: str) -> tuple[bool, str]:
        """
        Validate a path for safety.
        
        Args:
            path: The path to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not path:
            return False, "path is required"
        
        # Reject path traversal attempts
        if ".." in path:
            return False, "path cannot contain '..'"
        
        # Reject absolute paths (Unix and Windows)
        if path.startswith("/") or path.startswith("\\"):
            return False, "path cannot be absolute"
        if len(path) >= 2 and path[1] == ":":  # Windows drive letter (e.g., C:)
            return False, "path cannot be absolute"
        
        # Reject null bytes (security)
        if "\x00" in path:
            return False, "path contains invalid characters"
        
        return True, ""
    
    def _format_response(self, response: APIResponse) -> str:
        """Format API response as readable text."""
        if not response.success:
            return f"Error: {response.error}"
        
        if response.data is None:
            return "Success (no data)"
        
        # Pretty print JSON
        return json.dumps(response.data, indent=2, ensure_ascii=False)
    
    def _tool_search_notes(self, args: dict) -> str:
        """Search notes by query."""
        query = args.get("query", "").strip()
        limit = args.get("limit")
        offset = args.get("offset", 0)

        if not query:
            return "No search term provided. Please specify a query."

        # Use server-side pagination if limit is specified
        response = self.client.search(query, limit=limit, offset=offset)
        
        if not response.success:
            return f"Search failed: {response.error}"
        
        data = response.data or {}
        results = data.get("results", [])
        pagination = data.get("pagination")
        
        if not results:
            return f"No notes found matching '{query}'"
        
        # Build header with pagination info if available
        if pagination:
            total = pagination.get("total", len(results))
            output = [f"Found {total} result(s) for '{query}' (showing {len(results)}):\n"]
        else:
            output = [f"Found {len(results)} result(s) for '{query}':\n"]
        
        # Format search results
        for i, result in enumerate(results, 1):
            path = result.get("path", "unknown")
            matches = result.get("matches", [])
            output.append(f"{i}. **{path}**")
            
            # Show snippets with line numbers
            for match in matches[:2]:  # Limit to 2 snippets per note
                line_num = match.get("line_number", "?")
                context = match.get("context", "")
                # Strip HTML tags for cleaner AI output
                clean_context = re.sub(r'<[^>]+>', '', context)
                if clean_context:
                    output.append(f"   Line {line_num}: {clean_context[:150]}")
            output.append("")
        
        # Add pagination hint if there are more results
        if pagination and pagination.get("has_more"):
            output.append(f"... more results available (use limit and offset to paginate)")

        return "\n".join(output)

    def _tool_list_notes(self, args: dict) -> str:
        """List all notes."""
        limit = args.get("limit")
        offset = args.get("offset", 0)

        # Use server-side pagination if limit is specified
        response = self.client.list_notes(limit=limit, offset=offset)
        
        if not response.success:
            return f"Failed to list notes: {response.error}"
        
        data = response.data or {}
        notes = data.get("notes", [])
        folders = data.get("folders", [])
        pagination = data.get("pagination")
        
        # Build header with pagination info if available
        if pagination:
            total = pagination.get("total", len(notes))
            output = [f"Found {total} note(s) in {len(folders)} folder(s) (showing {len(notes)}):\n"]
        else:
            output = [f"Found {len(notes)} note(s) in {len(folders)} folder(s):\n"]
        
        # Group notes by folder
        notes_by_folder: dict[str, list] = {}
        for note in notes:
            path = note.get("path", "")
            folder = "/".join(path.split("/")[:-1]) or "(root)"
            if folder not in notes_by_folder:
                notes_by_folder[folder] = []
            notes_by_folder[folder].append(note)
        
        for folder in sorted(notes_by_folder.keys()):
            output.append(f"📁 {folder}/")
            for note in notes_by_folder[folder]:
                name = note.get("name", "unknown")
                modified = note.get("modified", "")
                output.append(f"   📝 {name} (modified: {modified})")
            output.append("")
        
        # Add pagination hint if there are more results
        if pagination and pagination.get("has_more"):
            output.append(f"... more notes available (use limit and offset to paginate)")

        return "\n".join(output)

    def _tool_get_note(self, args: dict) -> str:
        """Get note content."""
        path = args.get("path", "")
        is_valid, error = self._validate_path(path)
        if not is_valid:
            return f"Error: {error}"
        
        response = self.client.get_note(path)
        
        if not response.success:
            return f"Failed to get note: {response.error}"
        
        data = response.data or {}
        content = data.get("content", "")
        metadata = data.get("metadata", {})
        
        output = [f"# {path}\n"]
        if metadata:
            output.append(f"Modified: {metadata.get('modified', 'unknown')}")
            output.append(f"Size: {metadata.get('size', 0)} bytes\n")
        output.append("---\n")
        output.append(content)
        
        return "\n".join(output)
    
    def _tool_list_tags(self, args: dict) -> str:
        """List all tags."""
        response = self.client.list_tags()
        
        if not response.success:
            return f"Failed to list tags: {response.error}"
        
        data = response.data or {}
        tags = data.get("tags", {})
        
        if not tags:
            return "No tags found in any notes."
        
        output = [f"Found {len(tags)} tag(s):\n"]
        # tags is a dict: {"tag_name": count, ...}
        for name, count in sorted(tags.items(), key=lambda x: x[1], reverse=True):
            output.append(f"  #{name} ({count} note{'s' if count != 1 else ''})")
        
        return "\n".join(output)
    
    def _tool_get_notes_by_tag(self, args: dict) -> str:
        """Get notes with a specific tag."""
        tag = args.get("tag", "")
        limit = args.get("limit")
        offset = args.get("offset", 0)

        if not tag:
            return "Error: tag is required"

        # Use server-side pagination if limit is specified
        response = self.client.get_notes_by_tag(tag, limit=limit, offset=offset)

        if not response.success:
            return f"Failed to get notes by tag: {response.error}"

        data = response.data or {}
        notes = data.get("notes", [])
        count = data.get("count", len(notes))
        pagination = data.get("pagination")

        if not notes:
            return f"No notes found with tag '#{tag}'"

        # Build header with pagination info if available
        if pagination:
            output = [f"Notes with tag #{tag} ({count} total, showing {len(notes)}):\n"]
        else:
            output = [f"Notes with tag #{tag} ({count} total):\n"]
        
        for note in notes:
            path = note.get("path", "unknown")
            output.append(f"  📝 {path}")

        # Add pagination hint if there are more results
        if pagination and pagination.get("has_more"):
            output.append(f"\n... more notes available (use limit and offset to paginate)")

        return "\n".join(output)
    
    def _tool_get_graph(self, args: dict) -> str:
        """Get knowledge graph data."""
        response = self.client.get_graph()
        
        if not response.success:
            return f"Failed to get graph: {response.error}"
        
        data = response.data or {}
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        
        output = [f"Knowledge Graph: {len(nodes)} nodes, {len(edges)} connections\n"]
        
        # Find most connected notes
        connection_count: dict[str, int] = {}
        for edge in edges:
            source = edge.get("source", "")
            target = edge.get("target", "")
            connection_count[source] = connection_count.get(source, 0) + 1
            connection_count[target] = connection_count.get(target, 0) + 1
        
        if connection_count:
            output.append("Most connected notes:")
            sorted_notes = sorted(connection_count.items(), key=lambda x: x[1], reverse=True)[:10]
            for note, count in sorted_notes:
                output.append(f"  {note}: {count} connections")
        
        return "\n".join(output)

    def _tool_get_backlinks(self, args: dict) -> str:
        """Get backlinks (reverse links) for a note."""
        path = args.get("path", "")
        is_valid, error = self._validate_path(path)
        if not is_valid:
            return f"Error: {error}"

        response = self.client.get_backlinks(path)

        if not response.success:
            return f"Failed to get backlinks: {response.error}"

        data = response.data or {}
        backlinks = data.get("backlinks", [])
        note_path = data.get("path", path)

        if not backlinks:
            return f"No backlinks found for '{note_path}'. No other notes link to this note."

        output = [f"Backlinks for '{note_path}': {len(backlinks)} note(s) link to this note\n"]

        for bl in backlinks:
            bl_path = bl.get("path", "unknown")
            bl_name = bl.get("name", bl_path)
            references = bl.get("references", [])

            output.append(f"📄 {bl_name} ({bl_path})")
            for ref in references:
                line_num = ref.get("line_number", "?")
                context = ref.get("context", "")
                link_type = ref.get("type", "link")
                output.append(f"   Line {line_num} [{link_type}]: {context}")

        return "\n".join(output)
    
    def _tool_create_note(self, args: dict) -> str:
        """Create or update a note."""
        path = args.get("path", "")
        content = args.get("content", "")
        
        is_valid, error = self._validate_path(path)
        if not is_valid:
            return f"Error: {error}"
        if not content:
            return "Error: content is required"
        
        response = self.client.create_note(path, content)
        
        if not response.success:
            return f"Failed to create note: {response.error}"
        
        return f"✅ Note created/updated: {path}"
    
    def _tool_delete_note(self, args: dict) -> str:
        """Delete a note."""
        path = args.get("path", "")
        is_valid, error = self._validate_path(path)
        if not is_valid:
            return f"Error: {error}"
        
        response = self.client.delete_note(path)
        
        if not response.success:
            return f"Failed to delete note: {response.error}"
        
        return f"🗑️ Note deleted: {path}"
    
    def _tool_create_folder(self, args: dict) -> str:
        """Create a folder."""
        path = args.get("path", "")
        is_valid, error = self._validate_path(path)
        if not is_valid:
            return f"Error: {error}"
        
        response = self.client.create_folder(path)
        
        if not response.success:
            return f"Failed to create folder: {response.error}"
        
        return f"📁 Folder created: {path}"
    
    def _tool_list_templates(self, args: dict) -> str:
        """List templates."""
        response = self.client.list_templates()
        
        if not response.success:
            return f"Failed to list templates: {response.error}"
        
        data = response.data or {}
        templates = data.get("templates", [])
        
        if not templates:
            return "No templates available."
        
        output = ["Available templates:\n"]
        for template in templates:
            name = template.get("name", "unknown")
            output.append(f"  📄 {name}")
        
        return "\n".join(output)
    
    def _tool_get_template(self, args: dict) -> str:
        """Get template content."""
        name = args.get("name", "")
        # Validate template name (same rules as paths for safety)
        is_valid, error = self._validate_path(name)
        if not is_valid:
            return f"Error: {error.replace('path', 'name')}"
        
        response = self.client.get_template(name)
        
        if not response.success:
            return f"Failed to get template: {response.error}"
        
        data = response.data or {}
        content = data.get("content", "")
        
        return f"Template: {name}\n---\n{content}"
    
    def _tool_append_to_note(self, args: dict) -> str:
        """Append content to an existing note."""
        path = args.get("path", "")
        content = args.get("content", "")
        add_timestamp = args.get("add_timestamp", False)
        
        is_valid, error = self._validate_path(path)
        if not is_valid:
            return f"Error: {error}"
        if not content:
            return "Error: content is required"
        
        response = self.client.append_to_note(path, content, add_timestamp)
        
        if not response.success:
            return f"Failed to append to note: {response.error}"
        
        return f"✅ Content appended to: {path}"
    
    def _tool_move_note(self, args: dict) -> str:
        """Move or rename a note."""
        old_path = args.get("old_path", "")
        new_path = args.get("new_path", "")
        
        is_valid, error = self._validate_path(old_path)
        if not is_valid:
            return f"Error: old_path - {error}"
        
        is_valid, error = self._validate_path(new_path)
        if not is_valid:
            return f"Error: new_path - {error}"
        
        response = self.client.move_note(old_path, new_path)
        
        if not response.success:
            return f"Failed to move note: {response.error}"
        
        return f"✅ Note moved: {old_path} → {new_path}"
    
    def _tool_get_recent_notes(self, args: dict) -> str:
        """Get recently modified notes."""
        days = args.get("days", 7)
        limit = args.get("limit", 10)
        
        # Get all notes
        response = self.client.list_notes()
        
        if not response.success:
            return f"Failed to get notes: {response.error}"
        
        data = response.data or {}
        notes = data.get("notes", [])
        
        if not notes:
            return "No notes found."
        
        # Filter by date
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        
        recent_notes = []
        for note in notes:
            modified_str = note.get("modified", "")
            if modified_str:
                try:
                    # Parse ISO format datetime
                    modified = datetime.fromisoformat(modified_str.replace("Z", "+00:00"))
                    if modified.replace(tzinfo=None) >= cutoff:
                        recent_notes.append(note)
                except (ValueError, TypeError):
                    continue
        
        # Sort by modified date (most recent first) and limit
        recent_notes.sort(key=lambda x: x.get("modified", ""), reverse=True)
        recent_notes = recent_notes[:limit]
        
        if not recent_notes:
            return f"No notes modified in the last {days} day(s)."
        
        output = [f"📅 Notes modified in the last {days} day(s) (showing {len(recent_notes)}):\n"]
        for note in recent_notes:
            path = note.get("path", "unknown")
            modified = note.get("modified", "")[:10]  # Just the date part
            output.append(f"  📝 {path} (modified: {modified})")
        
        return "\n".join(output)
    
    def _tool_create_note_from_template(self, args: dict) -> str:
        """Create a note from a template."""
        template_name = args.get("template_name", "")
        note_path = args.get("note_path", "")

        if not template_name:
            return "Error: template_name is required"

        is_valid, error = self._validate_path(note_path)
        if not is_valid:
            return f"Error: note_path - {error}"

        response = self.client.create_note_from_template(template_name, note_path)

        if not response.success:
            return f"Failed to create note from template: {response.error}"

        return f"✅ Note created from template '{template_name}': {note_path}"
    
    def _tool_health_check(self, args: dict) -> str:
        """Check server health."""
        response = self.client.health_check()
        
        if not response.success:
            return f"❌ NoteDiscovery is not reachable: {response.error}"
        
        return f"✅ NoteDiscovery is healthy at {self.config.base_url}"

    def _tool_get_config(self, args: dict) -> str:
        """Get NoteDiscovery server configuration."""
        response = self.client.get_config()

        if not response.success:
            return f"Failed to get config: {response.error}"

        data = response.data or {}
        if not data:
            return "Server returned empty configuration."

        output = ["NoteDiscovery Server Configuration:\n"]
        for key in sorted(data.keys()):
            value = data[key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            output.append(f"  {key}: {value}")

        return "\n".join(output)
    
    # =========================================================================
    # Main Loop
    # =========================================================================
    
    def handle_message(self, message: Any) -> Optional[dict]:
        """
        Handle a single JSON-RPC message.
        
        Args:
            message: Parsed JSON-RPC message
            
        Returns:
            The JSON-RPC response to send back, or None when the message
            needs no reply (notifications and client responses).
        """
        if not isinstance(message, dict):
            return self._response(None, error=self._error(-32600, "Invalid Request"))
        
        request_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}
        
        # A client response to a server request; we never send any
        if not method:
            return None
        
        try:
            # Route to handler
            if method == "initialize":
                return self._response(request_id, self.handle_initialize(params))
            
            if method == "notifications/initialized":
                self.handle_initialized(params)
                return None
            
            if method in ("tools/list", "tools/call") and not self._initialized:
                return self._response(
                    request_id,
                    error=self._error(-32002, "Server not initialized")
                )
            
            if method == "tools/list":
                return self._response(request_id, self.handle_list_tools(params))
            
            if method == "tools/call":
                return self._response(request_id, self.handle_call_tool(params))
            
            if method == "ping":
                return self._response(request_id, {})
            
            # Unknown method; unknown notifications are ignored
            if request_id is None:
                return None
            return self._response(
                request_id,
                error=self._error(-32601, f"Method not found: {method}")
            )
        
        except Exception as e:
            self._log(f"Error handling {method}: {e}")
            traceback.print_exc(file=sys.stderr)
            if request_id is None:
                return None
            return self._response(
                request_id,
                error=self._error(-32603, f"Internal error: {str(e)}")
            )
    
    def run(self) -> None:
        """
        Run the MCP server, reading requests from stdin.
        
        This is the main event loop that processes JSON-RPC messages.
        """
        self._log("Starting MCP server...")
        self._log(f"NoteDiscovery URL: {self.config.base_url}")
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                response = self.handle_message(json.loads(line))
            except json.JSONDecodeError as e:
                self._log(f"Invalid JSON: {e}")
                response = self._response(
                    None,
                    error=self._error(-32700, f"Parse error: {str(e)}")
                )
            
            if response is not None:
                print(json.dumps(response), flush=True)
        
        self._log("Server shutting down")


def main() -> None:
    """
    Main entry point for the MCP server.
    
    Loads configuration from environment variables and starts the server.
    """
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    
    server = MCPServer(config)
    
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n[notediscovery-mcp] Interrupted", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"[notediscovery-mcp] Fatal error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
