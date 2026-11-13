"""
HTTP client for NoteDiscovery API.

Provides a clean interface to all NoteDiscovery API endpoints
with proper error handling, retries, and timeout management.
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Optional
from dataclasses import dataclass

from .config import MCPConfig


@dataclass
class APIResponse:
    """Represents an API response."""
    success: bool
    data: Any
    error: Optional[str] = None
    status_code: int = 200


class NoteDiscoveryClient:
    """
    HTTP client for NoteDiscovery API.
    
    Uses only stdlib (urllib) for minimal dependencies.
    Handles authentication, retries, and error formatting.
    """
    
    def __init__(self, config: MCPConfig) -> None:
        """
        Initialize the client.
        
        Args:
            config: MCP configuration object
        """
        self.config = config
        self.base_url = config.base_url
        self.headers = config.headers
        self.timeout = config.timeout
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, str | list[str]]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Make an HTTP request to the API.
        
        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (e.g., "/api/notes")
            params: Query parameters
            data: JSON body data
            
        Returns:
            APIResponse with success status and data/error
        """
        # Build URL with query parameters
        url = f"{self.base_url}{endpoint}"
        if params:
            query_string = urllib.parse.urlencode(params, doseq=True)
            url = f"{url}?{query_string}"
        
        # Prepare request body
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
        
        # Create request
        request = urllib.request.Request(
            url,
            data=body,
            headers=self.headers,
            method=method,
        )
        
        # Execute with retries and exponential backoff
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_data = response.read().decode("utf-8")
                    return APIResponse(
                        success=True,
                        data=json.loads(response_data) if response_data else None,
                        status_code=response.status,
                    )
            except urllib.error.HTTPError as e:
                # HTTP error (4xx, 5xx) - don't retry, return immediately
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8")
                    error_detail = json.loads(error_body).get("detail", error_body)
                except Exception:
                    error_detail = error_body or str(e)
                
                return APIResponse(
                    success=False,
                    data=None,
                    error=f"HTTP {e.code}: {error_detail}",
                    status_code=e.code,
                )
            except urllib.error.URLError as e:
                # Network error - retry with backoff
                last_error = f"Connection error: {e.reason}"
                if attempt < self.config.max_retries - 1:
                    time.sleep(2 ** attempt * 0.1)  # 0.1s, 0.2s, 0.4s...
                continue
            except TimeoutError:
                # Timeout - retry with backoff
                last_error = f"Request timed out after {self.timeout}s"
                if attempt < self.config.max_retries - 1:
                    time.sleep(2 ** attempt * 0.1)  # 0.1s, 0.2s, 0.4s...
                continue
            except json.JSONDecodeError as e:
                return APIResponse(
                    success=False,
                    data=None,
                    error=f"Invalid JSON response: {e}",
                )
        
        # All retries exhausted
        return APIResponse(
            success=False,
            data=None,
            error=last_error or "Unknown error after retries",
        )
    
    # =========================================================================
    # Notes API
    # =========================================================================
    
    def list_notes(
        self,
        limit: int | None = None,
        offset: int = 0,
        folder: str | None = None,
        recursive: bool = True
    ) -> APIResponse:
        """
        List all notes with metadata.
        
        Args:
            limit: Maximum number of notes to return (None = no limit)
            offset: Number of notes to skip (default: 0)
            folder: Only return notes under this folder
            recursive: With folder, also include subfolders (default: True)
        
        Returns:
            APIResponse with notes and folders data
        """
        params: dict[str, str] = {}
        if limit is not None:
            params["limit"] = str(limit)
            params["offset"] = str(offset)
        if folder:
            params["folder"] = folder
            params["recursive"] = "true" if recursive else "false"
        return self._request("GET", "/api/notes", params=params if params else None)
    
    def get_note(self, path: str) -> APIResponse:
        """
        Get a specific note's content.

        Args:
            path: Note path (e.g., "folder/note.md")

        Returns:
            APIResponse with note content and metadata
        """
        # /api/notes/{path} defaults to include_backlinks=True server-side,
        # which scans every note in the vault. The MCP get_note tool only
        # surfaces content + metadata, so we skip the backlinks computation.
        # Backlinks are still available via the dedicated get_backlinks method.
        encoded_path = urllib.parse.quote(path, safe="")
        return self._request(
            "GET",
            f"/api/notes/{encoded_path}",
            params={"include_backlinks": "false"},
        )
    
    def create_note(self, path: str, content: str) -> APIResponse:
        """
        Create or update a note.
        
        Args:
            path: Note path
            content: Markdown content
            
        Returns:
            APIResponse with creation result
        """
        encoded_path = urllib.parse.quote(path, safe="")
        return self._request("POST", f"/api/notes/{encoded_path}", data={"content": content})
    
    def delete_note(self, path: str) -> APIResponse:
        """
        Delete a note.
        
        Args:
            path: Note path
            
        Returns:
            APIResponse with deletion result
        """
        encoded_path = urllib.parse.quote(path, safe="")
        return self._request("DELETE", f"/api/notes/{encoded_path}")
    
    def append_to_note(self, path: str, content: str, add_timestamp: bool = False) -> APIResponse:
        """
        Append content to an existing note.
        
        Args:
            path: Note path
            content: Content to append
            add_timestamp: Whether to add a timestamp header
            
        Returns:
            APIResponse with append result
        """
        encoded_path = urllib.parse.quote(path, safe="")
        return self._request(
            "PATCH",
            f"/api/notes/{encoded_path}",
            data={"content": content, "add_timestamp": add_timestamp}
        )
    
    def edit_note(self, path: str, old_str: str, new_str: str) -> APIResponse:
        """
        Replace one exact occurrence of a text in an existing note.
        
        Args:
            path: Note path
            old_str: Text to replace (must appear exactly once)
            new_str: Replacement text
            
        Returns:
            APIResponse with edit result
        """
        return self._request(
            "POST",
            "/api/notes/replace",
            data={"path": path, "old_str": old_str, "new_str": new_str}
        )
    
    def move_note(self, old_path: str, new_path: str) -> APIResponse:
        """
        Move or rename a note.
        
        Args:
            old_path: Current note path
            new_path: New note path
            
        Returns:
            APIResponse with move result
        """
        return self._request(
            "POST",
            "/api/notes/move",
            data={"oldPath": old_path, "newPath": new_path, "reportBrokenLinks": True}
        )
    
    def create_note_from_template(
        self,
        template_name: str,
        note_path: str,
    ) -> APIResponse:
        """
        Create a note from a template.

        Built-in placeholders ({{title}}, {{date}}, {{datetime}},
        {{folder}}, {{date:FMT}}, etc.) are substituted server-side
        by apply_template_placeholders. There is no per-call variable
        injection; use update_note after creation for custom content.

        Args:
            template_name: Name of the template
            note_path: Path for the new note

        Returns:
            APIResponse with creation result
        """
        # The /api/templates/create-note endpoint reads `templateName` and `notePath`.
        data = {
            "templateName": template_name,
            "notePath": note_path,
        }
        return self._request("POST", "/api/templates/create-note", data=data)
    
    # =========================================================================
    # Search API
    # =========================================================================
    
    def search(
        self,
        query: str,
        limit: int | None = None,
        offset: int = 0,
        folder: str | None = None,
        recursive: bool = True
    ) -> APIResponse:
        """
        Search notes by query.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return (None = no limit)
            offset: Number of results to skip (default: 0)
            folder: Only return results under this folder
            recursive: With folder, also include subfolders (default: True)
            
        Returns:
            APIResponse with search results
        """
        params: dict[str, str] = {"q": query}
        if limit is not None:
            params["limit"] = str(limit)
            params["offset"] = str(offset)
        if folder:
            params["folder"] = folder
            params["recursive"] = "true" if recursive else "false"
        return self._request("GET", "/api/search", params=params)
    
    # =========================================================================
    # Tags API
    # =========================================================================
    
    def list_tags(self) -> APIResponse:
        """
        List all tags with note counts.
        
        Returns:
            APIResponse with tags data
        """
        return self._request("GET", "/api/tags")
    
    def get_notes_by_tag(
        self,
        tag: str,
        limit: int | None = None,
        offset: int = 0
    ) -> APIResponse:
        """
        Get notes with a specific tag.
        
        Args:
            tag: Tag name
            limit: Maximum number of notes to return (None = no limit)
            offset: Number of notes to skip (default: 0)
            
        Returns:
            APIResponse with matching notes
        """
        encoded_tag = urllib.parse.quote(tag, safe="")
        params: dict[str, str] = {}
        if limit is not None:
            params["limit"] = str(limit)
            params["offset"] = str(offset)
        return self._request(
            "GET",
            f"/api/tags/{encoded_tag}",
            params=params if params else None
        )
    
    def get_notes_by_tags(
        self,
        tags: list[str],
        match: str = "all",
        limit: int | None = None,
        offset: int = 0
    ) -> APIResponse:
        """
        Get notes that have several tags.

        Args:
            tags: Tag names
            match: "all" for notes with every tag, "any" for notes with at least one
            limit: Maximum number of notes to return (None = no limit)
            offset: Number of notes to skip (default: 0)

        Returns:
            APIResponse with matching notes
        """
        params: dict[str, str | list[str]] = {"tags": tags, "match": match}
        if limit is not None:
            params["limit"] = str(limit)
            params["offset"] = str(offset)
        return self._request("GET", "/api/tags-match", params=params)

    # =========================================================================
    # Folders API
    # =========================================================================
    
    def create_folder(self, path: str) -> APIResponse:
        """
        Create a new folder.
        
        Args:
            path: Folder path
            
        Returns:
            APIResponse with creation result
        """
        return self._request("POST", "/api/folders", data={"path": path})
    
    def move_folder(self, old_path: str, new_path: str) -> APIResponse:
        """
        Move or rename a folder with everything inside it.

        Args:
            old_path: Current folder path
            new_path: New folder path

        Returns:
            APIResponse with move result
        """
        return self._request(
            "POST",
            "/api/folders/move",
            data={"oldPath": old_path, "newPath": new_path, "reportBrokenLinks": True}
        )

    def delete_folder(self, path: str) -> APIResponse:
        """
        Delete an empty folder.

        Args:
            path: Folder path

        Returns:
            APIResponse with deletion result
        """
        encoded_path = urllib.parse.quote(path, safe="")
        return self._request("DELETE", f"/api/folders/{encoded_path}", params={"require_empty": "true"})

    # =========================================================================
    # Graph API
    # =========================================================================
    
    def get_graph(self) -> APIResponse:
        """
        Get note relationship graph data.

        Returns:
            APIResponse with graph nodes and links
        """
        return self._request("GET", "/api/graph")

    def get_backlinks(self, path: str) -> APIResponse:
        """
        Get backlinks (reverse links) for a specific note.

        Args:
            path: Note path (e.g., "folder/note.md")

        Returns:
            APIResponse with note info and backlinks
        """
        encoded_path = urllib.parse.quote(path, safe="")
        return self._request("GET", f"/api/notes/{encoded_path}", params={"include_backlinks": "true"})
    
    # =========================================================================
    # Templates API
    # =========================================================================
    
    def list_templates(self) -> APIResponse:
        """
        List available note templates.
        
        Returns:
            APIResponse with templates list
        """
        return self._request("GET", "/api/templates")
    
    def get_template(self, name: str) -> APIResponse:
        """
        Get a specific template's content.
        
        Args:
            name: Template name
            
        Returns:
            APIResponse with template content
        """
        encoded_name = urllib.parse.quote(name, safe="")
        return self._request("GET", f"/api/templates/{encoded_name}")
    
    # =========================================================================
    # System API
    # =========================================================================
    
    def health_check(self) -> APIResponse:
        """
        Check if NoteDiscovery server is healthy.
        
        Returns:
            APIResponse with health status
        """
        return self._request("GET", "/health")
    
    def get_config(self) -> APIResponse:
        """
        Get NoteDiscovery configuration.
        
        Returns:
            APIResponse with config data
        """
        return self._request("GET", "/api/config")
