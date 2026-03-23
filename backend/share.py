"""
Share Token Management for NoteDiscovery
Handles creating, storing, and revoking share tokens for public note access.
"""

import asyncio
import json
import secrets
import string
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import aiofiles

# Async lock for safe concurrent access
_lock = asyncio.Lock()


def generate_token(length: int = 16) -> str:
    """Generate a URL-safe random token."""
    # Use alphanumeric + underscore/hyphen (URL-safe)
    alphabet = string.ascii_letters + string.digits + '_-'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def get_tokens_file_path(data_dir: str) -> Path:
    """Get the path to the share tokens file."""
    return Path(data_dir) / '.share-tokens.json'


async def load_tokens(data_dir: str) -> Dict[str, Dict[str, Any]]:
    """Load share tokens from file."""
    tokens_file = get_tokens_file_path(data_dir)
    
    if not tokens_file.exists():
        return {}
    
    try:
        async with aiofiles.open(tokens_file, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {}


async def save_tokens(data_dir: str, tokens: Dict[str, Dict[str, Any]]) -> bool:
    """Save share tokens to file."""
    tokens_file = get_tokens_file_path(data_dir)
    
    try:
        # Ensure parent directory exists
        tokens_file.parent.mkdir(parents=True, exist_ok=True)
        
        async with aiofiles.open(tokens_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(tokens, indent=2, ensure_ascii=False))
        return True
    except IOError as e:
        print(f"Failed to save share tokens: {e}")
        return False


async def create_share_token(data_dir: str, note_path: str, theme: str = "light") -> Optional[str]:
    """
    Create a share token for a note.
    If the note already has a token, returns the existing one.
    
    Args:
        data_dir: Path to the data directory
        note_path: Path to the note (relative to notes_dir)
        theme: The theme to use when viewing the shared note
    
    Returns:
        The share token, or None on error
    """
    async with _lock:
        tokens = await load_tokens(data_dir)
        
        # Check if note already has a token
        for token, info in tokens.items():
            if info.get('path') == note_path:
                return token
        
        # Generate new token
        token = generate_token()
        
        # Ensure uniqueness (extremely unlikely collision, but check anyway)
        while token in tokens:
            token = generate_token()
        
        # Store token with theme
        tokens[token] = {
            'path': note_path,
            'theme': theme,
            'created': datetime.now(timezone.utc).isoformat()
        }
        
        if await save_tokens(data_dir, tokens):
            return token
        return None


async def get_share_token(data_dir: str, note_path: str) -> Optional[str]:
    """
    Get the share token for a note, if it exists.
    
    Args:
        data_dir: Path to the data directory
        note_path: Path to the note
    
    Returns:
        The share token, or None if not shared
    """
    tokens = await load_tokens(data_dir)
    
    for token, info in tokens.items():
        if info.get('path') == note_path:
            return token
    
    return None


async def get_note_by_token(data_dir: str, token: str) -> Optional[Dict[str, Any]]:
    """
    Get the note info for a share token.
    
    Args:
        data_dir: Path to the data directory
        token: The share token
    
    Returns:
        Dict with 'path' and 'theme', or None if token not found
    """
    tokens = await load_tokens(data_dir)
    
    if token in tokens:
        return {
            'path': tokens[token].get('path'),
            'theme': tokens[token].get('theme', 'light')
        }
    
    return None


async def get_all_shared_paths(data_dir: str) -> list:
    """
    Get a list of all currently shared note paths.
    Used for displaying share indicators in the UI.
    
    Args:
        data_dir: Path to the data directory
    
    Returns:
        List of note paths that are currently shared
    """
    tokens = await load_tokens(data_dir)
    return [info.get('path') for info in tokens.values() if info.get('path')]


async def revoke_share_token(data_dir: str, note_path: str) -> bool:
    """
    Revoke (delete) the share token for a note.
    
    Args:
        data_dir: Path to the data directory
        note_path: Path to the note
    
    Returns:
        True if token was revoked, False if not found or error
    """
    async with _lock:
        tokens = await load_tokens(data_dir)
        
        # Find and remove token for this note
        token_to_remove = None
        for token, info in tokens.items():
            if info.get('path') == note_path:
                token_to_remove = token
                break
        
        if token_to_remove:
            del tokens[token_to_remove]
            return await save_tokens(data_dir, tokens)
        
        return False


async def get_share_info(data_dir: str, note_path: str) -> Optional[Dict[str, Any]]:
    """
    Get share information for a note.
    
    Args:
        data_dir: Path to the data directory
        note_path: Path to the note
    
    Returns:
        Dict with token, theme, and created date, or None if not shared
    """
    tokens = await load_tokens(data_dir)
    
    for token, info in tokens.items():
        if info.get('path') == note_path:
            return {
                'token': token,
                'theme': info.get('theme', 'light'),
                'created': info.get('created'),
                'shared': True
            }
    
    return {'shared': False}


async def update_token_path(data_dir: str, old_path: str, new_path: str) -> bool:
    """
    Update the path for a token when a note is moved/renamed.
    
    Args:
        data_dir: Path to the data directory
        old_path: Old note path
        new_path: New note path
    
    Returns:
        True if updated, False if not found or error
    """
    async with _lock:
        tokens = await load_tokens(data_dir)
        
        for token, info in tokens.items():
            if info.get('path') == old_path:
                info['path'] = new_path
                return await save_tokens(data_dir, tokens)
        
        return False


async def delete_token_for_note(data_dir: str, note_path: str) -> bool:
    """
    Delete the share token when a note is deleted.
    Alias for revoke_share_token for clarity.
    """
    return await revoke_share_token(data_dir, note_path)
