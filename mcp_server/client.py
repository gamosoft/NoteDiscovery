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
        params: Optional[dict[str, str]] = None,
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
            query_string = urllib.parse.urlencode(params)
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
    
    def list_notes(self) -> APIResponse:
        """
        List all notes with metadata.
        
        Returns:
            APIResponse with notes and folders data
        """
        return self._request("GET", "/api/notes")
    
    def get_note(self, path: str) -> APIResponse:
        """
        Get a specific note's content.
        
        Args:
            path: Note path (e.g., "folder/note.md")
            
        Returns:
            APIResponse with note content and metadata
        """
        # URL-encode the path
        encoded_path = urllib.parse.quote(path, safe="")
        return self._request("GET", f"/api/notes/{encoded_path}")
    
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
            data={"oldPath": old_path, "newPath": new_path}
        )
    
    def create_note_from_template(
        self,
        template_name: str,
        note_path: str,
        variables: dict | None = None
    ) -> APIResponse:
        """
        Create a note from a template.
        
        Args:
            template_name: Name of the template
            note_path: Path for the new note
            variables: Variables to substitute in the template
            
        Returns:
            APIResponse with creation result
        """
        data = {
            "template": template_name,
            "path": note_path,
        }
        if variables:
            data["variables"] = variables
        
        return self._request("POST", "/api/templates/create-note", data=data)
    
    # =========================================================================
    # Search API
    # =========================================================================
    
    def search(self, query: str) -> APIResponse:
        """
        Search notes by query.
        
        Args:
            query: Search query string
            
        Returns:
            APIResponse with search results
        """
        return self._request("GET", "/api/search", params={"q": query})
    
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
    
    def get_notes_by_tag(self, tag: str) -> APIResponse:
        """
        Get notes with a specific tag.
        
        Args:
            tag: Tag name
            
        Returns:
            APIResponse with matching notes
        """
        encoded_tag = urllib.parse.quote(tag, safe="")
        return self._request("GET", f"/api/tags/{encoded_tag}")
    
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
