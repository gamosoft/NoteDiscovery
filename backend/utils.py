"""
Utility functions for file operations, search, and markdown processing
"""

import os
import re
import shutil
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


def validate_path_security(notes_dir: str, path: Path) -> bool:
    """
    Validate that a path is within the notes directory (security check).
    Prevents path traversal attacks.
    
    Args:
        notes_dir: Base notes directory
        path: Path to validate
        
    Returns:
        True if path is safe, False otherwise
    """
    try:
        path.resolve().relative_to(Path(notes_dir).resolve())
        return True
    except ValueError:
        return False


def ensure_directories(config: dict):
    """Create necessary directories if they don't exist"""
    dirs = [
        config['storage']['notes_dir'],
        config['storage']['plugins_dir'],
    ]
    
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)


def create_folder(notes_dir: str, folder_path: str) -> bool:
    """Create a new folder in the notes directory"""
    full_path = Path(notes_dir) / folder_path
    
    # Security check
    if not validate_path_security(notes_dir, full_path):
        return False
    
    full_path.mkdir(parents=True, exist_ok=True)
    
    return True


def get_all_folders(notes_dir: str) -> List[str]:
    """Get all folders in the notes directory, including empty ones"""
    folders = []
    notes_path = Path(notes_dir)
    
    for item in notes_path.rglob("*"):
        if item.is_dir():
            relative_path = item.relative_to(notes_path)
            folder_path = str(relative_path.as_posix())
            if folder_path and not folder_path.startswith('.'):
                folders.append(folder_path)
    
    return sorted(folders)


def move_note(notes_dir: str, old_path: str, new_path: str) -> bool:
    """Move a note to a different location"""
    old_full_path = Path(notes_dir) / old_path
    new_full_path = Path(notes_dir) / new_path
    
    # Security checks
    if not validate_path_security(notes_dir, old_full_path) or \
       not validate_path_security(notes_dir, new_full_path):
        return False
    
    if not old_full_path.exists():
        return False
    
    # Create parent directory if needed
    new_full_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Move the file
    old_full_path.rename(new_full_path)
    
    # Note: We don't automatically delete empty folders to preserve user's folder structure
    
    return True


def move_folder(notes_dir: str, old_path: str, new_path: str) -> bool:
    """Move a folder to a different location"""
    import shutil
    
    old_full_path = Path(notes_dir) / old_path
    new_full_path = Path(notes_dir) / new_path
    
    # Security checks
    if not validate_path_security(notes_dir, old_full_path) or \
       not validate_path_security(notes_dir, new_full_path):
        return False
    
    if not old_full_path.exists() or not old_full_path.is_dir():
        return False
    
    # Check if target already exists
    if new_full_path.exists():
        return False
    
    # Create parent directory if needed
    new_full_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Move the folder
    shutil.move(str(old_full_path), str(new_full_path))
    
    # Note: We don't automatically delete empty folders to preserve user's folder structure
    
    return True


def rename_folder(notes_dir: str, old_path: str, new_path: str) -> bool:
    """Rename a folder (same as move but for clarity)"""
    return move_folder(notes_dir, old_path, new_path)


def delete_folder(notes_dir: str, folder_path: str) -> bool:
    """Delete a folder and all its contents"""
    try:
        full_path = Path(notes_dir) / folder_path
        
        # Security check: ensure the path is within notes_dir
        if not validate_path_security(notes_dir, full_path):
            print(f"Security: Path is outside notes directory: {full_path}")
            return False
        
        if not full_path.exists():
            print(f"Folder does not exist: {full_path}")
            return False
            
        if not full_path.is_dir():
            print(f"Path is not a directory: {full_path}")
            return False
        
        # Delete the folder and all its contents
        shutil.rmtree(full_path)
        print(f"Successfully deleted folder: {full_path}")
        return True
    except Exception as e:
        print(f"Error deleting folder '{folder_path}': {e}")
        import traceback
        traceback.print_exc()
        return False


def get_all_notes(notes_dir: str) -> List[Dict]:
    """Recursively get all markdown notes and images"""
    items = []
    notes_path = Path(notes_dir)
    
    # Get all markdown notes
    for md_file in notes_path.rglob("*.md"):
        relative_path = md_file.relative_to(notes_path)
        stat = md_file.stat()
        
        items.append({
            "name": md_file.stem,
            "path": str(relative_path.as_posix()),
            "folder": str(relative_path.parent.as_posix()) if str(relative_path.parent) != "." else "",
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "size": stat.st_size,
            "type": "note"
        })
    
    # Get all images
    images = get_all_images(notes_dir)
    items.extend(images)
    
    return sorted(items, key=lambda x: x['modified'], reverse=True)


def get_note_content(notes_dir: str, note_path: str) -> Optional[str]:
    """Get the content of a specific note"""
    full_path = Path(notes_dir) / note_path
    
    if not full_path.exists() or not full_path.is_file():
        return None
    
    # Security check: ensure the path is within notes_dir
    if not validate_path_security(notes_dir, full_path):
        return None
    
    with open(full_path, 'r', encoding='utf-8') as f:
        return f.read()


def save_note(notes_dir: str, note_path: str, content: str) -> bool:
    """Save or update a note"""
    full_path = Path(notes_dir) / note_path
    
    # Ensure .md extension
    if not note_path.endswith('.md'):
        full_path = full_path.with_suffix('.md')
    
    # Security check
    if not validate_path_security(notes_dir, full_path):
        return False
    
    # Create parent directories if needed
    full_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return True


def delete_note(notes_dir: str, note_path: str) -> bool:
    """Delete a note"""
    full_path = Path(notes_dir) / note_path
    
    if not full_path.exists():
        return False
    
    # Security check
    if not validate_path_security(notes_dir, full_path):
        return False
    
    full_path.unlink()
    
    # Note: We don't automatically delete empty folders to preserve user's folder structure
    
    return True


def parse_wiki_links(content: str) -> List[str]:
    """Extract wiki-style links [[link]] from markdown content"""
    pattern = r'\[\[([^\]]+)\]\]'
    matches = re.findall(pattern, content)
    return matches


def search_notes(notes_dir: str, query: str) -> List[Dict]:
    """Simple full-text search through all notes"""
    results = []
    query_lower = query.lower()
    notes_path = Path(notes_dir)
    
    for md_file in notes_path.rglob("*.md"):
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if query_lower in content.lower():
                # Find context around match
                lines = content.split('\n')
                matched_lines = []
                
                for i, line in enumerate(lines):
                    if query_lower in line.lower():
                        # Get surrounding context
                        start = max(0, i - 1)
                        end = min(len(lines), i + 2)
                        context = '\n'.join(lines[start:end])
                        matched_lines.append({
                            "line_number": i + 1,
                            "context": context[:200]  # Limit context length
                        })
                
                relative_path = md_file.relative_to(notes_path)
                results.append({
                    "name": md_file.stem,
                    "path": str(relative_path.as_posix()),
                    "matches": matched_lines[:3]  # Limit to 3 matches per file
                })
        except Exception:
            continue
    
    return results


def create_note_metadata(notes_dir: str, note_path: str) -> Dict:
    """Get metadata for a note"""
    full_path = Path(notes_dir) / note_path
    
    if not full_path.exists():
        return {}
    
    stat = full_path.stat()
    
    # Count lines with proper file handle management
    with open(full_path, 'r', encoding='utf-8') as f:
        line_count = sum(1 for _ in f)
    
    return {
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "size": stat.st_size,
        "lines": line_count
    }


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing/replacing invalid characters.
    Keeps only alphanumeric chars, dots, dashes, and underscores.
    """
    # Get the extension first
    parts = filename.rsplit('.', 1)
    name = parts[0]
    ext = parts[1] if len(parts) > 1 else ''
    
    # Remove/replace invalid characters
    name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    
    # Rejoin with extension
    return f"{name}.{ext}" if ext else name


def get_attachment_dir(notes_dir: str, note_path: str) -> Path:
    """
    Get the attachments directory for a given note.
    If note is in root, returns /data/_attachments/
    If note is in folder, returns /data/folder/_attachments/
    """
    if not note_path:
        # Root level
        return Path(notes_dir) / "_attachments"
    
    note_path_obj = Path(note_path)
    folder = note_path_obj.parent
    
    if str(folder) == '.':
        # Note is in root
        return Path(notes_dir) / "_attachments"
    else:
        # Note is in a folder
        return Path(notes_dir) / folder / "_attachments"


def save_uploaded_image(notes_dir: str, note_path: str, filename: str, file_data: bytes) -> Optional[str]:
    """
    Save an uploaded image to the appropriate attachments directory.
    Returns the relative path to the image if successful, None otherwise.
    
    Args:
        notes_dir: Base notes directory
        note_path: Path of the note the image is being uploaded to
        filename: Original filename
        file_data: Binary file data
    
    Returns:
        Relative path to the saved image, or None if failed
    """
    # Sanitize filename
    sanitized_name = sanitize_filename(filename)
    
    # Get extension
    ext = Path(sanitized_name).suffix
    name_without_ext = Path(sanitized_name).stem
    
    # Add timestamp to prevent collisions
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    final_filename = f"{name_without_ext}-{timestamp}{ext}"
    
    # Get attachments directory
    attachments_dir = get_attachment_dir(notes_dir, note_path)
    
    # Create directory if it doesn't exist
    attachments_dir.mkdir(parents=True, exist_ok=True)
    
    # Full path to save the image
    full_path = attachments_dir / final_filename
    
    # Security check
    if not validate_path_security(notes_dir, full_path):
        print(f"Security: Attempted to save image outside notes directory: {full_path}")
        return None
    
    try:
        # Write the file
        with open(full_path, 'wb') as f:
            f.write(file_data)
        
        # Return relative path from notes_dir
        relative_path = full_path.relative_to(Path(notes_dir))
        return str(relative_path.as_posix())
    except Exception as e:
        print(f"Error saving image: {e}")
        return None


def get_all_images(notes_dir: str) -> List[Dict]:
    """
    Get all images from attachments directories.
    Returns list of image dictionaries with metadata.
    """
    images = []
    notes_path = Path(notes_dir)
    
    # Common image extensions
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    
    # Find all attachments directories
    for attachments_dir in notes_path.rglob("_attachments"):
        if not attachments_dir.is_dir():
            continue
        
        # Find all images in this attachments directory
        for image_file in attachments_dir.iterdir():
            if image_file.is_file() and image_file.suffix.lower() in image_extensions:
                relative_path = image_file.relative_to(notes_path)
                stat = image_file.stat()
                
                images.append({
                    "name": image_file.name,
                    "path": str(relative_path.as_posix()),
                    "folder": str(relative_path.parent.as_posix()),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "size": stat.st_size,
                    "type": "image"
                })
    
    return images

