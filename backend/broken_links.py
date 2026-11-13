"""
Find the links that a move breaks.

A move changes file paths, and other notes may name those paths in their links.
This module finds the notes with such links. It follows the rules the frontend
uses to resolve a link, so a link counts only if it pointed at a moved file and
no longer does. A link by note name, like [[note]], keeps working after a move
to another folder, so it does not count.

Text inside code blocks and inline code is ignored.
"""

import posixpath
import re
import urllib.parse
from typing import Callable, Dict, Iterable, List, Optional, Tuple

_WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(\|[^\]]+)?\]\]')
# Starts at "](" so an image inside a link, [![alt](a.png)](b.md), matches twice.
_MDLINK_RE = re.compile(r'\]\((<[^>]+>|[^)]+?)(\s+"[^"]*")?\)')
_URL_SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.\-]*:')
_INLINE_CODE_RE = re.compile(r'(`+)[^`].*?\1')
_FENCE_RE = re.compile(r'^\s*(`{3,}|~{3,})')
_NEEDS_ENCODING_RE = re.compile(r'[\s()<>]')


class VaultPaths:
    """Finds a file from the text of a link, for one state of the vault."""

    def __init__(self, paths: Iterable[str]):
        self._by_path: Dict[str, str] = {}
        self._by_name: Dict[str, List[str]] = {}
        for path in paths:
            lower = path.lower()
            self._by_path[lower] = path
            filename = lower.rsplit('/', 1)[-1]
            self._by_name.setdefault(filename, []).append(path)
            if filename.endswith('.md'):
                self._by_path[lower[:-3]] = path
                self._by_name.setdefault(filename[:-3], []).append(path)

    def by_path(self, target: str) -> Optional[str]:
        return self._by_path.get(target.lower())

    def resolve_wikilink(self, target: str) -> Optional[str]:
        found = self.by_path(target)
        if found:
            return found
        # With two files of the same name the link is ambiguous, so it counts as
        # pointing at neither of them.
        names = self._by_name.get(target.lower(), [])
        return names[0] if len(names) == 1 else None


def _is_markdown(path: str) -> bool:
    return path.lower().endswith('.md')


def _resolve_mdlink(paths: VaultPaths, source: str, link: str) -> Tuple[Optional[str], bool]:
    """Returns the file a Markdown link points at, and if it resolved from the source folder."""
    if link.startswith('/'):
        return paths.by_path(link.lstrip('/')), False

    from_source = posixpath.normpath(posixpath.join(posixpath.dirname(source), link))
    candidates = [(link, False), (from_source, True)]
    # The frontend opens a note link from the vault root first, and loads an image
    # from the note's folder first.
    suffix = posixpath.splitext(link)[1]
    if suffix and not _is_markdown(link):
        candidates.reverse()
    for candidate, relative in candidates:
        found = paths.by_path(candidate)
        if found:
            return found, relative
    return None, False


def _keep_extension_style(new_path: str, written: str) -> str:
    """A link written without .md stays without it."""
    if _is_markdown(new_path) and not _is_markdown(written):
        return new_path[:-3]
    return new_path


class _LinkRewriter:
    def __init__(self, before: VaultPaths, after: VaultPaths, moves: Dict[str, str]):
        self.before = before
        self.after = after
        self.moves = moves
        self.previous_path = {new: old for old, new in moves.items()}

    def wikilink(self, match: re.Match) -> str:
        target = match.group(1)
        base, hash_sign, anchor = target.strip().partition('#')
        if not base:
            return match.group(0)

        old = self.before.resolve_wikilink(base)
        new = self.moves.get(old) if old else None
        if not new or self.after.resolve_wikilink(base) == new:
            return match.group(0)

        written = _keep_extension_style(new, base)
        return f"[[{written}{hash_sign}{anchor}{match.group(2) or ''}]]"

    def mdlink(self, match: re.Match, source: str) -> str:
        raw = match.group(1)
        angle = raw.startswith('<')
        target = raw[1:-1] if angle else raw
        if _URL_SCHEME_RE.match(target) or target.startswith(('#', '//')):
            return match.group(0)

        encoded_base, hash_sign, anchor = target.partition('#')
        base = urllib.parse.unquote(encoded_base)
        if not base:
            return match.group(0)

        old_source = self.previous_path.get(source, source)
        old, relative = _resolve_mdlink(self.before, old_source, base)
        if not old:
            return match.group(0)

        new = self.moves.get(old, old)
        if new == old and source == old_source:
            return match.group(0)
        if _resolve_mdlink(self.after, source, base)[0] == new:
            return match.group(0)

        if base.startswith('/'):
            written = '/' + new
        elif relative:
            written = posixpath.relpath(new, posixpath.dirname(source) or '.')
        else:
            written = new
        written = _keep_extension_style(written, base)

        if angle:
            written = f"<{written}{hash_sign}{anchor}>"
        else:
            if '%' in encoded_base or _NEEDS_ENCODING_RE.search(written):
                written = urllib.parse.quote(written, safe='/')
            written = f"{written}{hash_sign}{anchor}"
        return f"]({written}{match.group(2) or ''})"

    def rewrite(self, content: str, source: str) -> str:
        output = []
        fence = None
        for line in content.split('\n'):
            marker = _FENCE_RE.match(line)
            if fence:
                closes = marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence)
                if closes:
                    fence = None
                output.append(line)
            elif marker:
                fence = marker.group(1)
                output.append(line)
            else:
                output.append(self._rewrite_line(line, source))
        return '\n'.join(output)

    def _rewrite_line(self, line: str, source: str) -> str:
        pieces = []
        position = 0
        for code in _INLINE_CODE_RE.finditer(line):
            pieces.append(self._rewrite_text(line[position:code.start()], source))
            pieces.append(code.group(0))
            position = code.end()
        pieces.append(self._rewrite_text(line[position:], source))
        return ''.join(pieces)

    def _rewrite_text(self, text: str, source: str) -> str:
        text = _WIKILINK_RE.sub(self.wikilink, text)
        return _MDLINK_RE.sub(lambda match: self.mdlink(match, source), text)


def notes_with_broken_links(
    paths_before: List[str],
    moves: Dict[str, str],
    read_note: Callable[[str], Optional[str]],
) -> List[str]:
    """
    List the notes whose links stopped working because of a move that already happened.

    Args:
        paths_before: Vault-relative path of every file, from before the move
        moves: Old path to new path, for every file that moved
        read_note: Reads a note by its current path

    Returns:
        Current paths of the notes with at least one broken link
    """
    paths_after = [moves.get(path, path) for path in paths_before]
    # A link is broken when pointing it back at its file would change it.
    fixer = _LinkRewriter(VaultPaths(paths_before), VaultPaths(paths_after), moves)

    broken: List[str] = []
    for path in paths_after:
        if not _is_markdown(path):
            continue
        try:
            content = read_note(path)
        except Exception:
            continue
        if content is not None and fixer.rewrite(content, path) != content:
            broken.append(path)
    return sorted(broken)
