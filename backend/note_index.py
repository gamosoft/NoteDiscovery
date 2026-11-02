"""
NoteIndex — in-memory index of vault state: notes, folders, tags, links, search.

Backs /api/notes, /api/tags, /api/backlinks, /api/graph, /api/search. Keeps
everything thread-safe under one RLock. Process-memory only — rebuilds on the
first /api/notes request after each process start (~1-3s on a 10K-note vault).

Updated incrementally on every save/delete/move/rename through the on_*
facades at the bottom of this file.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger("uvicorn.error")


# Below this many markdown files, parallel tag extraction adds more overhead
# than it saves.
_PARALLEL_CUTOFF = 50
_PARALLEL_WORKERS = min(8, (os.cpu_count() or 4))

# Search tokenization. Min length 2 keeps single-letter noise out without
# losing common short queries like "go", "ai". \w takes accented and other
# non-Latin letters as letters, so "espárragos" stays one word.
_SEARCH_TOKEN_RE = re.compile(r"[\w\-]{2,}")

WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')
MDLINK_RE = re.compile(r'\[([^\]]+)\]\((?!https?://|mailto:|#|data:)([^\)]+)\)')


def extract_links_from_content(content: str) -> Dict[str, List[str]]:
    """Pull raw wikilink targets and markdown-link paths out of note content."""
    wikilinks = [m.strip() for m in WIKILINK_RE.findall(content)]
    mdlinks = [link_path for _, link_path in MDLINK_RE.findall(content)]
    return {"wikilinks": wikilinks, "mdlinks": mdlinks}


def fold_for_search(text: str) -> str:
    """Lowercase and drop accents, so "Espárragos" and "esparragos" compare
    equal. The indexed words, the query and the final match all go through
    this, or a query typed without accents would miss on one side.

    casefold() rather than lower(): lower() depends on context (a Greek "Σ"
    becomes "ς" only at the end of a word), so folding a whole query and
    folding a note one character at a time would disagree."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def extract_search_terms(content: str) -> Set[str]:
    """Tokenize content for the inverted search index."""
    return {m.group(0) for m in _SEARCH_TOKEN_RE.finditer(fold_for_search(content))}


@dataclass
class NoteRecord:
    """One note's metadata. No content, no resolved links."""
    path: str                       # vault-relative POSIX
    name: str                       # stem (no extension)
    folder: str                     # vault-relative POSIX, "" for root
    modified: str                   # ISO timestamp
    size: int                       # bytes
    type: str                       # "note" | "image" | "audio" | ...
    mtime: float                    # raw stat mtime
    tags: Tuple[str, ...] = field(default_factory=tuple)


class NoteIndex:
    """Thread-safe in-memory index of vault state. Reads return copies so
    callers don't have to hold the lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

        self._notes: Dict[str, NoteRecord] = {}              # path -> record
        self._folders: Set[str] = set()

        self._tags_forward: Dict[str, Tuple[str, ...]] = {}  # path -> tags
        self._tags_backward: Dict[str, Set[str]] = {}        # tag -> paths

        self._raw_links: Dict[str, Dict[str, List[str]]] = {}  # path -> {"wikilinks":[], "mdlinks":[]}
        self._links_forward: Dict[str, Dict[str, str]] = {}    # src -> {tgt: type}
        self._links_backward: Dict[str, Set[str]] = {}         # tgt -> {srcs}
        self._wikilink_tokens: Dict[str, Set[str]] = {}        # lower token -> {srcs} (loose match)

        self._search_terms: Dict[str, Set[str]] = {}           # term -> {paths}

        # _search_built tracked separately — the search index is built lazily
        # on the first /api/search call, after the cheaper notes/tags/links
        # part is already built.
        self._built = False
        self._search_built = False
        self._raw_fingerprint: Optional[int] = None  # short-circuits no-op rebuilds

        self._stats = {
            "build_count": 0,
            "last_build_ms": 0.0,
            "last_built_at": None,
            "incremental_updates": 0,
            "fingerprint_short_circuits": 0,
            "search_build_count": 0,
            "last_search_build_ms": 0.0,
        }

    def is_built(self) -> bool:
        with self._lock:
            return self._built

    def invalidate(self) -> None:
        """Mark as needing rebuild on next scan."""
        with self._lock:
            self._built = False
            self._raw_fingerprint = None

    def reset(self) -> None:
        with self._lock:
            self._notes.clear()
            self._folders.clear()
            self._tags_forward.clear()
            self._tags_backward.clear()
            self._raw_links.clear()
            self._links_forward.clear()
            self._links_backward.clear()
            self._wikilink_tokens.clear()
            self._search_terms.clear()
            self._built = False
            self._search_built = False
            self._raw_fingerprint = None

    def is_search_built(self) -> bool:
        with self._lock:
            return self._search_built

    def ensure_search_index_built(self, notes_dir: str) -> bool:
        """Build the search index on demand. Returns True when ready, False
        only if the main index isn't built yet. File I/O happens OUTSIDE the
        lock so other reads aren't blocked."""
        if self._search_built:
            return True

        with self._lock:
            if self._search_built:
                return True
            if not self._built:
                return False
            paths_to_read = [p for p, r in self._notes.items() if r.type == "note"]

        t0 = time.perf_counter()
        base = Path(notes_dir)
        terms_per_path: Dict[str, Set[str]] = {}
        for rel in paths_to_read:
            try:
                with open(base / rel, "r", encoding="utf-8") as f:
                    terms_per_path[rel] = extract_search_terms(f.read())
            except Exception:
                terms_per_path[rel] = set()

        with self._lock:
            if self._search_built:
                return True
            self._search_terms.clear()
            for path, terms in terms_per_path.items():
                for term in terms:
                    self._search_terms.setdefault(term, set()).add(path)
            self._search_built = True
            self._stats["search_build_count"] += 1
            self._stats["last_search_build_ms"] = (time.perf_counter() - t0) * 1000
        return True

    def bulk_set(
        self,
        notes_meta: List[NoteRecord],
        folders: Iterable[str],
        sources_raw: Dict[str, Dict[str, List[str]]],
    ) -> None:
        """Replace the entire index from a fresh scan. Short-circuits when
        the input fingerprints to the same state we already hold (warm
        scan, nothing changed)."""
        new_fp = _fingerprint(notes_meta, sources_raw)
        with self._lock:
            if self._built and self._raw_fingerprint == new_fp:
                self._stats["fingerprint_short_circuits"] += 1
                return

            t0 = time.perf_counter()

            self._notes = {n.path: n for n in notes_meta}
            self._folders = set(folders)
            self._raw_links = {k: v for k, v in sources_raw.items()}

            self._rebuild_tags_unlocked()
            self._rebuild_links_unlocked()
            if self._search_built:
                self._prune_search_unlocked()

            self._raw_fingerprint = new_fp
            self._built = True

            elapsed = time.perf_counter() - t0
            self._stats["build_count"] += 1
            self._stats["last_build_ms"] = elapsed * 1000
            self._stats["last_built_at"] = datetime.now(tz=timezone.utc).isoformat()

        logger.info("Vault index rebuilt in %.2fs (%d notes)", elapsed, len(notes_meta))

    def update_note(
        self,
        record: NoteRecord,
        raw_links: Dict[str, List[str]],
        content: Optional[str] = None,
    ) -> None:
        """Patch the index in place after a note is created or saved."""
        with self._lock:
            old_record = self._notes.get(record.path)
            old_tags = old_record.tags if old_record else ()

            self._notes[record.path] = record
            if record.folder:
                self._folders.add(record.folder)

            new_tags = record.tags
            if old_tags != new_tags:
                for t in set(old_tags) - set(new_tags):
                    bucket = self._tags_backward.get(t)
                    if bucket is not None:
                        bucket.discard(record.path)
                        if not bucket:
                            del self._tags_backward[t]
                for t in set(new_tags) - set(old_tags):
                    self._tags_backward.setdefault(t, set()).add(record.path)
                self._tags_forward[record.path] = new_tags

            self._raw_links[record.path] = raw_links
            self._resolve_single_source_unlocked(record.path)

            # Search index only gets patched if it's already been built —
            # otherwise the first /api/search will build it from scratch.
            if content is not None and self._search_built:
                self._update_search_for_note_unlocked(record.path, content)

            self._raw_fingerprint = None
            self._stats["incremental_updates"] += 1

    def remove_note(self, path: str) -> None:
        """A note was deleted. Drop everything that mentions it."""
        with self._lock:
            old_record = self._notes.pop(path, None)
            if old_record is None:
                return

            # Tags
            for t in old_record.tags:
                bucket = self._tags_backward.get(t)
                if bucket is not None:
                    bucket.discard(path)
                    if not bucket:
                        del self._tags_backward[t]
            self._tags_forward.pop(path, None)

            # Links: drop as source.
            self._raw_links.pop(path, None)
            old_targets = self._links_forward.pop(path, {})
            for t in old_targets:
                bucket = self._links_backward.get(t)
                if bucket is not None:
                    bucket.discard(path)
                    if not bucket:
                        del self._links_backward[t]

            # Links: drop as loose wikilink source.
            empty_keys = []
            for key, sources in self._wikilink_tokens.items():
                sources.discard(path)
                if not sources:
                    empty_keys.append(key)
            for k in empty_keys:
                del self._wikilink_tokens[k]

            # Links: drop as target from every other source's forward dict.
            sources_pointing_here = self._links_backward.pop(path, set())
            for src in sources_pointing_here:
                fwd = self._links_forward.get(src)
                if fwd is not None and path in fwd:
                    del fwd[path]
                    if not fwd:
                        del self._links_forward[src]

            # Search: drop from every term bucket. Linear in distinct terms
            # this note contributed to, which is bounded by note size.
            empty_terms = []
            for term, paths in self._search_terms.items():
                if path in paths:
                    paths.discard(path)
                    if not paths:
                        empty_terms.append(term)
            for term in empty_terms:
                del self._search_terms[term]

            self._raw_fingerprint = None
            self._stats["incremental_updates"] += 1

    def rename_note(self, old_path: str, new_path: str) -> None:
        """Move all references from old_path to new_path. The path change can
        affect how other notes' wikilinks resolve, so we wipe the resolved
        link indexes for this note and rely on the next bulk_set to rebuild."""
        if old_path == new_path:
            return
        with self._lock:
            old_record = self._notes.pop(old_path, None)
            if old_record is None:
                return
            new_record = NoteRecord(
                path=new_path,
                name=Path(new_path).stem,
                folder=str(Path(new_path).parent).replace("\\", "/").lstrip(".").lstrip("/") or "",
                modified=old_record.modified,
                size=old_record.size,
                type=old_record.type,
                mtime=old_record.mtime,
                tags=old_record.tags,
            )
            # Re-derive folder cleanly (the above lstrip dance is brittle).
            folder = str(Path(new_path).parent).replace("\\", "/")
            new_record.folder = "" if folder == "." else folder
            self._notes[new_path] = new_record
            if new_record.folder:
                self._folders.add(new_record.folder)

            if old_path in self._tags_forward:
                tags = self._tags_forward.pop(old_path)
                self._tags_forward[new_path] = tags
                for t in tags:
                    bucket = self._tags_backward.get(t)
                    if bucket is not None:
                        bucket.discard(old_path)
                        bucket.add(new_path)

            for paths in self._search_terms.values():
                if old_path in paths:
                    paths.discard(old_path)
                    paths.add(new_path)

            if old_path in self._raw_links:
                self._raw_links[new_path] = self._raw_links.pop(old_path)

            # Other sources that linked to old_path by stem name may now
            # resolve to new_path (or not), so we wipe both forward & backward
            # for old_path and let the next bulk_set re-resolve from scratch.
            self._links_forward.pop(old_path, None)
            for bucket in self._links_backward.values():
                bucket.discard(old_path)
            old_backlinks = self._links_backward.pop(old_path, set())
            for src in old_backlinks:
                fwd = self._links_forward.get(src)
                if fwd is not None and old_path in fwd:
                    del fwd[old_path]
                    if not fwd:
                        del self._links_forward[src]

            empty_keys = []
            for key, sources in self._wikilink_tokens.items():
                if old_path in sources:
                    sources.discard(old_path)
                    sources.add(new_path)
                if not sources:
                    empty_keys.append(key)
            for k in empty_keys:
                del self._wikilink_tokens[k]

            self._raw_fingerprint = None
            self._built = False  # force re-resolve on next bulk_set
            self._stats["incremental_updates"] += 1

    def rename_folder_prefix(self, old_prefix: str, new_prefix: str) -> None:
        """Migrate every entry under `old_prefix/` to `new_prefix/`. Much
        cheaper than a full rebuild — microseconds of key swaps."""
        old_prefix = old_prefix.rstrip("/")
        new_prefix = new_prefix.rstrip("/")
        if old_prefix == new_prefix:
            return
        with self._lock:
            affected_paths = [p for p in self._notes if p == old_prefix or p.startswith(old_prefix + "/")]
            for old_path in affected_paths:
                suffix = old_path[len(old_prefix):]
                self._rename_note_unlocked(old_path, new_prefix + suffix)

            folders_to_rename = [
                f for f in self._folders if f == old_prefix or f.startswith(old_prefix + "/")
            ]
            for f in folders_to_rename:
                self._folders.discard(f)
                suffix = f[len(old_prefix):]
                self._folders.add(new_prefix + suffix)

            self._raw_fingerprint = None
            self._built = False

    def remove_folder_prefix(self, prefix: str) -> None:
        """Drop every entry under `prefix/`."""
        prefix = prefix.rstrip("/")
        with self._lock:
            affected = [p for p in self._notes if p == prefix or p.startswith(prefix + "/")]
            for path in affected:
                self._remove_note_unlocked(path)
            folders_to_drop = [
                f for f in self._folders if f == prefix or f.startswith(prefix + "/")
            ]
            for f in folders_to_drop:
                self._folders.discard(f)
            self._raw_fingerprint = None

    # ------------------------------------------------------------------
    # Read API — every method returns a snapshot copy
    # ------------------------------------------------------------------

    def get_backlink_candidate_sources(self, target_path: str) -> Set[str]:
        """Superset of true backlink sources. Combines strict resolved
        backward links with the loose wikilink-token reverse index. Caller
        runs the per-line matcher against each candidate to filter."""
        target_lower = target_path.lower()
        target_no_ext_lower = target_lower[:-3] if target_lower.endswith(".md") else target_lower
        target_name = Path(target_path).stem.lower()

        with self._lock:
            candidates: Set[str] = set(self._links_backward.get(target_path, set()))
            for key in (target_lower, target_no_ext_lower, target_name):
                candidates.update(self._wikilink_tokens.get(key, set()))
            candidates.discard(target_path)
            return candidates

    def get_graph_data(self) -> Tuple[List[str], List[Tuple[str, str, str]]]:
        """Snapshot of (sorted note paths, (source, target, type) edges)."""
        with self._lock:
            nodes = sorted(p for p, r in self._notes.items() if r.type == "note")
            edges: List[Tuple[str, str, str]] = []
            for src, targets in self._links_forward.items():
                for target, edge_type in targets.items():
                    edges.append((src, target, edge_type))
            return nodes, edges

    def get_all_tags(self) -> Dict[str, int]:
        """Snapshot {tag: count}, sorted by tag name."""
        with self._lock:
            return {tag: len(paths) for tag, paths in sorted(self._tags_backward.items())}

    def get_paths_for_tag(self, tag: str) -> Set[str]:
        """Snapshot set of paths tagged with `tag` (case-insensitive)."""
        with self._lock:
            return set(self._tags_backward.get(tag.lower(), set()))

    def get_note_record(self, path: str) -> Optional[NoteRecord]:
        with self._lock:
            return self._notes.get(path)

    def all_note_records(self) -> List[Tuple[str, NoteRecord]]:
        """Snapshot list of (path, record) for every indexed markdown note."""
        with self._lock:
            return [(p, r) for p, r in self._notes.items() if r.type == "note"]

    def try_get_extraction(
        self,
        rel_path: str,
        mtime: float,
    ) -> Optional[Tuple[List[str], Dict[str, List[str]]]]:
        """Return (tags, raw_links) from the index only if the recorded mtime
        matches `mtime` exactly. Lets scan_notes_fast_walk skip the per-file
        read on a warm scan."""
        with self._lock:
            rec = self._notes.get(rel_path)
            if rec is None or rec.mtime != mtime:
                return None
            raw = self._raw_links.get(rel_path)
            if raw is None:
                return None
            return (
                list(rec.tags),
                {
                    "wikilinks": list(raw.get("wikilinks", [])),
                    "mdlinks": list(raw.get("mdlinks", [])),
                },
            )

    def get_search_candidates(self, query: str) -> Optional[Set[str]]:
        """Superset of paths whose content COULD contain `query`. Caller
        still runs the substring match per candidate for confirmation +
        snippet extraction. Returns None when nothing in the query is
        indexable — caller should iterate every note instead.

        Single characters are skipped, not narrowed on: the index holds no term
        shorter than two, so "Z" in "Plan Z details" was never recorded and
        narrowing on it would rule out the very note that matches. A query of
        only such runs ("b c") has to fall back to reading the vault."""
        if not self._search_built:
            return None
        tokens = [m.group(0) for m in _SEARCH_TOKEN_RE.finditer(fold_for_search(query))]
        if not tokens:
            return None

        # The index stores whole words, but the caller confirms with a
        # substring match, so "feat" has to reach the notes holding
        # "features" — looking the token up as a key would drop them and the
        # search would find nothing. Every term is tested against every token
        # in a single pass instead. That costs a scan of the vocabulary, which
        # stays well under the cost of the file reads the caller then does.
        buckets: List[Set[str]] = [set() for _ in tokens]
        with self._lock:
            for term, term_paths in self._search_terms.items():
                for bucket, tok in zip(buckets, tokens):
                    if tok in term:
                        bucket |= term_paths

        result = buckets[0]
        for bucket in buckets[1:]:
            result &= bucket
            if not result:
                break
        return result

    def summary(self) -> Dict[str, Any]:
        """Aggregate counts + total size + last-modified note. Powers /api/stats
        without a vault scan — every field is computed from records already in
        memory."""
        with self._lock:
            notes_count = 0
            media_count = 0
            total_size = 0
            last_modified: Optional[str] = None
            last_mtime = -1.0
            for rec in self._notes.values():
                total_size += rec.size
                if rec.type == "note":
                    notes_count += 1
                    if rec.mtime > last_mtime:
                        last_mtime = rec.mtime
                        last_modified = rec.modified
                else:
                    media_count += 1
            return {
                "notes_count": notes_count,
                "media_count": media_count,
                "folders_count": len(self._folders),
                "tags_count": len(self._tags_backward),
                "total_size_bytes": total_size,
                "last_modified": last_modified,
            }

    def stats(self) -> Dict[str, Any]:
        """Snapshot of counters + size metrics."""
        with self._lock:
            return {
                "built": self._built,
                "search_built": self._search_built,
                "notes": len(self._notes),
                "folders": len(self._folders),
                "tags": len(self._tags_backward),
                "links_forward_entries": len(self._links_forward),
                "links_backward_entries": len(self._links_backward),
                "wikilink_tokens": len(self._wikilink_tokens),
                "search_terms": len(self._search_terms),
                "counters": dict(self._stats),
            }

    # ==================================================================
    # Internal — must hold _lock when called
    # ==================================================================

    def _rebuild_tags_unlocked(self) -> None:
        self._tags_forward.clear()
        self._tags_backward.clear()
        for path, record in self._notes.items():
            if record.type != "note":
                continue
            tags = record.tags
            if not tags:
                continue
            self._tags_forward[path] = tags
            for tag in tags:
                self._tags_backward.setdefault(tag, set()).add(path)

    def _rebuild_links_unlocked(self) -> None:
        """Full link re-resolution. Reuses one _Resolver across all sources
        (O(N+K*L) instead of O(N*K))."""
        self._links_forward.clear()
        self._links_backward.clear()
        self._wikilink_tokens.clear()
        note_paths = {p for p, r in self._notes.items() if r.type == "note"}
        resolver = _Resolver(note_paths)
        for source_path in self._raw_links:
            self._resolve_single_source_unlocked(source_path, resolver=resolver, skip_cleanup=True)

    def _prune_search_unlocked(self) -> None:
        """Drop search-term entries for paths no longer in the index."""
        live_paths = set(self._notes.keys())
        empty_terms = []
        for term, paths in self._search_terms.items():
            stale = paths - live_paths
            if stale:
                paths -= stale
                if not paths:
                    empty_terms.append(term)
        for term in empty_terms:
            del self._search_terms[term]

    def _update_search_for_note_unlocked(self, path: str, content: str) -> None:
        """Replace one note's terms in the inverted index."""
        empty_terms = []
        for term, paths in self._search_terms.items():
            if path in paths:
                paths.discard(path)
                if not paths:
                    empty_terms.append(term)
        for term in empty_terms:
            del self._search_terms[term]
        for term in extract_search_terms(content):
            self._search_terms.setdefault(term, set()).add(path)

    def _resolve_single_source_unlocked(
        self,
        source_path: str,
        resolver: Optional["_Resolver"] = None,
        skip_cleanup: bool = False,
    ) -> None:
        if not skip_cleanup:
            old_targets = self._links_forward.pop(source_path, {})
            for t in old_targets:
                bucket = self._links_backward.get(t)
                if bucket is not None:
                    bucket.discard(source_path)
                    if not bucket:
                        del self._links_backward[t]
            empty_keys = []
            for key, sources in self._wikilink_tokens.items():
                sources.discard(source_path)
                if not sources:
                    empty_keys.append(key)
            for k in empty_keys:
                del self._wikilink_tokens[k]

        raw = self._raw_links.get(source_path)
        if not raw:
            return

        if resolver is None:
            note_paths = {p for p, r in self._notes.items() if r.type == "note"}
            resolver = _Resolver(note_paths)

        source_folder = str(Path(source_path).parent).replace("\\", "/")
        if source_folder == ".":
            source_folder = ""

        targets: Dict[str, str] = {}

        # Wikilinks first (they win the "first wins" dedup that /api/graph uses).
        for target in raw.get("wikilinks", []):
            resolved = resolver.resolve_wikilink(target, source_folder)
            if resolved and resolved != source_path and resolved not in targets:
                targets[resolved] = "wikilink"
            # Loose token index — populated even when strict resolution fails,
            # because backlink matching uses stem comparison independently.
            t_lower = target.strip().lower()
            if t_lower:
                self._wikilink_tokens.setdefault(t_lower, set()).add(source_path)
                t_no_ext = t_lower[:-3] if t_lower.endswith(".md") else t_lower
                if t_no_ext != t_lower:
                    self._wikilink_tokens.setdefault(t_no_ext, set()).add(source_path)

        for link_path in raw.get("mdlinks", []):
            resolved = resolver.resolve_mdlink(link_path, source_folder)
            if resolved and resolved != source_path and resolved not in targets:
                targets[resolved] = "markdown"

        if targets:
            self._links_forward[source_path] = targets
            for t in targets:
                self._links_backward.setdefault(t, set()).add(source_path)

    def _rename_note_unlocked(self, old_path: str, new_path: str) -> None:
        """rename_note() body without acquiring the lock — used by
        rename_folder_prefix to avoid re-locking per file."""
        if old_path == new_path:
            return
        old_record = self._notes.pop(old_path, None)
        if old_record is None:
            return
        folder = str(Path(new_path).parent).replace("\\", "/")
        new_record = NoteRecord(
            path=new_path,
            name=Path(new_path).stem,
            folder="" if folder == "." else folder,
            modified=old_record.modified,
            size=old_record.size,
            type=old_record.type,
            mtime=old_record.mtime,
            tags=old_record.tags,
        )
        self._notes[new_path] = new_record
        if new_record.folder:
            self._folders.add(new_record.folder)

        if old_path in self._tags_forward:
            tags = self._tags_forward.pop(old_path)
            self._tags_forward[new_path] = tags
            for t in tags:
                bucket = self._tags_backward.get(t)
                if bucket is not None:
                    bucket.discard(old_path)
                    bucket.add(new_path)

        for paths in self._search_terms.values():
            if old_path in paths:
                paths.discard(old_path)
                paths.add(new_path)

        if old_path in self._raw_links:
            self._raw_links[new_path] = self._raw_links.pop(old_path)

        self._links_forward.pop(old_path, None)
        for bucket in self._links_backward.values():
            bucket.discard(old_path)
        old_backlinks = self._links_backward.pop(old_path, set())
        for src in old_backlinks:
            fwd = self._links_forward.get(src)
            if fwd is not None and old_path in fwd:
                del fwd[old_path]
                if not fwd:
                    del self._links_forward[src]

        empty_keys = []
        for key, sources in self._wikilink_tokens.items():
            if old_path in sources:
                sources.discard(old_path)
                sources.add(new_path)
            if not sources:
                empty_keys.append(key)
        for k in empty_keys:
            del self._wikilink_tokens[k]

    def _remove_note_unlocked(self, path: str) -> None:
        """Same as remove_note() but assumes the caller already holds the lock."""
        old_record = self._notes.pop(path, None)
        if old_record is None:
            return
        for t in old_record.tags:
            bucket = self._tags_backward.get(t)
            if bucket is not None:
                bucket.discard(path)
                if not bucket:
                    del self._tags_backward[t]
        self._tags_forward.pop(path, None)
        self._raw_links.pop(path, None)
        old_targets = self._links_forward.pop(path, {})
        for t in old_targets:
            bucket = self._links_backward.get(t)
            if bucket is not None:
                bucket.discard(path)
                if not bucket:
                    del self._links_backward[t]
        empty_keys = []
        for key, sources in self._wikilink_tokens.items():
            sources.discard(path)
            if not sources:
                empty_keys.append(key)
        for k in empty_keys:
            del self._wikilink_tokens[k]
        sources_pointing_here = self._links_backward.pop(path, set())
        for src in sources_pointing_here:
            fwd = self._links_forward.get(src)
            if fwd is not None and path in fwd:
                del fwd[path]
                if not fwd:
                    del self._links_forward[src]
        empty_terms = []
        for term, paths in self._search_terms.items():
            if path in paths:
                paths.discard(path)
                if not paths:
                    empty_terms.append(term)
        for term in empty_terms:
            del self._search_terms[term]


# ============================================================================
# Resolver — link-target matching (mirrors legacy /api/graph rules exactly)
# ============================================================================

class _Resolver:
    """Link-target lookup tables. Build once per resolution batch, then call
    resolve_* repeatedly across many sources."""

    def __init__(self, all_notes: Set[str]) -> None:
        self.note_paths: Set[str] = set(all_notes)
        self.note_paths_lower: Dict[str, str] = {}
        self.note_names: Dict[str, str] = {}
        for p in all_notes:
            self.note_paths_lower[p.lower()] = p
            if p.endswith(".md"):
                self.note_paths_lower[p[:-3].lower()] = p
            stem = Path(p).stem
            self.note_names[stem.lower()] = p
            self.note_names[Path(p).name.lower()] = p

    def resolve_wikilink(self, target: str, source_folder: str) -> Optional[str]:
        target = target.strip()
        if not target:
            return None
        target_lower = target.lower()

        # 1. Relative to source folder (only for bare names with no slash).
        if source_folder and "/" not in target:
            relative_path = f"{source_folder}/{target}"
            relative_path_lower = relative_path.lower()
            if relative_path in self.note_paths:
                return relative_path if relative_path.endswith(".md") else relative_path + ".md"
            if relative_path + ".md" in self.note_paths:
                return relative_path + ".md"
            if relative_path_lower in self.note_paths_lower:
                return self.note_paths_lower[relative_path_lower]
            if (relative_path_lower + ".md") in self.note_paths_lower:
                return self.note_paths_lower[relative_path_lower + ".md"]

        if target in self.note_paths:
            return target if target.endswith(".md") else target + ".md"
        if (target + ".md") in self.note_paths:
            return target + ".md"
        if target_lower in self.note_paths_lower:
            return self.note_paths_lower[target_lower]
        if (target_lower + ".md") in self.note_paths_lower:
            return self.note_paths_lower[target_lower + ".md"]
        if target_lower in self.note_names:
            return self.note_names[target_lower]
        return None

    def resolve_mdlink(self, link_path: str, source_folder: str) -> Optional[str]:
        if not link_path:
            return None
        link_path = link_path.split("#")[0]
        if not link_path:
            return None
        link_path = urllib.parse.unquote(link_path)
        if link_path.startswith("./"):
            link_path = link_path[2:]
        link_path_with_md = link_path if link_path.endswith(".md") else link_path + ".md"

        if source_folder and not link_path.startswith("/"):
            relative_path = f"{source_folder}/{link_path}"
            relative_path_with_md = f"{source_folder}/{link_path_with_md}"
            relative_path_lower = relative_path.lower()
            relative_path_with_md_lower = relative_path_with_md.lower()
            if relative_path in self.note_paths:
                return relative_path if relative_path.endswith(".md") else relative_path + ".md"
            if relative_path_with_md in self.note_paths:
                return relative_path_with_md
            if relative_path_lower in self.note_paths_lower:
                return self.note_paths_lower[relative_path_lower]
            if relative_path_with_md_lower in self.note_paths_lower:
                return self.note_paths_lower[relative_path_with_md_lower]

        link_path_lower = link_path.lower()
        link_path_with_md_lower = link_path_with_md.lower()
        if link_path in self.note_paths:
            return link_path if link_path.endswith(".md") else link_path + ".md"
        if link_path_with_md in self.note_paths:
            return link_path_with_md
        if link_path_lower in self.note_paths_lower:
            return self.note_paths_lower[link_path_lower]
        if link_path_with_md_lower in self.note_paths_lower:
            return self.note_paths_lower[link_path_with_md_lower]
        return None


# ============================================================================
# Internal helpers
# ============================================================================

def _fingerprint(
    notes_meta: List[NoteRecord],
    sources_raw: Dict[str, Dict[str, List[str]]],
) -> int:
    """Cheap hash of a scan result. Short-circuits bulk_set when unchanged."""
    notes_fp = hash(frozenset((n.path, n.mtime) for n in notes_meta))
    raw_items = (
        (src, tuple(raw.get("wikilinks", [])), tuple(raw.get("mdlinks", [])))
        for src, raw in sources_raw.items()
    )
    return hash((notes_fp, hash(frozenset(raw_items))))


# ============================================================================
# Module singleton + facade. Callers in utils.py / main.py go through these.
# ============================================================================

_index = NoteIndex()


def get_index() -> NoteIndex:
    return _index


# --- Lifecycle hooks (one-line calls from utils.py mutators) ----------------

def on_note_saved(notes_dir: str, full_path: Path, content: str) -> None:
    """A note was created or updated on disk."""
    try:
        rel_path = full_path.relative_to(Path(notes_dir)).as_posix()
        st = full_path.stat()
        folder = str(Path(rel_path).parent).replace("\\", "/")
        record = NoteRecord(
            path=rel_path,
            name=Path(rel_path).stem,
            folder="" if folder == "." else folder,
            modified=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            size=st.st_size,
            type="note",
            mtime=st.st_mtime,
            tags=tuple(_parse_tags_for_record(content)),
        )
        _index.update_note(record, extract_links_from_content(content), content=content)
    except Exception as e:
        logger.error("note_index: on_note_saved failed for %s: %s", full_path, e)


def on_note_deleted(notes_dir: str, full_path: Path) -> None:
    try:
        rel_path = full_path.relative_to(Path(notes_dir)).as_posix()
        _index.remove_note(rel_path)
    except Exception as e:
        logger.error("note_index: on_note_deleted failed for %s: %s", full_path, e)


def on_note_renamed(notes_dir: str, old_full_path: Path, new_full_path: Path) -> None:
    try:
        base = Path(notes_dir)
        _index.rename_note(
            old_full_path.relative_to(base).as_posix(),
            new_full_path.relative_to(base).as_posix(),
        )
    except Exception as e:
        logger.error("note_index: on_note_renamed failed: %s", e)


def on_folder_renamed(notes_dir: str, old_full_path: Path, new_full_path: Path) -> None:
    """Re-key every entry under the folder. No disk reads."""
    try:
        base = Path(notes_dir)
        _index.rename_folder_prefix(
            old_full_path.relative_to(base).as_posix(),
            new_full_path.relative_to(base).as_posix(),
        )
    except Exception as e:
        logger.error("note_index: on_folder_renamed failed: %s", e)
        _index.invalidate()


def on_folder_deleted(notes_dir: str, full_path: Path) -> None:
    try:
        rel_prefix = full_path.relative_to(Path(notes_dir)).as_posix()
        _index.remove_folder_prefix(rel_prefix)
    except Exception as e:
        logger.error("note_index: on_folder_deleted failed: %s", e)
        _index.invalidate()


def populate_from_scan(
    notes_meta: List[NoteRecord],
    folders: Iterable[str],
    sources_raw: Dict[str, Dict[str, List[str]]],
) -> None:
    """Bulk-replace the index after a full scan_notes_fast_walk."""
    try:
        _index.bulk_set(notes_meta, folders, sources_raw)
    except Exception as e:
        logger.error("note_index: populate_from_scan failed: %s", e)


def ensure_search_index(notes_dir: str) -> bool:
    """Lazy-build the search index on first /api/search. Returns False only
    if the main index isn't built yet."""
    if not _index.is_built():
        return False
    return _index.ensure_search_index_built(notes_dir)


# --- Read facade -------------------------------------------------------------

def get_backlink_candidates(target_path: str) -> Set[str]:
    return _index.get_backlink_candidate_sources(target_path)


def get_graph_data() -> Tuple[List[str], List[Tuple[str, str, str]]]:
    return _index.get_graph_data()


def get_search_candidates(query: str) -> Optional[Set[str]]:
    """Returns None when query is too short / untokenizable — caller iterates
    every indexed note instead."""
    return _index.get_search_candidates(query)


def get_all_tags() -> Dict[str, int]:
    return _index.get_all_tags()


def get_paths_for_tag(tag: str) -> Set[str]:
    return _index.get_paths_for_tag(tag)


def try_get_extraction(
    rel_path: str,
    mtime: float,
) -> Optional[Tuple[List[str], Dict[str, List[str]]]]:
    """(tags, raw_links) from the index when mtime matches, else None so the
    caller reads the file. Used by scan_notes_fast_walk."""
    return _index.try_get_extraction(rel_path, mtime)


def summary() -> Dict[str, Any]:
    return _index.summary()


def stats() -> Dict[str, Any]:
    return _index.stats()


# Late import — utils imports this module, so we delay the reverse direction.
def _parse_tags_for_record(content: str) -> List[str]:
    from .utils import parse_tags
    return parse_tags(content)
