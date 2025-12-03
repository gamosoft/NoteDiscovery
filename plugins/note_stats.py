"""
Note Statistics Plugin for NoteDiscovery
Calculates and logs statistics about your notes

Shows:
- Word count
- Character count  
- Reading time estimate
- Number of links
- Number of code blocks
- Line count
"""

import re


class Plugin:
    def __init__(self):
        self.name = "Note Statistics"
        self.version = "1.0.0"
        self.enabled = True
        self.stats_history = {}
    
    def calculate_stats(self, content: str) -> dict:
        """Calculate comprehensive note statistics"""
        # Word count (split by whitespace and filter empty)
        words = len([w for w in re.findall(r'\S+', content) if w])
        
        # Character count (excluding whitespace)
        chars = len(re.sub(r'\s', '', content))
        
        # Total character count (including whitespace)
        total_chars = len(content)
        
        # Reading time (average 200 words per minute)
        reading_time = max(1, round(words / 200))
        
        # Line count
        lines = len(content.split('\n'))
        
        # Paragraph count (blocks separated by blank lines)
        paragraphs = len([p for p in content.split('\n\n') if p.strip()])

        # Sentence count: punctuation [.!?]+ followed by space or end-of-string
        sentences = len(re.findall(r'[.!?]+(?:\s|$)', content))

        # List items: lines starting with -, *, + or a number (e.g. 1., 10.), excluding tasks [-]
        list_items = len(
            re.findall(r'^\s*(?:[-*+]|\d+\.)\s+(?!\[)', content, re.MULTILINE)
        )

        # Tables: count markdown table separator rows (| --- | --- |)
        tables = len(
            re.findall(r'^\s*\|(?:\s*:?-+:?\s*\|){1,}\s*$', content, re.MULTILINE)
        )
        
        # Markdown link count (standard [text](url) format)
        markdown_links = len(re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', content))
        
        # Internal link count (standard markdown links to .md files)
        markdown_internal_links = len(re.findall(r'\[([^\]]+)\]\(([^\)]+\.md)\)', content))
        
        # Wikilink count ([[note]] or [[note|display text]] format - Obsidian style)
        wikilinks = len(re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content))
        
        # Total links and internal links
        links = markdown_links + wikilinks
        internal_links = markdown_internal_links + wikilinks  # All wikilinks are internal
        
        # Code block count
        code_blocks = len(re.findall(r'```[\s\S]*?```', content))
        
        # Inline code count
        inline_code = len(re.findall(r'`[^`]+`', content))
        
        # Heading count by level
        h1_count = len(re.findall(r'^# ', content, re.MULTILINE))
        h2_count = len(re.findall(r'^## ', content, re.MULTILINE))
        h3_count = len(re.findall(r'^### ', content, re.MULTILINE))
        
        # Task count (checkboxes)
        total_tasks = len(re.findall(r'- \[[ x]\]', content))
        completed_tasks = len(re.findall(r'- \[x\]', content, re.IGNORECASE))
        pending_tasks = total_tasks - completed_tasks
        
        # Image count
        images = len(re.findall(r'!\[([^\]]*)\]\(([^\)]+)\)', content))
        
        # Blockquote count
        blockquotes = len(re.findall(r'^> ', content, re.MULTILINE))
        
        return {
            'words': words,
            'sentences': sentences,
            'characters': chars,
            'total_characters': total_chars,
            'reading_time_minutes': reading_time,
            'lines': lines,
            'paragraphs': paragraphs,
            'list_items': list_items,
            'tables': tables,
            'links': links,
            'internal_links': internal_links,
            'external_links': links - internal_links,
            'wikilinks': wikilinks,
            'code_blocks': code_blocks,
            'inline_code': inline_code,
            'headings': {
                'h1': h1_count,
                'h2': h2_count,
                'h3': h3_count,
                'total': h1_count + h2_count + h3_count
            },
            'tasks': {
                'total': total_tasks,
                'completed': completed_tasks,
                'pending': pending_tasks,
                'completion_rate': round(completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
            },
            'images': images,
            'blockquotes': blockquotes
        }
    
    def format_stats(self, stats: dict) -> str:
        """Format statistics as a readable string"""
        lines = [
            f"📊 Statistics:",
            f"  Words: {stats['words']:,}",
            f"  Reading time: ~{stats['reading_time_minutes']} min",
            f"  Lines: {stats['lines']:,}",
        ]
        
        if stats['links'] > 0:
            lines.append(f"  Links: {stats['links']} ({stats['internal_links']} internal, {stats['external_links']} external)")
        
        if stats['code_blocks'] > 0:
            lines.append(f"  Code blocks: {stats['code_blocks']}")
        
        if stats['tasks']['total'] > 0:
            lines.append(f"  Tasks: {stats['tasks']['completed']}/{stats['tasks']['total']} completed ({stats['tasks']['completion_rate']}%)")
        
        if stats['headings']['total'] > 0:
            lines.append(f"  Headings: {stats['headings']['total']} (H1: {stats['headings']['h1']}, H2: {stats['headings']['h2']}, H3: {stats['headings']['h3']})")
        
        return '\n'.join(lines)
    
    def on_note_save(self, note_path: str, content: str) -> str | None:
        """Calculate and log statistics when note is saved"""
        stats = self.calculate_stats(content)
        
        # Store stats history
        self.stats_history[note_path] = stats
        
        # Log key statistics
        print(f"📊 {note_path}:")
        print(
            f"   {stats['words']:,} words | "
            f"{stats['sentences']:,} sentences | "
            f"{stats['reading_time_minutes']}m read | "
            f"{stats['lines']:,} lines | "
            f"{stats['list_items']:,} lists | "
            f"{stats['tables']:,} tables"
        )
        
        if stats['links'] > 0:
            print(f"   {stats['links']} links ({stats['internal_links']} internal)")
        
        if stats['tasks']['total'] > 0:
            print(f"   {stats['tasks']['completed']}/{stats['tasks']['total']} tasks completed")
        
        return None  # Don't modify content, just observe
    
    def get_stats(self, note_path: str) -> dict:
        """Get cached statistics for a note"""
        return self.stats_history.get(note_path, {})
    
    def get_total_stats(self) -> dict:
        """Get aggregated statistics across all notes"""
        if not self.stats_history:
            return {}
        
        total_words = sum(s['words'] for s in self.stats_history.values())
        total_notes = len(self.stats_history)
        total_links = sum(s['links'] for s in self.stats_history.values())
        total_tasks = sum(s['tasks']['total'] for s in self.stats_history.values())
        
        return {
            'total_notes': total_notes,
            'total_words': total_words,
            'average_words_per_note': round(total_words / total_notes) if total_notes > 0 else 0,
            'total_links': total_links,
            'total_tasks': total_tasks,
            'total_reading_time': sum(s['reading_time_minutes'] for s in self.stats_history.values())
        }

