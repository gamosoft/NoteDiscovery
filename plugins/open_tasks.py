"""
Open Tasks Plugin for NoteDiscovery

Turns the search box into a task inbox: searching for "@task" (or "@tasks")
replaces the normal full-text results with every note that still has an
unchecked checkbox, e.g.

    - [ ] Buy milk

How it works: `on_search` cannot return a new result set (PluginManager
discards the return value of void hooks), but `results` is the same list object
that /api/search paginates afterwards, so we replace its contents in place.

Ordering is not ours to pick — /api/search always re-sorts by path.
"""

import logging
import os
import re
from html import escape
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger("uvicorn.error")

# Search strings that switch the search into task mode (compared lowercased).
TRIGGERS = {"@task", "@tasks"}

# An unchecked GFM task item: "- [ ] label", "* [] label", "1. [ ] label".
# "[x]" / "[X]" deliberately do not match — those are done.
OPEN_TASK_RE = re.compile(r'^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[ ?\][ \t]*(.*)$')

# Snippets shown per note. Matches what search_notes() returns, and the sidebar
# only renders the first one anyway.
MAX_MATCHES_PER_NOTE = 1
MAX_LABEL_CHARS = 120
UNTITLED_TASK = "(untitled task)"

# Same markup search_notes() emits, so the theme highlights it identically.
# The label is escaped because the frontend renders context with x-html.
_MARKER = '<mark class="search-highlight">&#9744;</mark>'


def extract_open_tasks(content: str) -> Tuple[List[Dict], int]:
    """Return (snippets, total_open_count) for one note's content.

    Fenced code blocks are skipped so a checkbox inside a ``` example is not
    reported as a real task.
    """
    matches: List[Dict] = []
    count = 0
    in_fence = False

    for line_number, line in enumerate(content.split('\n'), start=1):
        stripped = line.lstrip()
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        match = OPEN_TASK_RE.match(line)
        if not match:
            continue

        count += 1
        if len(matches) < MAX_MATCHES_PER_NOTE:
            label = match.group(1).strip() or UNTITLED_TASK
            if len(label) > MAX_LABEL_CHARS:
                label = label[:MAX_LABEL_CHARS].rstrip() + '…'
            matches.append({
                "line_number": line_number,
                "context": f'{_MARKER} {escape(label)}',
            })

    return matches, count


class Plugin:
    def __init__(self):
        self.name = "Open Tasks"
        self.version = "1.0.0"
        self.enabled = True
        # full path -> (mtime, size, matches, open_count). Rebuilt every scan,
        # which also evicts notes that were deleted or moved.
        self._cache: Dict[str, Tuple[float, int, List[Dict], int]] = {}
        self._notes_dir: Path | None = None

    # ------------------------------------------------------------------
    # Hook
    # ------------------------------------------------------------------

    def on_search(self, query: str, results: list):
        """Replace results with the open-task list when the query is @task."""
        if query.strip().lower() not in TRIGGERS:
            return

        notes_dir = self._resolve_notes_dir()
        if not notes_dir.is_dir():
            logger.warning("open_tasks: notes directory not found: %s", notes_dir)
            return

        # Built fully before swapping, so a failure mid-scan leaves the original
        # results untouched rather than half-replaced.
        replacement = self._scan(notes_dir)
        results[:] = replacement
        logger.info(
            "open_tasks: '%s' -> %d note(s) with %d open task(s)",
            query, len(replacement), sum(r["open_tasks"] for r in replacement),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scan(self, notes_dir: Path) -> List[Dict]:
        """Walk the vault and collect notes that still have unchecked boxes.

        Skips hidden files and folders, mirroring scan_notes_fast_walk().
        """
        fresh: Dict[str, Tuple[float, int, List[Dict], int]] = {}
        found: List[Dict] = []

        for root, dirnames, filenames in os.walk(notes_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            root_path = Path(root)

            for filename in filenames:
                if filename.startswith('.') or not filename.lower().endswith('.md'):
                    continue

                full_path = root_path / filename
                try:
                    st = full_path.stat()
                except OSError:
                    continue

                key = str(full_path)
                cached = self._cache.get(key)
                if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                    matches, count = cached[2], cached[3]
                else:
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    except (OSError, UnicodeDecodeError):
                        continue
                    matches, count = extract_open_tasks(content)

                # Cached even at count 0, so task-free notes are read only once.
                fresh[key] = (st.st_mtime, st.st_size, matches, count)

                if count:
                    relative_path = full_path.relative_to(notes_dir)
                    parent = relative_path.parent.as_posix()
                    found.append({
                        "name": full_path.stem,
                        "path": relative_path.as_posix(),
                        "folder": "" if parent == "." else parent,
                        "matches": matches,
                        # Extra field: the true count even when snippets are capped.
                        # The web UI ignores it; API/MCP consumers can use it.
                        "open_tasks": count,
                    })

        self._cache = fresh
        return found

    def _resolve_notes_dir(self) -> Path:
        """Resolve the vault the same way backend/main.py does.

        NOTES_DIR env var > storage.notes_dir in config.yaml > ./data.
        Memoized: config.yaml is not re-read at runtime by the app either.
        """
        if self._notes_dir is not None:
            return self._notes_dir

        if 'NOTES_DIR' in os.environ:
            self._notes_dir = Path(os.environ['NOTES_DIR'])
            return self._notes_dir

        # cwd is the app root under both `python run.py` and Docker (WORKDIR
        # /app); the plugin-relative path is the fallback for an unusual layout.
        candidates = [
            Path.cwd() / "config.yaml",
            Path(__file__).resolve().parent.parent / "config.yaml",
        ]
        for config_path in candidates:
            try:
                if not config_path.is_file():
                    continue
                import yaml
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                notes_dir = (cfg.get('storage') or {}).get('notes_dir')
                if notes_dir:
                    self._notes_dir = Path(notes_dir)
                    return self._notes_dir
            except Exception as exc:
                logger.warning("open_tasks: could not read %s: %s", config_path, exc)

        self._notes_dir = Path("./data")
        return self._notes_dir
