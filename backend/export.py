"""
HTML Export Module for NoteDiscovery
Generates standalone HTML files for notes with embedded images and styling.
Used by both /api/export (download) and /share (public sharing) endpoints.

Note: Only images are embedded as base64. Audio, video, and PDF files are
replaced with placeholder HTML since they would make exports too large.
"""

import base64
import re
from pathlib import Path
from typing import Optional, Tuple
import mimetypes

# Import shared media type definitions and scanner from utils to avoid duplication
from backend.utils import MEDIA_EXTENSIONS, get_media_type, scan_notes_fast_walk


def get_media_as_base64(media_path: Path) -> Optional[Tuple[str, str]]:
    """
    Read a media file and return it as a base64 data URL.
    Returns tuple of (base64_url, media_type) or None if failed.
    """
    if not media_path.exists() or not media_path.is_file():
        return None
    
    # Get MIME type
    mime_type, _ = mimetypes.guess_type(str(media_path))
    if not mime_type:
        return None
    
    # Determine media type
    media_type = get_media_type(media_path.name)
    if not media_type:
        return None
    
    try:
        with open(media_path, 'rb') as f:
            media_data = f.read()
        base64_data = base64.b64encode(media_data).decode('utf-8')
        return (f"data:{mime_type};base64,{base64_data}", media_type)
    except Exception as e:
        print(f"Failed to read media {media_path}: {e}")
        return None


# Legacy alias for backward compatibility
def get_image_as_base64(image_path: Path) -> Optional[str]:
    """Read an image file and return it as a base64 data URL."""
    result = get_media_as_base64(image_path)
    if result and result[1] == 'image':
        return result[0]
    return None


def strip_frontmatter(content: str) -> str:
    """
    Remove YAML frontmatter from markdown content.
    Frontmatter is delimited by --- at the start and end.
    """
    if not content.strip().startswith('---'):
        return content
    
    lines = content.split('\n')
    if lines[0].strip() != '---':
        return content
    
    # Find closing ---
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end_idx = i
            break
    
    if end_idx == -1:
        return content
    
    # Remove frontmatter and return the rest
    return '\n'.join(lines[end_idx + 1:]).strip()


def find_media_in_attachments(media_name: str, note_folder: Path, notes_dir: Path) -> Optional[Path]:
    """
    Search for a media file in common attachment locations.
    Returns the resolved path if found, None otherwise.
    """
    # Common locations to search for media (fast path)
    search_paths = [
        note_folder / media_name,                          # Same folder as note
        note_folder / '_attachments' / media_name,         # Note's _attachments folder
        notes_dir / '_attachments' / media_name,           # Root _attachments folder
    ]
    
    # Also search in parent folders' _attachments (for nested notes)
    current = note_folder
    while current != notes_dir and current.parent != current:
        search_paths.append(current / '_attachments' / media_name)
        current = current.parent
    
    for path in search_paths:
        resolved = path.resolve()
        if resolved.exists() and resolved.is_file():
            # Security: ensure path is within notes_dir
            try:
                resolved.relative_to(notes_dir.resolve())
                return resolved
            except ValueError:
                continue
    
    # Fallback: search all _attachments folders recursively (slower but thorough)
    # This handles cross-folder media references like in Obsidian
    try:
        _files, folders = scan_notes_fast_walk(str(notes_dir), include_media=False)
        for folder in folders:
            if folder == '_attachments' or folder.endswith('/_attachments'):
                attachment_folder = notes_dir / folder
                candidate = attachment_folder / media_name
                if candidate.exists() and candidate.is_file():
                    try:
                        candidate.resolve().relative_to(notes_dir.resolve())
                        return candidate.resolve()
                    except ValueError:
                        continue
    except Exception:
        pass  # Ignore errors in recursive search
    
    return None


# Legacy alias
def find_image_in_attachments(image_name: str, note_folder: Path, notes_dir: Path) -> Optional[Path]:
    return find_media_in_attachments(image_name, note_folder, notes_dir)


def generate_media_placeholder(media_type: str, alt_text: str) -> str:
    """Generate a placeholder for non-embeddable media (audio, video, PDF)."""
    safe_alt = alt_text.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
    
    icons = {'audio': '🎵', 'video': '🎬', 'document': '📄'}
    labels = {'audio': 'Audio file', 'video': 'Video file', 'document': 'PDF document'}
    icon = icons.get(media_type, '📎')
    label = labels.get(media_type, 'Media file')
    
    return f'''<div style="margin:1.5rem 0;padding:1.5rem;background:linear-gradient(135deg,var(--bg-tertiary,#f8f9fa) 0%,var(--bg-secondary,#e9ecef) 100%);border:1px solid var(--border-primary,#dee2e6);border-radius:0.5rem;display:flex;align-items:center;gap:1rem;">
<span style="font-size:2rem;">{icon}</span>
<div>
<div style="font-weight:600;color:var(--text-primary,#212529);">{safe_alt}</div>
<div style="font-size:0.875rem;color:var(--text-secondary,#6c757d);">{label} — not available in exported view</div>
</div>
</div>'''


def process_media_for_export(markdown_content: str, note_folder: Path, notes_dir: Path) -> str:
    """
    Process all media references in markdown for standalone HTML export.
    
    Handles:
    - Standard markdown images: ![alt](path)
    - Wikilink media: ![[file.png]] or ![[file.mp3|alt text]]
    
    Behavior by media type:
    - Images (jpg, png, gif, webp): Embedded as base64 data URLs
    - Audio/Video/PDF: Replaced with styled placeholder HTML (not embedded - too large)
    """
    
    # First, handle wikilink media: ![[file.png]] or ![[file.mp3|alt text]]
    wikilink_pattern = r'!\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'
    
    def replace_wikilink_media(match):
        media_name = match.group(1).strip()
        alt_text = match.group(2).strip() if match.group(2) else media_name.split('/')[-1].rsplit('.', 1)[0]
        
        # Check media type first
        media_type = get_media_type(media_name)
        
        # For non-image media (audio, video, PDF), show placeholder without embedding
        if media_type in ('audio', 'video', 'document'):
            return generate_media_placeholder(media_type, alt_text)
        
        # For images, embed as base64
        resolved_path = find_media_in_attachments(media_name, note_folder, notes_dir)
        
        if resolved_path:
            base64_url = get_image_as_base64(resolved_path)
            if base64_url:
                return f'![{alt_text}]({base64_url})'
        
        # Image not found
        return f'<span style="color:var(--text-tertiary,#999);opacity:0.7;" title="Image not found">🖼️ {alt_text}</span>'
    
    markdown_content = re.sub(wikilink_pattern, replace_wikilink_media, markdown_content)
    
    # Then, handle standard markdown images: ![alt](path)
    img_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    
    def replace_media(match):
        alt_text = match.group(1)
        media_path = match.group(2)
        
        # Handle external URLs
        if media_path.startswith(('http://', 'https://')):
            # Check if it's a PDF - generate styled external link
            media_type = get_media_type(media_path)
            if media_type == 'document':
                display_name = alt_text or Path(media_path).stem
                safe_name = display_name.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                safe_url = media_path.replace('"', '&quot;')
                return f'''<a href="{safe_url}" target="_blank" rel="noopener noreferrer" style="display:flex;flex-direction:column;gap:0.25rem;padding:1rem 1.25rem;margin:1rem 0;background:linear-gradient(135deg,var(--bg-tertiary,#f8f9fa) 0%,var(--bg-secondary,#e9ecef) 100%);border:1px solid var(--border-primary,#dee2e6);border-radius:0.5rem;color:var(--text-primary,#212529);text-decoration:none;">
<span style="font-weight:600;">📄 {safe_name}</span>
<span style="font-size:0.75rem;color:var(--text-secondary,#6c757d);">Opens in new tab</span>
</a>'''
            # Other external media: keep as-is (will show as broken image)
            return match.group(0)
        
        # Skip already-embedded base64
        if media_path.startswith('data:'):
            return match.group(0)
        
        # Skip empty paths (from failed wikilink conversion)
        if not media_path:
            return match.group(0)
        
        # Check media type first
        media_type = get_media_type(media_path)
        display_alt = alt_text or Path(media_path).stem
        
        # For non-image media (audio, video, PDF), show placeholder without embedding
        if media_type in ('audio', 'video', 'document'):
            return generate_media_placeholder(media_type, display_alt)
        
        # For images, proceed with base64 embedding
        # Handle /api/media/ or legacy /api/images/ paths (convert to filesystem paths)
        if media_path.startswith('/api/media/'):
            relative_path = media_path[len('/api/media/'):]
            resolved_path = (notes_dir / relative_path).resolve()
        elif media_path.startswith('/api/images/'):
            # Legacy path support for backward compatibility
            relative_path = media_path[len('/api/images/'):]
            resolved_path = (notes_dir / relative_path).resolve()
        else:
            # Try to resolve the media path relative to note folder
            resolved_path = (note_folder / media_path).resolve()
        
        # If not found, try the attachment search
        if not resolved_path.exists():
            # Extract just the filename and search
            media_name = Path(media_path).name
            resolved_path = find_media_in_attachments(media_name, note_folder, notes_dir)
            if not resolved_path:
                return match.group(0)  # Keep original if not found
        
        # Security: ensure path is within notes_dir
        try:
            resolved_path.relative_to(notes_dir.resolve())
        except ValueError:
            # Path is outside notes_dir, skip
            return match.group(0)
        
        # Get base64 data for image
        base64_url = get_image_as_base64(resolved_path)
        if base64_url:
            return f'![{display_alt}]({base64_url})'
        
        # Image not found, keep original
        return match.group(0)
    
    markdown_content = re.sub(img_pattern, replace_media, markdown_content)
    
    return markdown_content


# Legacy alias for backward compatibility
# Legacy alias for backward compatibility
def embed_images_as_base64(markdown_content: str, note_folder: Path, notes_dir: Path) -> str:
    """Alias for process_media_for_export (legacy name kept for compatibility)."""
    return process_media_for_export(markdown_content, note_folder, notes_dir)


def convert_wikilinks_to_html(markdown_content: str) -> str:
    """
    Convert wikilinks [[note]] or [[note|display text]] to HTML links.
    In standalone export mode, these are non-functional decorative links.
    """
    # Pattern for wikilinks: [[target]] or [[target|display text]]
    # But NOT image wikilinks (those start with !)
    wikilink_pattern = r'(?<!!)\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'
    
    def replace_wikilink(match):
        target = match.group(1).strip()
        display = match.group(2).strip() if match.group(2) else target
        
        # Create a decorative link (href="#" since it's standalone)
        return f'<a href="#" class="wikilink" title="{target}" style="color: var(--accent-primary, #0366d6); text-decoration: none; border-bottom: 1px dashed currentColor;">{display}</a>'
    
    return re.sub(wikilink_pattern, replace_wikilink, markdown_content)


def generate_export_html(
    title: str,
    content: str,
    theme_css: str,
    is_dark: bool = False
) -> str:
    """
    Generate a standalone HTML document for a note.
    Uses marked.js for client-side markdown rendering.
    
    Args:
        title: The note title (for <title> and display)
        content: Raw markdown content (images should already be base64 embedded)
        theme_css: CSS content for theming
        is_dark: Whether using a dark theme (for Mermaid/Highlight.js)
    
    Returns:
        Complete HTML document as string
    """
    # Escape content for JavaScript string
    escaped_content = (
        content
        .replace('\\', '\\\\')
        .replace('`', '\\`')
        .replace('$', '\\$')
        .replace('</', '<\\/')  # Prevent </script> breaking
    )
    
    highlight_theme = 'github-dark' if is_dark else 'github'
    mermaid_theme = 'dark' if is_dark else 'default'
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    
    <!-- Highlight.js for code syntax highlighting -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/{highlight_theme}.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    
    <!-- Marked.js for markdown parsing -->
    <script src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js"></script>
    
    <!-- MathJax for LaTeX math rendering -->
    <script>
        MathJax = {{
            tex: {{
                inlineMath: [['$', '$']],
                displayMath: [['$$', '$$']],
                processEscapes: true,
                processEnvironments: true
            }},
            options: {{
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
            }},
            startup: {{
                pageReady: () => {{
                    return MathJax.startup.defaultPageReady().then(() => {{
                        // Highlight code blocks after MathJax is done
                        document.querySelectorAll('pre code:not(.language-mermaid)').forEach((block) => {{
                            hljs.highlightElement(block);
                        }});
                    }});
                }}
            }}
        }};
    </script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js"></script>
    
    <!-- Mermaid.js for diagrams -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11.12.2/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ 
            startOnLoad: false,
            theme: '{mermaid_theme}',
            securityLevel: 'strict',
            fontFamily: 'inherit',
            flowchart: {{ useMaxWidth: true }},
            sequence: {{ useMaxWidth: true }},
            gantt: {{ useMaxWidth: true }},
            state: {{ useMaxWidth: true }},
            er: {{ useMaxWidth: true }},
            pie: {{ useMaxWidth: true }},
            mindmap: {{ useMaxWidth: true }},
            gitGraph: {{ useMaxWidth: true }}
        }});
        
        // Render Mermaid diagrams after page load
        document.addEventListener('DOMContentLoaded', async () => {{
            const mermaidBlocks = document.querySelectorAll('pre code.language-mermaid');
            for (let i = 0; i < mermaidBlocks.length; i++) {{
                const block = mermaidBlocks[i];
                const pre = block.parentElement;
                try {{
                    const code = block.textContent;
                    const id = 'mermaid-diagram-' + i;
                    const {{ svg }} = await mermaid.render(id, code);
                    const container = document.createElement('div');
                    container.className = 'mermaid-rendered';
                    container.style.cssText = 'background-color: transparent; padding: 20px; text-align: center; overflow-x: auto;';
                    container.innerHTML = svg;
                    pre.parentElement.replaceChild(container, pre);
                }} catch (error) {{
                    console.error('Mermaid rendering error:', error);
                }}
            }}
        }});
    </script>
    
    <style>
        /* Theme CSS */
        {theme_css}
        
        /* Base styles */
        * {{
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 2rem;
            max-width: 900px;
            margin-left: auto;
            margin-right: auto;
            background-color: var(--bg-primary, #ffffff);
            color: var(--text-primary, #333333);
        }}
        
        /* Markdown content styles */
        .markdown-preview {{
            line-height: 1.6;
        }}
        
        .markdown-preview h1,
        .markdown-preview h2,
        .markdown-preview h3,
        .markdown-preview h4,
        .markdown-preview h5,
        .markdown-preview h6 {{
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            font-weight: 600;
            line-height: 1.25;
        }}
        
        .markdown-preview h1 {{ font-size: 2em; border-bottom: 1px solid var(--border-color, #e1e4e8); padding-bottom: 0.3em; }}
        .markdown-preview h2 {{ font-size: 1.5em; border-bottom: 1px solid var(--border-color, #e1e4e8); padding-bottom: 0.3em; }}
        .markdown-preview h3 {{ font-size: 1.25em; }}
        .markdown-preview h4 {{ font-size: 1em; }}
        
        .markdown-preview p {{
            margin: 1em 0;
        }}
        
        .markdown-preview a {{
            color: var(--accent-primary, #0366d6);
            text-decoration: none;
        }}
        
        .markdown-preview a:hover {{
            text-decoration: underline;
        }}
        
        .markdown-preview img {{
            max-width: 100%;
            height: auto;
            border-radius: 4px;
        }}
        
        /* Inline code */
        .markdown-preview code:not(pre code) {{ 
            background-color: var(--bg-tertiary, #f6f8fa);
            color: var(--accent-primary, #0366d6);
            padding: 0.2rem 0.4rem;
            border-radius: 0.25rem;
            font-size: 0.875rem;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-weight: 500;
        }}
        
        /* Code blocks */
        .markdown-preview pre {{ 
            background-color: var(--bg-tertiary, #f6f8fa);
            margin-bottom: 1.5rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            border: 1px solid var(--border-primary, #e1e4e8);
        }}
        
        .markdown-preview pre code {{
            background: transparent;
            padding: 1rem;
            display: block;
            font-size: 0.875rem;
            line-height: 1.6;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            color: inherit;
        }}
        
        .markdown-preview blockquote {{
            margin: 1em 0;
            padding: 0 1em;
            border-left: 4px solid var(--accent-primary, #0366d6);
            color: var(--text-secondary, #6a737d);
        }}
        
        .markdown-preview ul,
        .markdown-preview ol {{
            padding-left: 2em;
            margin: 1em 0;
        }}
        
        .markdown-preview li {{
            margin: 0.25em 0;
        }}
        
        .markdown-preview table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }}
        
        .markdown-preview th,
        .markdown-preview td {{
            border: 1px solid var(--border-color, #e1e4e8);
            padding: 0.5em 1em;
            text-align: left;
        }}
        
        .markdown-preview th {{
            background-color: var(--bg-secondary, #f6f8fa);
            font-weight: 600;
        }}
        
        .markdown-preview hr {{
            border: none;
            border-top: 1px solid var(--border-color, #e1e4e8);
            margin: 2em 0;
        }}
        
        /* Task list styling */
        .markdown-preview input[type="checkbox"] {{
            margin-right: 0.5em;
        }}
        
        /* Enhanced Shell/Bash Syntax Highlighting */
        .markdown-preview pre code.language-shell .hljs-meta,
        .markdown-preview pre code.language-bash .hljs-meta,
        .markdown-preview pre code.language-sh .hljs-meta {{
            color: #7c3aed !important;
            font-weight: 600;
        }}
        
        .markdown-preview pre code.language-shell .hljs-built_in,
        .markdown-preview pre code.language-bash .hljs-built_in,
        .markdown-preview pre code.language-sh .hljs-built_in {{
            color: #10b981 !important;
            font-weight: 500;
        }}
        
        .markdown-preview pre code.language-shell .hljs-string,
        .markdown-preview pre code.language-bash .hljs-string,
        .markdown-preview pre code.language-sh .hljs-string {{
            color: #f59e0b !important;
        }}
        
        .markdown-preview pre code.language-shell .hljs-variable,
        .markdown-preview pre code.language-bash .hljs-variable,
        .markdown-preview pre code.language-sh .hljs-variable {{
            color: #06b6d4 !important;
            font-weight: 500;
        }}
        
        .markdown-preview pre code.language-shell .hljs-comment,
        .markdown-preview pre code.language-bash .hljs-comment,
        .markdown-preview pre code.language-sh .hljs-comment {{
            color: #6b7280 !important;
            font-style: italic;
        }}
        
        .markdown-preview pre code.language-shell .hljs-keyword,
        .markdown-preview pre code.language-bash .hljs-keyword,
        .markdown-preview pre code.language-sh .hljs-keyword {{
            color: #ec4899 !important;
            font-weight: 600;
        }}
        
        /* Enhanced PowerShell Syntax Highlighting */
        .markdown-preview pre code.language-powershell .hljs-built_in,
        .markdown-preview pre code.language-ps1 .hljs-built_in {{
            color: #10b981 !important;
            font-weight: 600;
        }}
        
        .markdown-preview pre code.language-powershell .hljs-variable,
        .markdown-preview pre code.language-ps1 .hljs-variable {{
            color: #06b6d4 !important;
            font-weight: 500;
        }}
        
        .markdown-preview pre code.language-powershell .hljs-string,
        .markdown-preview pre code.language-ps1 .hljs-string {{
            color: #f59e0b !important;
        }}
        
        .markdown-preview pre code.language-powershell .hljs-keyword,
        .markdown-preview pre code.language-ps1 .hljs-keyword {{
            color: #ec4899 !important;
            font-weight: 600;
        }}
        
        .markdown-preview pre code.language-powershell .hljs-comment,
        .markdown-preview pre code.language-ps1 .hljs-comment {{
            color: #6b7280 !important;
            font-style: italic;
        }}
        
        /* Copy button for code blocks */
        .markdown-preview pre {{
            position: relative;
        }}
        
        .copy-btn {{
            position: absolute;
            top: 0.5rem;
            right: 0.5rem;
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem;
            background-color: var(--bg-secondary, #e1e4e8);
            color: var(--text-secondary, #586069);
            border: 1px solid var(--border-primary, #d0d7de);
            border-radius: 0.25rem;
            cursor: pointer;
            opacity: 0;
            transition: opacity 0.2s ease;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        
        .markdown-preview pre:hover .copy-btn {{
            opacity: 1;
        }}
        
        .copy-btn:hover {{
            background-color: var(--accent-primary, #0366d6);
            color: white;
            border-color: var(--accent-primary, #0366d6);
        }}
        
        .copy-btn.copied {{
            background-color: #10b981;
            color: white;
            border-color: #10b981;
        }}
        
        @media (max-width: 768px) {{
            body {{
                padding: 1rem;
            }}
        }}
        
        @media print {{
            body {{
                padding: 0.5in;
                max-width: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="markdown-preview" id="content"></div>
    
    <script>
        // Configure marked
        marked.setOptions({{
            gfm: true,
            breaks: true,
            headerIds: true,
            mangle: false
        }});
        
        // Raw markdown content
        const markdown = `{escaped_content}`;
        
        // Render markdown
        document.getElementById('content').innerHTML = marked.parse(markdown);
        
        // Add copy buttons to code blocks
        document.querySelectorAll('.markdown-preview pre').forEach(pre => {{
            const btn = document.createElement('button');
            btn.className = 'copy-btn';
            btn.textContent = 'Copy';
            btn.addEventListener('click', async () => {{
                const code = pre.querySelector('code');
                if (code) {{
                    try {{
                        await navigator.clipboard.writeText(code.textContent);
                        btn.textContent = 'Copied!';
                        btn.classList.add('copied');
                        setTimeout(() => {{
                            btn.textContent = 'Copy';
                            btn.classList.remove('copied');
                        }}, 2000);
                    }} catch (err) {{
                        btn.textContent = 'Failed';
                        setTimeout(() => btn.textContent = 'Copy', 2000);
                    }}
                }}
            }});
            pre.appendChild(btn);
        }});
    </script>
</body>
</html>'''
    
    return html
