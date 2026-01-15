"""
HTML Export Module for NoteDiscovery
Generates standalone HTML files for notes with embedded images and styling.
Used by both /api/export (download) and /public (sharing) endpoints.
"""

import base64
import re
from pathlib import Path
from typing import Optional
import mimetypes


def get_image_as_base64(image_path: Path) -> Optional[str]:
    """Read an image file and return it as a base64 data URL."""
    if not image_path.exists() or not image_path.is_file():
        return None
    
    # Get MIME type
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if not mime_type or not mime_type.startswith('image/'):
        return None
    
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        base64_data = base64.b64encode(image_data).decode('utf-8')
        return f"data:{mime_type};base64,{base64_data}"
    except Exception as e:
        print(f"Failed to read image {image_path}: {e}")
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


def find_image_in_attachments(image_name: str, note_folder: Path, notes_dir: Path) -> Optional[Path]:
    """
    Search for an image file in common attachment locations.
    Returns the resolved path if found, None otherwise.
    """
    # Common locations to search for images (fast path)
    search_paths = [
        note_folder / image_name,                          # Same folder as note
        note_folder / '_attachments' / image_name,         # Note's _attachments folder
        notes_dir / '_attachments' / image_name,           # Root _attachments folder
    ]
    
    # Also search in parent folders' _attachments (for nested notes)
    current = note_folder
    while current != notes_dir and current.parent != current:
        search_paths.append(current / '_attachments' / image_name)
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
    # This handles cross-folder image references like in Obsidian
    try:
        for attachment_folder in notes_dir.rglob('_attachments'):
            if attachment_folder.is_dir():
                candidate = attachment_folder / image_name
                if candidate.exists() and candidate.is_file():
                    try:
                        candidate.resolve().relative_to(notes_dir.resolve())
                        return candidate.resolve()
                    except ValueError:
                        continue
    except Exception:
        pass  # Ignore errors in recursive search
    
    return None


def embed_images_as_base64(markdown_content: str, note_folder: Path, notes_dir: Path) -> str:
    """
    Find all image references in markdown and embed them as base64.
    Handles:
    - Standard markdown images: ![alt](path)
    - Wikilink images: ![[image.png]] or ![[image.png|alt text]]
    """
    
    # First, handle wikilink images: ![[image.png]] or ![[image.png|alt text]]
    wikilink_img_pattern = r'!\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'
    
    def replace_wikilink_image(match):
        image_name = match.group(1).strip()
        alt_text = match.group(2).strip() if match.group(2) else image_name.split('/')[-1].rsplit('.', 1)[0]
        
        # Find the image
        resolved_path = find_image_in_attachments(image_name, note_folder, notes_dir)
        
        if resolved_path:
            base64_url = get_image_as_base64(resolved_path)
            if base64_url:
                return f'![{alt_text}]({base64_url})'
        
        # Image not found, convert to placeholder
        return f'![{alt_text}]()'
    
    markdown_content = re.sub(wikilink_img_pattern, replace_wikilink_image, markdown_content)
    
    # Then, handle standard markdown images: ![alt](path)
    img_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    
    def replace_image(match):
        alt_text = match.group(1)
        img_path = match.group(2)
        
        # Skip external URLs and already-embedded base64
        if img_path.startswith(('http://', 'https://', 'data:')):
            return match.group(0)
        
        # Skip empty paths (from failed wikilink conversion)
        if not img_path:
            return match.group(0)
        
        # Handle /api/images/ paths (convert to filesystem paths)
        if img_path.startswith('/api/images/'):
            # Strip the /api/images/ prefix to get the relative path within notes_dir
            relative_path = img_path[len('/api/images/'):]
            resolved_path = (notes_dir / relative_path).resolve()
        else:
            # Try to resolve the image path relative to note folder
            resolved_path = (note_folder / img_path).resolve()
        
        # If not found, try the attachment search
        if not resolved_path.exists():
            # Extract just the filename and search
            image_name = Path(img_path).name
            resolved_path = find_image_in_attachments(image_name, note_folder, notes_dir)
            if not resolved_path:
                return match.group(0)  # Keep original if not found
        
        # Security: ensure path is within notes_dir
        try:
            resolved_path.relative_to(notes_dir.resolve())
        except ValueError:
            # Path is outside notes_dir, skip
            return match.group(0)
        
        # Get base64 data
        base64_url = get_image_as_base64(resolved_path)
        if base64_url:
            return f'![{alt_text}]({base64_url})'
        
        # Image not found, keep original
        return match.group(0)
    
    markdown_content = re.sub(img_pattern, replace_image, markdown_content)
    
    return markdown_content


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
