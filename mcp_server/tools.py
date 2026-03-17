"""
MCP Tool definitions for NoteDiscovery.

Defines all available tools, their schemas, and descriptions.
Following MCP specification for tool definitions.
"""

from typing import Any

# Tool definitions following MCP schema specification
TOOLS: list[dict[str, Any]] = [
    # =========================================================================
    # Search & Discovery
    # =========================================================================
    {
        "name": "search_notes",
        "description": "Search through all notes using full-text search. Returns matching notes with snippets showing where the match was found. Use this to find notes by content, keywords, or phrases.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Can be keywords, phrases, or natural language."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_notes",
        "description": "List all notes in the knowledge base with their metadata (title, path, last modified date, size). Use this to get an overview of available notes or find notes by browsing.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_note",
        "description": "Read the full content of a specific note by its path. Returns the complete markdown content along with metadata. Use this after finding a note via search or list to read its contents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the note (e.g., 'folder/note.md' or 'note.md')"
                }
            },
            "required": ["path"]
        }
    },
    
    # =========================================================================
    # Tags & Organization
    # =========================================================================
    {
        "name": "list_tags",
        "description": "List all tags used across notes with the count of notes for each tag. Use this to understand how notes are organized and find topics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_notes_by_tag",
        "description": "Get all notes that have a specific tag. Use this to find related notes on a topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Tag name (without the # symbol)"
                }
            },
            "required": ["tag"]
        }
    },
    
    # =========================================================================
    # Knowledge Graph
    # =========================================================================
    {
        "name": "get_graph",
        "description": "Get the knowledge graph showing relationships between notes. Returns nodes (notes) and edges (links between them). Use this to understand how notes connect to each other.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    
    # =========================================================================
    # Note Management (Write Operations)
    # =========================================================================
    {
        "name": "create_note",
        "description": "Create a new note or update an existing one. The note will be saved as a markdown file. Use this to save new information or update existing notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path for the note (e.g., 'folder/new-note.md'). Include .md extension."
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content for the note"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "delete_note",
        "description": "Delete a note permanently. Use with caution - this cannot be undone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the note to delete"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "create_folder",
        "description": "Create a new folder for organizing notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path for the new folder (e.g., 'projects/2024')"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "append_to_note",
        "description": "Append content to an existing note without overwriting. Perfect for journals, logs, meeting notes, or collecting ideas incrementally.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the existing note"
                },
                "content": {
                    "type": "string",
                    "description": "Content to append to the note"
                },
                "add_timestamp": {
                    "type": "boolean",
                    "description": "Whether to add a timestamp header before the appended content (default: false)"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "move_note",
        "description": "Move or rename a note to a different path. Use this to reorganize notes or rename them.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_path": {
                    "type": "string",
                    "description": "Current path of the note"
                },
                "new_path": {
                    "type": "string",
                    "description": "New path for the note (can be in a different folder)"
                }
            },
            "required": ["old_path", "new_path"]
        }
    },
    {
        "name": "get_recent_notes",
        "description": "Get recently modified notes. Useful for finding what you were working on recently.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Get notes modified in the last N days (default: 7)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return (default: 10)"
                }
            },
            "required": []
        }
    },
    {
        "name": "create_note_from_template",
        "description": "Create a new note from a template with variable substitution. Variables in the template like {{variable_name}} will be replaced.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_name": {
                    "type": "string",
                    "description": "Name of the template to use (e.g., 'meeting-notes', 'daily-journal')"
                },
                "note_path": {
                    "type": "string",
                    "description": "Path for the new note (e.g., 'meetings/2024-03-13.md')"
                },
                "variables": {
                    "type": "object",
                    "description": "Variables to substitute in the template (e.g., {\"project\": \"Alpha\", \"date\": \"2024-03-13\"})"
                }
            },
            "required": ["template_name", "note_path"]
        }
    },
    
    # =========================================================================
    # Templates
    # =========================================================================
    {
        "name": "list_templates",
        "description": "List available note templates. Templates provide pre-formatted structures for common note types.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_template",
        "description": "Get the content of a specific template. Use this to see what a template contains before using it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Template name"
                }
            },
            "required": ["name"]
        }
    },
    
    # =========================================================================
    # System
    # =========================================================================
    {
        "name": "health_check",
        "description": "Check if NoteDiscovery server is running and healthy. Use this to verify connectivity.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]


def get_tool_names() -> list[str]:
    """Get list of all tool names."""
    return [tool["name"] for tool in TOOLS]


def get_tool_by_name(name: str) -> dict[str, Any] | None:
    """Get tool definition by name."""
    for tool in TOOLS:
        if tool["name"] == name:
            return tool
    return None
