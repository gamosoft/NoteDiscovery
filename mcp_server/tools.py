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
                },
                "folder": {
                    "type": "string",
                    "description": "Only include notes under this folder (e.g., 'projects/2024')."
                },
                "recursive": {
                    "type": "boolean",
                    "description": "With folder, also include subfolders. Defaults to true."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Useful for large vaults. If not specified, returns all matches."
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip. Use with limit for pagination."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_notes",
        "description": "List notes in the knowledge base with their metadata (title, path, last modified date, size). Use this to get an overview of available notes or find notes by browsing. Use folder to list only part of the vault.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Only include notes under this folder (e.g., 'projects/2024')."
                },
                "recursive": {
                    "type": "boolean",
                    "description": "With folder, also include subfolders. Defaults to true."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return. Useful for large vaults. If not specified, returns all notes."
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of notes to skip. Use with limit for pagination."
                }
            },
            "required": []
        }
    },
    {
        "name": "list_folders",
        "description": "List folders in the knowledge base, including empty ones, with the number of notes and subfolders directly inside each one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent": {
                    "type": "string",
                    "description": "Only list folders under this folder (e.g., 'projects'). If not specified, starts at the vault root."
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Include all nested folders. Set to false to list only direct children. Defaults to true."
                }
            },
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
        "description": "Get all notes that have a specific tag, or several tags. Use this to find related notes on a topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Tag name (without the # symbol). Use tags for several tags."
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tag names (without the # symbol)."
                },
                "match": {
                    "type": "string",
                    "enum": ["all", "any"],
                    "description": "With several tags: 'all' returns notes with every tag, 'any' returns notes with at least one. Defaults to 'all'."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return. Useful for large vaults. If not specified, returns all matches."
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of notes to skip. Use with limit for pagination."
                }
            },
            "required": []
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
    {
        "name": "get_backlinks",
        "description": "Get all notes that link TO a specific note (backlinks/reverse links). Use this to discover what other notes reference the current note, helping understand its importance and connections in the knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the note to find backlinks for (e.g., 'folder/note.md' or 'note.md')"
                }
            },
            "required": ["path"]
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
        "name": "move_folder",
        "description": "Move or rename a folder with all its notes and subfolders. Fails if a folder already exists at the new path. Other notes do not change: the result lists the notes whose links into it no longer work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_path": {
                    "type": "string",
                    "description": "Current path of the folder"
                },
                "new_path": {
                    "type": "string",
                    "description": "New path for the folder"
                }
            },
            "required": ["old_path", "new_path"]
        }
    },
    {
        "name": "delete_folder",
        "description": "Delete an empty folder. Fails if the folder still has anything in it, or if it is the vault root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the folder to delete"
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
        "name": "edit_note",
        "description": "Edit part of an existing note by replacing one exact piece of text, without resending the whole note. old_str must match the note content (as returned by get_note) exactly once, including whitespace and line breaks; otherwise nothing is written. To edit a section, include its heading in old_str. Prefer this over create_note for changes to existing notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the existing note"
                },
                "old_str": {
                    "type": "string",
                    "description": "Exact text to replace. Must appear exactly once in the note; add surrounding lines if needed to make it unique."
                },
                "new_str": {
                    "type": "string",
                    "description": "Replacement text. Use an empty string to delete old_str."
                }
            },
            "required": ["path", "old_str", "new_str"]
        }
    },
    {
        "name": "move_note",
        "description": "Move or rename a note to a different path. Use this to reorganize notes or rename them. Other notes do not change: the result lists the notes whose links to it no longer work.",
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
        "description": (
            "Create a new note from a template. Built-in placeholders like "
            "{{title}}, {{date}}, {{datetime}}, {{folder}}, {{date:FMT}} are "
            "substituted automatically (FMT is a Python strftime string). "
            "Use update_note afterwards if you need to inject custom content."
        ),
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
    {
        "name": "get_config",
        "description": (
            "Get NoteDiscovery server configuration: app name, version, "
            "whether search is enabled, authentication mode, autosave delay. "
            "Useful for confirming what server you're connected to and what "
            "features are available before calling other tools."
        ),
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
