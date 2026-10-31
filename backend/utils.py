"""
Utility functions for file operations, search, and markdown processing.

Heavy work (backlinks, graph, full-text search, tag aggregation) is delegated
to the in-memory index in note_index.py.
"""

import logging
import os
import re
import shutil
import threading
import time
import traceback
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, TypeVar, Callable
from datetime import datetime, timezone

from . import note_index
from .note_index import NoteRecord, extract_links_from_content

logger = logging.getLogger("uvicorn.error")


# ============================================================================
# Pagination Support
# ============================================================================

@dataclass
class PaginationResult:
    """
    Result of applying pagination to a list.
    
    Attributes:
        items: The paginated subset of items
        total: Total number of items before pagination
        limit: The limit that was applied (None if no pagination)
        offset: The offset that was applied
        has_more: Whether there are more items after this page
    """
    items: List[Any]
    total: int
    limit: Optional[int]
    offset: int
    has_more: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert pagination info to dict for API response."""
        return {
            "limit": self.limit,
            "offset": self.offset,
            "total": self.total,
            "has_more": self.has_more
        }


T = TypeVar('T')


def paginate(
    items: List[T],
    limit: Optional[int] = None,
    offset: int = 0,
    sort_key: Optional[Callable[[T], Any]] = None,
    sort_reverse: bool = False
) -> PaginationResult:
    """
    Apply optional pagination to a list with consistent sorting.
    
    This function is designed to be backward-compatible:
    - If limit is None, returns all items (no pagination)
    - If limit is provided, returns a paginated subset
    
    Sorting is always applied (when sort_key is provided) to ensure
    stable pagination across requests.
    
    Args:
        items: List of items to paginate
        limit: Maximum number of items to return (None = no limit)
        offset: Number of items to skip (default: 0)
        sort_key: Function to extract sort key from item (e.g., lambda x: x['path'])
        sort_reverse: If True, sort in descending order
        
    Returns:
        PaginationResult with items and pagination metadata
        
    Example:
        # No pagination (frontend compatibility)
        result = paginate(notes)
        
        # With pagination (MCP usage)
        result = paginate(notes, limit=20, offset=0, sort_key=lambda x: x['path'])
    """
    total = len(items)
    
    # Apply sorting for consistent ordering (prevents out-of-order issues)
    if sort_key is not None:
        items = sorted(items, key=sort_key, reverse=sort_reverse)
    
    # Apply pagination only if limit is specified
    if limit is not None:
        # Clamp offset to valid range
        offset = max(0, min(offset, total))
        end = offset + limit
        paginated_items = items[offset:end]
        has_more = end < total
    else:
        # No pagination - return all items
        paginated_items = items
        offset = 0
        has_more = False
    
    return PaginationResult(
        items=paginated_items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more
    )


# ============================================================================
# In-memory caches
#
# Two layers:
#   _tag_cache / _links_cache : per-file, mtime-keyed. Avoid re-parsing the
#     same file on warm scans. Used by get_tags_and_links_cached.
#   _SCAN_WALK_CACHE          : per-scan TTL cache. Avoids repeated full-
#     directory walks when several endpoints fire in quick succession.
#
# All three are invalidated on every mutation (save/delete/move). The
# note_index in note_index.py is the system of record for derived data
# (links, backlinks, tags-by-name, search) — these caches just exist to
# avoid double-reading files we already parsed.
# ============================================================================

_tag_cache: Dict[str, Tuple[float, List[str]]] = {}
_links_cache: Dict[str, Tuple[float, Dict[str, List[str]]]] = {}

_SCAN_WALK_CACHE_LOCK = threading.Lock()
_SCAN_WALK_CACHE_TTL_SECONDS = 1.0
# key: (resolved_notes_dir, include_media) -> (cached_at_monotonic_seconds, (notes, folders))
_SCAN_WALK_CACHE: Dict[Tuple[str, bool], Tuple[float, Tuple[List[Dict], List[str]]]] = {}


def _scan_cache_get(key: Tuple[str, bool]) -> Optional[Tuple[List[Dict], List[str]]]:
    now = time.monotonic()
    with _SCAN_WALK_CACHE_LOCK:
        entry = _SCAN_WALK_CACHE.get(key)
        if not entry:
            return None
        cached_at, value = entry
        if (now - cached_at) > _SCAN_WALK_CACHE_TTL_SECONDS:
            _SCAN_WALK_CACHE.pop(key, None)
            return None
        return value


def _scan_cache_set(key: Tuple[str, bool], value: Tuple[List[Dict], List[str]]) -> None:
    with _SCAN_WALK_CACHE_LOCK:
        _SCAN_WALK_CACHE[key] = (time.monotonic(), value)


def _scan_cache_invalidate() -> None:
    """Drop the TTL scan cache. Called from every mutation handler."""
    with _SCAN_WALK_CACHE_LOCK:
        _SCAN_WALK_CACHE.clear()


def ensure_index_built(notes_dir: str) -> None:
    """Trigger a fresh scan when the NoteIndex hasn't been populated yet.
    Scans with include_media=True so every index consumer (stats, notes,
    backlinks, search) shares one fingerprint and never thrashes."""
    if not note_index.get_index().is_built():
        scan_notes_fast_walk(notes_dir, use_cache=False, include_media=True)


def get_tags_and_links_cached(
    file_path: Path,
    rel_path: Optional[str] = None,
) -> Tuple[List[str], Dict[str, List[str]]]:
    """Fused tags + raw-links extraction, mtime-cached. Tries in-process
    per-file caches first, then the NoteIndex (when rel_path is provided),
    then reads the file."""
    try:
        mtime = file_path.stat().st_mtime
        file_key = str(file_path)

        tag_cached = _tag_cache.get(file_key)
        link_cached = _links_cache.get(file_key)
        tags_ok = tag_cached is not None and tag_cached[0] == mtime
        links_ok = link_cached is not None and link_cached[0] == mtime

        if tags_ok and links_ok:
            return tag_cached[1], link_cached[1]

        if rel_path is not None:
            indexed = note_index.try_get_extraction(rel_path, mtime)
            if indexed is not None:
                idx_tags, idx_links = indexed
                _tag_cache[file_key] = (mtime, idx_tags)
                _links_cache[file_key] = (mtime, idx_links)
                return idx_tags, idx_links

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        tags = tag_cached[1] if tags_ok else parse_tags(content)
        links = link_cached[1] if links_ok else extract_links_from_content(content)

        if not tags_ok:
            _tag_cache[file_key] = (mtime, tags)
        if not links_ok:
            _links_cache[file_key] = (mtime, links)

        return tags, links
    except Exception:
        return [], {"wikilinks": [], "mdlinks": []}


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


def resolve_vault_folder(notes_dir: str, folder_path: str) -> Optional[Path]:
    """Absolute path of a folder inside the vault, or None if it is not usable.

    An empty ``folder_path`` is the vault root. Rejects anything that escapes the
    vault, does not exist, is not a directory, or is a symlink — a link could
    point anywhere, and following one would put files from outside the vault into
    an export.

    Dot-directories are refused as well, so asking for ``.git`` by name cannot do
    what walking into it already cannot. That also covers ``..`` and ``.``.
    """
    if any(part.startswith('.') for part in Path(folder_path).parts):
        return None

    target = Path(notes_dir) if not folder_path else Path(notes_dir) / folder_path
    if not validate_path_security(notes_dir, target):
        return None
    if target.is_symlink() or not target.is_dir():
        return None
    return target


def collect_folder_files(notes_dir: str, folder: Path) -> Tuple[List[Tuple[Path, str]], int]:
    """Every file under ``folder``, paired with its path relative to it, plus total bytes.

    The vault on disk is the source of truth, so note content is never parsed:
    whatever is in the folder comes out, attachments and unreferenced files
    included. Nothing is added from outside, so a note linking to media in
    another folder exports without it.

    Skipped: symlinks, and dot-files and dot-directories, which is where editor
    and tooling state lives (``.git``, ``.obsidian``) rather than anyone's notes.
    """
    collected: List[Tuple[Path, str]] = []
    total_bytes = 0

    for root, dirnames, filenames in os.walk(folder):
        root_path = Path(root)
        # Pruned in place so os.walk does not descend into them at all.
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith('.') and not (root_path / d).is_symlink()
        )

        for filename in sorted(filenames):
            if filename.startswith('.'):
                continue
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            # Belt and braces: the walk starts inside the vault and skips links,
            # so this should always hold. It is cheap, and the alternative to
            # checking is shipping a file we cannot account for.
            if not validate_path_security(notes_dir, file_path):
                continue
            try:
                total_bytes += file_path.stat().st_size
            except OSError:
                continue
            collected.append((file_path, str(file_path.relative_to(folder)).replace(os.sep, '/')))

    return collected, total_bytes


def ensure_directories(config: dict):
    """Create necessary directories if they don't exist"""
    dirs = [
        config['storage']['notes_dir'],
        config['storage']['plugins_dir'],
    ]
    
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)


def create_folder(notes_dir: str, folder_path: str) -> bool:
    """Create a new folder in the notes directory."""
    full_path = Path(notes_dir) / folder_path
    if not validate_path_security(notes_dir, full_path):
        return False
    full_path.mkdir(parents=True, exist_ok=True)
    _scan_cache_invalidate()
    return True


def scan_notes_fast_walk(notes_dir: str, use_cache: bool = True, include_media: bool = False) -> Tuple[List[Dict], List[str]]:
    """Fast scanner using os.walk (pure Python + stdlib).

    Args:
        notes_dir: Base notes directory
    """
    notes_path = Path(notes_dir)

    cache_key = (str(notes_path.resolve()), include_media)
    if use_cache:
        cached = _scan_cache_get(cache_key)
        if cached is not None:
            return cached

        if not include_media:
            media_cache_key = (str(notes_path.resolve()), True)
            media_cached = _scan_cache_get(media_cache_key)
            if media_cached is not None:
                media_notes, media_folders = media_cached
                normalized_notes = []
                for note in media_notes:
                    if not Path(note.get("path", "")).match("*.md"):
                        continue
                    normalized_note = dict(note)
                    normalized_note["type"] = "note"
                    normalized_notes.append(normalized_note)

                normalized_value = (normalized_notes, media_folders)
                _scan_cache_set(cache_key, normalized_value)
                return normalized_value

    # Walk the vault once. Tag/link extraction is parallelized below across
    # the markdown files we collected here.
    notes: List[Dict] = []
    folders_set = set()
    md_to_extract: List[Tuple[int, Path, str]] = []  # (index, full_path, rel_path)

    for root, dirnames, filenames in os.walk(notes_path):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]

        root_path = Path(root)
        rel_folder = root_path.relative_to(notes_path).as_posix()
        if rel_folder != "." and not rel_folder.startswith('.'):
            folders_set.add(rel_folder)

        for filename in filenames:
            if filename.startswith('.'):
                continue

            full_path = root_path / filename
            try:
                st = full_path.stat()
            except OSError:
                continue

            relative_path = full_path.relative_to(notes_path)
            media_type = get_media_type(filename) if include_media else None
            is_markdown = full_path.suffix.lower() == '.md'
            should_include = is_markdown or (include_media and media_type is not None)
            if not should_include:
                continue

            folder = relative_path.parent.as_posix()
            rel_str = relative_path.as_posix()
            notes.append({
                "name": full_path.stem,
                "path": rel_str,
                "folder": "" if folder == "." else folder,
                "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "size": st.st_size,
                "type": media_type if media_type else "note",
                "tags": [],
                "_mtime": st.st_mtime,  # internal — popped before returning
            })
            if is_markdown:
                md_to_extract.append((len(notes) - 1, full_path, rel_str))

    # Tag + raw-link extraction in parallel. Search-index terms are built
    # later, lazily, on the first /api/search call.
    sources_raw: Dict[str, Dict[str, List[str]]] = {}
    if md_to_extract:
        path_pairs = [(full, rel) for (_, full, rel) in md_to_extract]
        if len(md_to_extract) >= 50:
            workers = min(8, (os.cpu_count() or 4))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                extraction = list(ex.map(
                    lambda pair: get_tags_and_links_cached(pair[0], pair[1]),
                    path_pairs,
                ))
        else:
            extraction = [get_tags_and_links_cached(full, rel) for (full, rel) in path_pairs]

        for (idx, _full, rel_str), (tags, links) in zip(md_to_extract, extraction):
            notes[idx]["tags"] = tags
            sources_raw[rel_str] = links

    # Push the result into the NoteIndex. Short-circuits on warm scans.
    notes_meta = [
        NoteRecord(
            path=n["path"],
            name=n["name"],
            folder=n["folder"],
            modified=n["modified"],
            size=n["size"],
            type=n["type"],
            mtime=n["_mtime"],
            tags=tuple(n["tags"]),
        )
        for n in notes
    ]
    note_index.populate_from_scan(notes_meta, folders_set, sources_raw)

    for n in notes:
        n.pop("_mtime", None)

    value = (sorted(notes, key=lambda x: x.get('modified', ''), reverse=True), sorted(folders_set))
    if use_cache:
        _scan_cache_set(cache_key, value)
    return value

def move_note(notes_dir: str, old_path: str, new_path: str) -> tuple[bool, str]:
    """Move a note. Returns (success, error_message)."""
    old_full_path = Path(notes_dir) / old_path
    new_full_path = Path(notes_dir) / new_path

    if not validate_path_security(notes_dir, old_full_path):
        return False, "Invalid source path"
    if not validate_path_security(notes_dir, new_full_path):
        return False, "Invalid destination path"
    if not old_full_path.exists():
        return False, f"Source note does not exist: {old_path}"
    if new_full_path.exists():
        return False, f"A note already exists at: {new_path}"
    conflict = note_name_conflict(notes_dir, new_path)
    if conflict and _normalized_rel_path(conflict).lower() != _normalized_rel_path(old_path).lower():
        return False, f"A note already exists at: {conflict}"

    _drop_path_caches(old_full_path)

    try:
        new_full_path.parent.mkdir(parents=True, exist_ok=True)
        old_full_path.rename(new_full_path)
    except Exception as e:
        return False, f"Failed to move file: {str(e)}"

    note_index.on_note_renamed(notes_dir, old_full_path, new_full_path)
    _scan_cache_invalidate()
    return True, ""


def move_folder(notes_dir: str, old_path: str, new_path: str) -> tuple[bool, str]:
    """Move a folder. Returns (success, error_message)."""
    old_full_path = Path(notes_dir) / old_path
    new_full_path = Path(notes_dir) / new_path

    if not validate_path_security(notes_dir, old_full_path):
        return False, "Invalid source path"
    if not validate_path_security(notes_dir, new_full_path):
        return False, "Invalid destination path"
    if not old_full_path.exists() or not old_full_path.is_dir():
        return False, f"Source folder does not exist: {old_path}"
    if new_full_path.exists():
        return False, f"A folder already exists at: {new_path}"
    conflict = folder_name_conflict(notes_dir, new_path)
    if conflict and _normalized_rel_path(conflict).lower() != _normalized_rel_path(old_path).lower():
        return False, f"A folder already exists at: {conflict}"

    _drop_prefix_caches(old_full_path)

    try:
        new_full_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_full_path), str(new_full_path))
    except Exception as e:
        return False, f"Failed to move folder: {str(e)}"

    note_index.on_folder_renamed(notes_dir, old_full_path, new_full_path)
    _scan_cache_invalidate()
    return True, ""


def rename_folder(notes_dir: str, old_path: str, new_path: str) -> tuple[bool, str]:
    """Rename a folder (same as move, named for clarity)."""
    return move_folder(notes_dir, old_path, new_path)


def delete_folder(notes_dir: str, folder_path: str) -> bool:
    """Delete a folder and all its contents."""
    try:
        full_path = Path(notes_dir) / folder_path

        if not validate_path_security(notes_dir, full_path):
            logger.warning("Security: Path is outside notes directory: %s", full_path)
            return False
        if not full_path.exists():
            logger.warning("Folder does not exist: %s", full_path)
            return False
        if not full_path.is_dir():
            logger.warning("Path is not a directory: %s", full_path)
            return False

        _drop_prefix_caches(full_path)
        shutil.rmtree(full_path)
        note_index.on_folder_deleted(notes_dir, full_path)
        _scan_cache_invalidate()
        return True
    except Exception as e:
        logger.error("Error deleting folder '%s': %s", folder_path, e)
        logger.error(traceback.format_exc())
        return False


def _drop_path_caches(full_path: Path) -> None:
    """Evict the per-file mtime caches for a single note."""
    key = str(full_path)
    _tag_cache.pop(key, None)
    _links_cache.pop(key, None)


def _drop_prefix_caches(folder_full_path: Path) -> None:
    """Evict per-file mtime caches for every entry under a folder."""
    prefix = str(folder_full_path)
    for k in [k for k in _tag_cache if k.startswith(prefix)]:
        _tag_cache.pop(k, None)
    for k in [k for k in _links_cache if k.startswith(prefix)]:
        _links_cache.pop(k, None)




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


def _normalized_rel_path(path: str) -> str:
    return path.replace('\\', '/').strip('/')


def _directory_entries(parent: Path):
    try:
        return list(parent.iterdir())
    except OSError:
        return []


def _matching_child(parent: Path, name: str, *, want_dir: bool) -> Optional[str]:
    """On-disk name of the child `name` refers to.

    An exact name wins. Otherwise a sibling that differs only by case, when it
    is the same kind of entry (file or directory). Symlinks are ignored.
    Returns None when nothing in the directory matches.
    """
    if not parent.is_dir():
        return None
    folded = name.lower()
    fallback = None
    for entry in _directory_entries(parent):
        try:
            if entry.is_symlink():
                continue
            if want_dir != entry.is_dir():
                continue
        except OSError:
            continue
        if entry.name == name:
            return entry.name
        if entry.name.lower() == folded:
            fallback = entry.name
    return fallback


def _resolve_existing_dir(root: Path, rel_dir: str) -> Optional[Path]:
    """Walk `rel_dir` from `root`, following a case-only match. None if a segment is missing."""
    current = root
    if not rel_dir:
        return current
    for part in rel_dir.split('/'):
        if not part or part == '.':
            continue
        match = _matching_child(current, part, want_dir=True)
        if match is None:
            return None
        current = current / match
    return current


def note_name_conflict(notes_dir: str, note_path: str) -> Optional[str]:
    """Existing note path that this path would hit, when the names differ by case.

    An exact on-disk name is not a conflict: that write is an update of the same
    note. A missing parent is not a conflict either. The path must stay inside
    the notes directory.
    """
    normalized = _normalized_rel_path(note_path)
    if not normalized.lower().endswith('.md'):
        normalized += '.md'
    full = Path(notes_dir) / normalized
    if not validate_path_security(notes_dir, full):
        return None
    parent_rel, _, name = normalized.rpartition('/')
    parent = _resolve_existing_dir(Path(notes_dir), parent_rel)
    if parent is None:
        return None
    match = _matching_child(parent, name, want_dir=False)
    if match is None or match == name:
        return None
    try:
        real_parent = parent.relative_to(Path(notes_dir)).as_posix()
    except ValueError:
        real_parent = parent_rel
    if real_parent == '.':
        real_parent = ''
    return f'{real_parent}/{match}' if real_parent else match


def folder_name_conflict(notes_dir: str, folder_path: str) -> Optional[str]:
    """Existing folder path that differs from `folder_path` only by case, or None."""
    normalized = _normalized_rel_path(folder_path)
    if not normalized:
        return None
    full = Path(notes_dir) / normalized
    if not validate_path_security(notes_dir, full):
        return None
    root = Path(notes_dir)
    current = root
    resolved: list[str] = []
    for part in normalized.split('/'):
        match = _matching_child(current, part, want_dir=True)
        if match is None:
            return None
        resolved.append(match)
        current = current / match
        if match != part:
            return '/'.join(resolved)
    return None


def path_has_hash(path: str) -> bool:
    """True when a note or folder name uses `#`, which heading links already own."""
    return any('#' in part for part in _normalized_rel_path(path).split('/') if part)


def note_exists_exact(notes_dir: str, note_path: str) -> bool:
    """True when a note is stored under this exact path, not merely a different case."""
    normalized = _normalized_rel_path(note_path)
    if not normalized.lower().endswith('.md'):
        normalized += '.md'
    full = Path(notes_dir) / normalized
    if not validate_path_security(notes_dir, full):
        return False
    parent_rel, _, name = normalized.rpartition('/')
    parent = _resolve_existing_dir(Path(notes_dir), parent_rel)
    if parent is None:
        return False
    return _matching_child(parent, name, want_dir=False) == name


def folder_exists_exact(notes_dir: str, folder_path: str) -> bool:
    """True when every segment of the folder path matches a directory name exactly."""
    normalized = _normalized_rel_path(folder_path)
    if not normalized:
        return False
    full = Path(notes_dir) / normalized
    if not validate_path_security(notes_dir, full):
        return False
    current = Path(notes_dir)
    for part in normalized.split('/'):
        match = _matching_child(current, part, want_dir=True)
        if match != part:
            return False
        current = current / match
    return True


def save_note(notes_dir: str, note_path: str, content: str) -> bool:
    """Save or update a note."""
    full_path = Path(notes_dir) / note_path
    if not note_path.endswith('.md'):
        full_path = full_path.with_suffix('.md')

    if not validate_path_security(notes_dir, full_path):
        return False

    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # Refresh the per-file mtime caches with what we just wrote, so the next
    # scan doesn't re-parse this file. extract_links + parse_tags + save are
    # tiny relative to the file write.
    try:
        mtime = full_path.stat().st_mtime
        file_key = str(full_path)
        _tag_cache[file_key] = (mtime, parse_tags(content))
        _links_cache[file_key] = (mtime, extract_links_from_content(content))
    except Exception:
        pass  # caches are best-effort

    note_index.on_note_saved(notes_dir, full_path, content)
    _scan_cache_invalidate()
    return True


def delete_note(notes_dir: str, note_path: str) -> bool:
    """Delete a note."""
    full_path = Path(notes_dir) / note_path
    if not full_path.exists():
        return False
    if not validate_path_security(notes_dir, full_path):
        return False

    _drop_path_caches(full_path)
    full_path.unlink()
    note_index.on_note_deleted(notes_dir, full_path)
    _scan_cache_invalidate()
    return True


@lru_cache(maxsize=4096)
def _fold_char(ch: str) -> str:
    return note_index.fold_for_search(ch)


def _folded_match_spans(content: str, folded_query: str, limit: int) -> List[Tuple[int, int]]:
    """Find folded_query in the folded content and return up to `limit`
    (start, end) spans in the original content, so snippets keep the text as
    written, accents included.

    Folding can change the length of the text ("é" may be stored as "e" plus a
    combining accent), so each folded character remembers which original
    character it came from."""
    if content.isascii():
        # casefold() and lower() agree on ASCII, and the length stays the same
        folded, origin = content.lower(), None
    else:
        parts: List[str] = []
        origin = []
        for i, ch in enumerate(content):
            folded_ch = _fold_char(ch)
            parts.append(folded_ch)
            origin.extend([i] * len(folded_ch))
        folded = "".join(parts)

    spans: List[Tuple[int, int]] = []
    pos = folded.find(folded_query)
    while pos != -1 and len(spans) < limit:
        end = pos + len(folded_query)
        if origin is None:
            spans.append((pos, end))
        else:
            start, stop = origin[pos], origin[end - 1] + 1
            # Keep a combining accent with the letter it belongs to
            while stop < len(content) and unicodedata.combining(content[stop]):
                stop += 1
            spans.append((start, stop))
        pos = folded.find(folded_query, end)
    return spans


def search_notes(notes_dir: str, query: str) -> List[Dict]:
    """Full-text search through note contents. Narrow the candidate set via
    the inverted index, then run the snippet extractor on each candidate.
    Matching ignores case and accents: "esparragos" finds "Espárragos"."""
    from html import escape
    results: List[Dict] = []

    folded_query = note_index.fold_for_search(query)
    if not folded_query:
        return results

    ensure_index_built(notes_dir)
    note_index.ensure_search_index(notes_dir)
    candidates = note_index.get_search_candidates(query)

    idx = note_index.get_index()
    if candidates is None:
        # Nothing in the query is indexable, "???" for instance — the index
        # can't narrow it, so iterate every note.
        candidate_records = idx.all_note_records()
    else:
        candidate_records = [(p, idx.get_note_record(p)) for p in candidates]
        candidate_records = [(p, r) for (p, r) in candidate_records if r is not None and r.type == "note"]

    candidate_records.sort(key=lambda pr: pr[1].mtime, reverse=True)
    iterable = [{"path": p, "name": r.name} for (p, r) in candidate_records]

    for note in iterable:
        path = note["path"]
        md_file = Path(notes_dir) / path
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()

            spans = _folded_match_spans(content, folded_query, 3)
            if not spans:
                continue

            matched_lines = []
            for start_index, end_index in spans:
                matched_text = content[start_index:end_index]

                context_start = max(0, start_index - 15)
                context_end = min(len(content), end_index + 15)

                before = escape(content[context_start:start_index].replace('\n', ' '))
                after = escape(content[end_index:context_end].replace('\n', ' '))
                matched_clean = escape(matched_text.replace('\n', ' '))

                snippet = f'{before}<mark class="search-highlight">{matched_clean}</mark>{after}'
                if context_start > 0:
                    snippet = '...' + snippet
                if context_end < len(content):
                    snippet = snippet + '...'

                line_number = content.count('\n', 0, start_index) + 1
                matched_lines.append({
                    "line_number": line_number,
                    "context": snippet,
                })

            relative_path = Path(path)
            results.append({
                "name": md_file.stem,
                "path": str(relative_path.as_posix()),
                "folder": str(relative_path.parent.as_posix()) if str(relative_path.parent) != "." else "",
                "matches": matched_lines,
            })
        except Exception:
            continue

    return results


def create_note_metadata(notes_dir: str, note_path: str) -> Dict:
    """Get metadata for a note"""
    full_path = Path(notes_dir) / note_path
    
    if not full_path.exists() or not full_path.is_file():
        return {}
    
    # Security check: ensure the path is within notes_dir (same as get_note_content)
    if not validate_path_security(notes_dir, full_path):
        return {}
    
    stat = full_path.stat()
    
    # Count lines with proper file handle management
    with open(full_path, 'r', encoding='utf-8') as f:
        line_count = sum(1 for _ in f)
    
    return {
        "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size": stat.st_size,
        "lines": line_count
    }


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing/replacing dangerous filesystem characters.
    Supports Unicode characters (international text) while blocking:
    - Windows forbidden: \\ / : * ? " < > |
    - Control characters (0x00-0x1f)
    
    Note: This is a safety net - the frontend validates before sending.
    """
    if not filename:
        return filename
        
    # Get the extension first
    parts = filename.rsplit('.', 1)
    name = parts[0]
    ext = parts[1] if len(parts) > 1 else ''
    
    # Remove dangerous characters (replace with underscore)
    # Blocklist approach: only remove what's truly dangerous
    # Pattern: backslash, forward slash, colon, asterisk, question mark, quotes, angle brackets, pipe, control chars
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name)
    
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    
    # Strip leading/trailing underscores and spaces
    name = name.strip('_ ')
    
    # Ensure we have something left
    if not name:
        name = 'unnamed'
    
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


def save_uploaded_image(
    notes_dir: str,
    note_path: str,
    filename: str,
    file_data: bytes,
    *,
    sibling_folder: Optional[str] = None,
) -> Optional[str]:
    """
    Save uploaded media under the vault.

    Default (sibling_folder is None): store in ``_attachments`` next to the note implied by
    ``note_path`` (drag/drop, paste, etc.).

    If ``sibling_folder`` is set (including ``""`` for vault root): store ``drawing-{timestamp}.png``
    in that folder next to ``.md`` files — used for new drawings from the + menu.

    Returns a relative path from ``notes_dir``, or None on failure.
    """
    base = Path(notes_dir)

    if sibling_folder is not None:
        cf = (sibling_folder or "").strip().replace("\\", "/")
        segments = [p for p in cf.split("/") if p and p != "."]
        if any(p == ".." for p in segments):
            return None
        dest_dir = base.joinpath(*segments) if segments else base
        if not validate_path_security(notes_dir, dest_dir / ".nd_probe"):
            return None
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        full_path = dest_dir / f"drawing-{timestamp}.png"
        if not validate_path_security(notes_dir, full_path):
            return None
        try:
            with open(full_path, "wb") as f:
                f.write(file_data)
            _scan_cache_invalidate()
            return str(full_path.relative_to(base).as_posix())
        except OSError as e:
            logger.error("Error saving image: %s", e)
            return None

    sanitized_name = sanitize_filename(filename)
    ext = Path(sanitized_name).suffix
    name_without_ext = Path(sanitized_name).stem
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    final_filename = f"{name_without_ext}-{timestamp}{ext}"
    attachments_dir = get_attachment_dir(notes_dir, note_path)
    attachments_dir.mkdir(parents=True, exist_ok=True)
    full_path = attachments_dir / final_filename
    if not validate_path_security(notes_dir, full_path):
        logger.warning("Security: Attempted to save image outside notes directory: %s", full_path)
        return None
    try:
        with open(full_path, "wb") as f:
            f.write(file_data)
        _scan_cache_invalidate()
        return str(full_path.relative_to(base).as_posix())
    except OSError as e:
        logger.error("Error saving image: %s", e)
        return None


# Media file type definitions
MEDIA_EXTENSIONS = {
    'image': {'.jpg', '.jpeg', '.png', '.gif', '.webp'},
    'audio': {'.mp3', '.wav', '.ogg', '.m4a'},
    'video': {'.mp4', '.webm', '.mov', '.avi'},
    'document': {'.pdf'},
}

# All supported media extensions (flat set for quick lookup)
ALL_MEDIA_EXTENSIONS = set().union(*MEDIA_EXTENSIONS.values())


def get_media_type(filename: str) -> Optional[str]:
    """
    Determine the media type based on file extension.
    Returns: 'image', 'audio', 'video', 'document', 'drawing', or None if not a media file.

    Drawings are PNG files stored like images but named drawing-*.png (editable canvas in the app).
    """
    name_lower = Path(filename).name.lower()
    if name_lower.startswith('drawing-') and name_lower.endswith('.png'):
        return 'drawing'
    ext = Path(filename).suffix.lower()
    for media_type, extensions in MEDIA_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return None


def parse_tags(content: str) -> List[str]:
    """
    Extract tags from YAML frontmatter in markdown content.
    
    Supported formats:
    ---
    tags: [python, tutorial, backend]
    ---
    
    or
    
    ---
    tags:
      - python
      - tutorial
      - backend
    ---
    
    Args:
        content: Markdown content with optional YAML frontmatter
        
    Returns:
        List of tag strings (lowercase, no duplicates)
    """
    tags = []
    
    # Check if content starts with frontmatter
    if not content.strip().startswith('---'):
        return tags
    
    try:
        # Extract frontmatter (between first two --- markers)
        lines = content.split('\n')
        if lines[0].strip() != '---':
            return tags
        
        # Find closing ---
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                end_idx = i
                break
        
        if end_idx is None:
            return tags
        
        frontmatter_lines = lines[1:end_idx]
        
        # Parse tags field
        in_tags_list = False
        for line in frontmatter_lines:
            stripped = line.strip()
            
            # Check for inline array format: tags: [tag1, tag2, tag3]
            if stripped.startswith('tags:'):
                rest = stripped[5:].strip()
                if rest.startswith('[') and rest.endswith(']'):
                    # Parse inline array
                    tags_str = rest[1:-1]  # Remove [ and ]
                    raw_tags = [t.strip() for t in tags_str.split(',')]
                    tags.extend([t.lower() for t in raw_tags if t])
                    break
                elif rest:
                    # Single tag without brackets
                    tags.append(rest.lower())
                    break
                else:
                    # Multi-line list format
                    in_tags_list = True
            elif in_tags_list:
                if stripped.startswith('-'):
                    # List item
                    tag = stripped[1:].strip()
                    if tag:
                        tags.append(tag.lower())
                elif stripped and not stripped.startswith('#'):
                    # End of tags list
                    break
        
        # Remove duplicates and return
        return sorted(list(set(tags)))
        
    except Exception as e:
        logger.error("Error parsing tags: %s", e)
        return []


def get_all_tags(notes_dir: str) -> Dict[str, int]:
    """All tags in the vault with note counts."""
    ensure_index_built(notes_dir)
    return note_index.get_all_tags()


def get_notes_by_tag(notes_dir: str, tag: str) -> List[Dict]:
    """All notes carrying `tag` (case-insensitive)."""
    ensure_index_built(notes_dir)
    idx = note_index.get_index()
    records = [idx.get_note_record(p) for p in note_index.get_paths_for_tag(tag.lower())]
    matching = [
        {
            "name": r.name,
            "path": r.path,
            "folder": r.folder,
            "modified": r.modified,
            "size": r.size,
            "tags": list(r.tags),
        }
        for r in records
        if r is not None and r.type == "note"
    ]
    matching.sort(key=lambda n: n["modified"], reverse=True)
    return matching


# ============================================================================
# Template Functions
# ============================================================================

def get_templates(notes_dir: str) -> List[Dict]:
    """
    Get all templates from the _templates folder.
    
    Args:
        notes_dir: Base notes directory
        
    Returns:
        List of template metadata (name, path, modified)
    """
    templates = []
    templates_path = Path(notes_dir) / "_templates"
    
    if not templates_path.exists():
        return templates
    
    # Security check: ensure _templates folder is within notes directory
    if not validate_path_security(notes_dir, templates_path):
        logger.warning("Security: Templates directory is outside notes directory: %s", templates_path)
        return templates
    
    try:
        for template_file in templates_path.glob("*.md"):
            try:
                if not validate_path_security(notes_dir, template_file):
                    logger.warning("Security: Skipping template outside notes directory: %s", template_file)
                    continue
                
                stat = template_file.stat()
                templates.append({
                    "name": template_file.stem,
                    "path": str(template_file.relative_to(notes_dir).as_posix()),
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                })
            except Exception as e:
                logger.error("Error reading template %s: %s", template_file, e)
                continue
    except Exception as e:
        logger.error("Error accessing templates directory: %s", e)
    
    return sorted(templates, key=lambda x: x['name'])


def get_template_content(notes_dir: str, template_name: str) -> Optional[str]:
    """
    Get the content of a specific template.
    
    Args:
        notes_dir: Base notes directory
        template_name: Name of the template (without .md extension)
        
    Returns:
        Template content or None if not found
    """
    template_path = Path(notes_dir) / "_templates" / f"{template_name}.md"
    
    if not template_path.exists():
        return None
    
    # Security check: ensure template is within notes directory
    if not validate_path_security(notes_dir, template_path):
        logger.warning("Security: Template path is outside notes directory: %s", template_path)
        return None
    
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error("Error reading template %s: %s", template_name, e)
        return None


# Matches custom strftime placeholders like {{date:%Y%m%d}} or {{time:%H%M%S}}.
# The three prefixes mirror the bare {{date}}, {{time}}, {{datetime}} placeholders;
# disallowing '{' and '}' inside the format keeps parsing unambiguous and
# guarantees we never swallow an adjacent placeholder.
_STRFTIME_PLACEHOLDER_RE = re.compile(r'\{\{(date|time|datetime):([^{}]+)\}\}')


def apply_template_placeholders(content: str, note_path: str) -> str:
    """
    Replace template placeholders with actual values.

    Built-in named placeholders (fixed default formats):
        {{date}}       - Current date (YYYY-MM-DD)
        {{time}}       - Current time (HH:MM:SS)
        {{datetime}}   - Current datetime (YYYY-MM-DD HH:MM:SS)
        {{timestamp}}  - Unix timestamp (seconds)
        {{year}}       - Current year (YYYY)
        {{month}}      - Current month (MM)
        {{day}}        - Current day (DD)
        {{title}}      - Note name without extension
        {{folder}}     - Parent folder name

    Custom date/time formats (strftime escape hatch):
        {{date:FMT}}, {{time:FMT}}, {{datetime:FMT}}

        Any of the three date/time placeholders above also accepts an
        optional ":FMT" suffix where FMT is a Python strftime() format
        string. Pick the prefix whose default format covers the same
        components you want to format. Examples:

            {{datetime:%Y%m%d%H%M%S}}  -> 20260506154200  (filename-safe stamp)
            {{date:%d/%m/%Y}}          -> 06/05/2026      (European date)
            {{date:%A}}                -> Wednesday       (full weekday name)
            {{time:%H%M%S}}            -> 154200          (compact time)
            {{date:%V}}                -> 19              (ISO week number)

        Invalid format strings are left in the output unchanged so a typo
        is visible rather than silently swallowed.

    Args:
        content: Template content with placeholders
        note_path: Path of the note being created

    Returns:
        Content with placeholders replaced
    """
    now = datetime.now()
    note = Path(note_path)

    def _strftime_sub(match: 're.Match[str]') -> str:
        fmt = match.group(2)
        try:
            return now.strftime(fmt)
        except (ValueError, TypeError):
            return match.group(0)

    content = _STRFTIME_PLACEHOLDER_RE.sub(_strftime_sub, content)

    replacements = {
        '{{date}}': now.strftime('%Y-%m-%d'),
        '{{time}}': now.strftime('%H:%M:%S'),
        '{{datetime}}': now.strftime('%Y-%m-%d %H:%M:%S'),
        '{{timestamp}}': str(int(now.timestamp())),
        '{{year}}': now.strftime('%Y'),
        '{{month}}': now.strftime('%m'),
        '{{day}}': now.strftime('%d'),
        '{{title}}': note.stem,
        '{{folder}}': note.parent.name if str(note.parent) != '.' else 'Root',
    }

    result = content
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    return result


def _extract_backlink_references(
    notes_dir: str,
    source_path: str,
    target_path: str,
    target_path_lower: str,
    target_path_no_ext_lower: str,
    wikilink_refs: set,
) -> List[Dict]:
    """Read one source file and pull line-level references that point to target.

    Same regex + resolution rules as the legacy get_backlinks loop body; just
    factored out so both the index-driven and the legacy code paths use the
    exact same context-extraction logic.
    """
    source_folder = str(Path(source_path).parent).replace('\\', '/')
    if source_folder == '.':
        source_folder = ''

    full_path = Path(notes_dir) / source_path
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return []

    lines = content.split('\n')
    found_links: List[Dict] = []

    for line_num, line in enumerate(lines, 1):
        for match in re.finditer(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line):
            link_target = match.group(1).strip().lower()
            link_target_no_ext = link_target.replace('.md', '')
            if link_target in wikilink_refs or link_target_no_ext in wikilink_refs:
                start = max(0, match.start() - 30)
                end = min(len(line), match.end() + 30)
                context = line[start:end]
                if start > 0:
                    context = '...' + context
                if end < len(line):
                    context = context + '...'
                found_links.append({
                    "line_number": line_num,
                    "context": context,
                    "type": "wikilink",
                })

        for match in re.finditer(r'\[([^\]]+)\]\((?!https?://|mailto:|#|data:)([^\)]+)\)', line):
            link_path = match.group(2).split('#')[0]
            if not link_path:
                continue
            link_path = urllib.parse.unquote(link_path)
            if link_path.startswith('./'):
                link_path = link_path[2:]
            link_path_with_md = link_path if link_path.endswith('.md') else link_path + '.md'

            resolved_path = None
            if source_folder and not link_path.startswith('/'):
                relative_path = f"{source_folder}/{link_path_with_md}"
                if relative_path.lower() == target_path_lower:
                    resolved_path = target_path
                elif f"{source_folder}/{link_path}".lower() == target_path_no_ext_lower:
                    resolved_path = target_path
            if not resolved_path:
                if link_path_with_md.lower() == target_path_lower:
                    resolved_path = target_path
                elif link_path.lower() == target_path_no_ext_lower:
                    resolved_path = target_path

            if resolved_path:
                start = max(0, match.start() - 30)
                end = min(len(line), match.end() + 30)
                context = line[start:end]
                if start > 0:
                    context = '...' + context
                if end < len(line):
                    context = context + '...'
                found_links.append({
                    "line_number": line_num,
                    "context": context,
                    "type": "markdown",
                })

    return found_links


def get_backlinks(notes_dir: str, target_note_path: str) -> List[Dict]:
    """All notes that link TO `target_note_path`. The index narrows the
    candidate set; we only read the candidate files for line context."""
    target_path = target_note_path
    target_path_lower = target_path.lower()
    target_path_no_ext_lower = target_path_lower.replace('.md', '')
    wikilink_refs = {
        target_path_lower,
        target_path_no_ext_lower,
        Path(target_path).stem.lower(),
    }

    ensure_index_built(notes_dir)
    idx = note_index.get_index()
    candidates = note_index.get_backlink_candidates(target_path)
    records = [(p, idx.get_note_record(p)) for p in candidates]
    records = [(p, r) for (p, r) in records if r is not None and r.type == "note" and p != target_path]
    records.sort(key=lambda pr: pr[1].mtime, reverse=True)

    backlinks: List[Dict] = []
    for source_path, record in records:
        refs = _extract_backlink_references(
            notes_dir,
            source_path,
            target_path,
            target_path_lower,
            target_path_no_ext_lower,
            wikilink_refs,
        )
        if refs:
            backlinks.append({
                "path": source_path,
                "name": record.name.replace('.md', ''),
                "references": refs[:3],
            })
    return backlinks

