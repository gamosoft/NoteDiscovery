// NoteDiscovery Frontend Application

// Configuration constants
const CONFIG = {
    AUTOSAVE_DELAY: 1000,              // ms - Delay before triggering autosave
    SAVE_INDICATOR_DURATION: 2000,     // ms - How long to show "saved" indicator
    SCROLL_SYNC_DELAY: 50,             // ms - Delay to prevent scroll sync interference
    SCROLL_SYNC_MAX_RETRIES: 10,       // Maximum attempts to find editor/preview elements
    SCROLL_SYNC_RETRY_INTERVAL: 100,   // ms - Time between setupScrollSync retries
    MAX_UNDO_HISTORY: 50,              // Maximum number of undo steps to keep
    DEFAULT_SIDEBAR_WIDTH: 256,        // px - Default sidebar width (w-64 in Tailwind)
};

// Centralized error handling
const ErrorHandler = {
    /**
     * Handle errors consistently across the app
     * @param {string} operation - The operation that failed (e.g., "load notes", "save note")
     * @param {Error} error - The error object
     * @param {boolean} showAlert - Whether to show an alert to the user
     */
    handle(operation, error, showAlert = true) {
        // Always log to console for debugging
        console.error(`Failed to ${operation}:`, error);
        
        // Show user-friendly alert if requested
        if (showAlert) {
            alert(`Failed to ${operation}. Please try again.`);
        }
    }
};

function noteApp() {
    return {
        // App state
        appName: 'NoteDiscovery',
        appTagline: 'Your Self-Hosted Knowledge Base',
        notes: [],
        currentNote: '',
        currentNoteName: '',
        noteContent: '',
        viewMode: 'split', // 'edit', 'split', 'preview'
        searchQuery: '',
        searchResults: [],
        currentSearchHighlight: '', // Track current highlighted search term
        currentMatchIndex: 0, // Current match being viewed
        totalMatches: 0, // Total number of matches in the note
        isSaving: false,
        lastSaved: false,
        saveTimeout: null,
        
        // Theme state
        currentTheme: 'light',
        availableThemes: [],
        
        // Folder state
        folderTree: [],
        allFolders: [],
        expandedFolders: new Set(),
        draggedNote: null,
        draggedFolder: null,
        dragOverFolder: null,  // Track which folder is being hovered during drag
        
        // Scroll sync state
        isScrolling: false,
        
        // Drag state for internal linking
        draggedNoteForLink: null,
        
        // Undo/Redo history
        undoHistory: [],
        redoHistory: [],
        maxHistorySize: CONFIG.MAX_UNDO_HISTORY,
        isUndoRedo: false,
        
        // Stats plugin state
        statsPluginEnabled: false,
        noteStats: null,
        statsExpanded: false,
        
        // Sidebar resize state
        sidebarWidth: CONFIG.DEFAULT_SIDEBAR_WIDTH,
        isResizing: false,
        
        // Mobile sidebar state
        mobileSidebarOpen: false,
        
        // Split view resize state
        editorWidth: 50, // percentage
        isResizingSplit: false,
        
        // Dropdown state
        showNewDropdown: false,
        
        // Mermaid state cache
        lastMermaidTheme: null,
        
        // DOM element cache (to avoid repeated querySelector calls)
        _domCache: {
            editor: null,
            previewContainer: null,
            previewContent: null
        },
        
        // Initialize app
        async init() {
            await this.loadConfig();
            await this.loadThemes();
            await this.initTheme();
            await this.loadNotes();
            await this.checkStatsPlugin();
            this.loadSidebarWidth();
            this.loadEditorWidth();
            this.loadViewMode();
            
            // Parse URL and load specific note if provided
            this.loadNoteFromURL();
            
            // Listen for browser back/forward navigation
            window.addEventListener('popstate', (e) => {
                if (e.state && e.state.notePath) {
                    const searchQuery = e.state.searchQuery || '';
                    this.loadNote(e.state.notePath, false, searchQuery); // false = don't update history
                    
                    // Update search box and trigger search if needed
                    if (searchQuery) {
                        this.searchQuery = searchQuery;
                        this.searchNotes();
                    } else {
                        this.searchQuery = '';
                        this.searchResults = [];
                        this.clearSearchHighlights();
                    }
                }
            });
            
            // Cache DOM references after initial render
            this.$nextTick(() => {
                this.refreshDOMCache();
            });
            
            // Setup mobile view mode handler
            this.setupMobileViewMode();
            
            // Watch view mode changes and auto-save
            this.$watch('viewMode', (newValue) => {
                this.saveViewMode();
                // Scroll to top when switching modes
                this.$nextTick(() => {
                    this.scrollToTop();
                });
            });
            
            // Watch for changes in note content to re-apply search highlights
            this.$watch('noteContent', () => {
                if (this.currentSearchHighlight) {
                    // Re-apply highlights after content changes (with small delay for render)
                    this.$nextTick(() => {
                        setTimeout(() => {
                            // Don't focus editor during content changes (false)
                            this.highlightSearchTerm(this.currentSearchHighlight, false);
                        }, 50);
                    });
                }
            });
            
            // Setup keyboard shortcuts (only once to prevent double triggers)
            if (!window.__noteapp_shortcuts_initialized) {
                window.__noteapp_shortcuts_initialized = true;
                window.addEventListener('keydown', (e) => {
                    // Ctrl/Cmd + S to save
                    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                        e.preventDefault();
                        this.saveNote();
                    }
                    
                    // Ctrl/Cmd + Alt + N for new note
                    if ((e.ctrlKey || e.metaKey) && e.altKey && e.key === 'n') {
                        e.preventDefault();
                        this.createNote();
                    }
                    
                    // Ctrl/Cmd + Alt + F for new folder
                    if ((e.ctrlKey || e.metaKey) && e.altKey && e.key === 'f') {
                        e.preventDefault();
                        this.createFolder();
                    }
                    
                    // Ctrl/Cmd + Z for undo
                    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'z') {
                        e.preventDefault();
                        this.undo();
                    }
                    
                    // Ctrl/Cmd + Y or Ctrl/Cmd + Shift + Z for redo
                    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.shiftKey && e.key === 'z'))) {
                        e.preventDefault();
                        this.redo();
                    }
                    
                    // F3 for next search match
                    if (e.key === 'F3' && !e.shiftKey) {
                        e.preventDefault();
                        this.nextMatch();
                    }
                    
                    // Shift + F3 for previous search match
                    if (e.key === 'F3' && e.shiftKey) {
                        e.preventDefault();
                        this.previousMatch();
                    }
                });
            }
            
            // Note: setupScrollSync() is called when a note is loaded (see loadNote())
            
            // Listen for system theme changes
            if (window.matchMedia) {
                window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                    if (this.currentTheme === 'system') {
                        this.applyTheme('system');
                    }
                });
            }
        },
        
        // Load app configuration
        async loadConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                this.appName = config.name;
                this.appTagline = config.tagline;
            } catch (error) {
                console.error('Failed to load config:', error);
            }
        },
        
        // Load available themes from backend
        async loadThemes() {
            try {
                const response = await fetch('/api/themes');
                const data = await response.json();
                
                // Use theme names directly from backend (already include emojis)
                this.availableThemes = data.themes;
            } catch (error) {
                console.error('Failed to load themes:', error);
                // Fallback to default themes
                this.availableThemes = [
                    { id: 'light', name: '🌞 Light' },
                    { id: 'dark', name: '🌙 Dark' }
                ];
            }
        },
        
        // Initialize theme system
        async initTheme() {
            // Load saved theme preference from localStorage
            const savedTheme = localStorage.getItem('noteDiscoveryTheme') || 'light';
            this.currentTheme = savedTheme;
            await this.applyTheme(savedTheme);
        },
        
        // Set and apply theme
        async setTheme(themeId) {
            this.currentTheme = themeId;
            localStorage.setItem('noteDiscoveryTheme', themeId);
            await this.applyTheme(themeId);
        },
        
        // Apply theme to document
        async applyTheme(themeId) {
            // Load theme CSS from file
            try {
                const response = await fetch(`/api/themes/${themeId}`);
                const data = await response.json();
                
                // Create or update style element
                let styleEl = document.getElementById('dynamic-theme');
                if (!styleEl) {
                    styleEl = document.createElement('style');
                    styleEl.id = 'dynamic-theme';
                    document.head.appendChild(styleEl);
                }
                styleEl.textContent = data.css;
                
                // Set data attribute for theme-specific selectors
                document.documentElement.setAttribute('data-theme', themeId);
                
                // Load appropriate Highlight.js theme for code syntax highlighting
                const highlightTheme = document.getElementById('highlight-theme');
                if (highlightTheme) {
                    if (themeId === 'light') {
                        highlightTheme.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
                    } else {
                        // Use dark theme for dark/custom themes
                        highlightTheme.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css';
                    }
                }
                
                // Re-render Mermaid diagrams with new theme if there's a current note
                if (this.currentNote) {
                    // Small delay to allow theme CSS to load
                    setTimeout(() => {
                        // Clear existing Mermaid renders
                        const previewContent = document.querySelector('.markdown-preview');
                        if (previewContent) {
                            const mermaidContainers = previewContent.querySelectorAll('.mermaid-rendered');
                            mermaidContainers.forEach(container => {
                                // Replace with the original code block for re-rendering
                                const parent = container.parentElement;
                                if (parent && container.dataset.originalCode) {
                                    const pre = document.createElement('pre');
                                    const code = document.createElement('code');
                                    code.className = 'language-mermaid';
                                    code.textContent = container.dataset.originalCode;
                                    pre.appendChild(code);
                                    parent.replaceChild(pre, container);
                                }
                            });
                        }
                        // Re-render with new theme
                        this.renderMermaid();
                    }, 100);
                }
            } catch (error) {
                console.error('Failed to load theme:', error);
            }
        },
        
        // Load all notes
        async loadNotes() {
            try {
                const response = await fetch('/api/notes');
                const data = await response.json();
                this.notes = data.notes;
                this.allFolders = data.folders || [];
                this.buildFolderTree();
            } catch (error) {
                ErrorHandler.handle('load notes', error);
            }
        },
        
        // Build folder tree structure
        buildFolderTree() {
            const tree = {};
            
            // Add ALL folders from backend (including empty ones)
            this.allFolders.forEach(folderPath => {
                const parts = folderPath.split('/');
                let current = tree;
                
                parts.forEach((part, index) => {
                    const fullPath = parts.slice(0, index + 1).join('/');
                    
                    if (!current[part]) {
                        current[part] = {
                            name: part,
                            path: fullPath,
                            children: {},
                            notes: []
                        };
                    }
                    current = current[part].children;
                });
            });
            
            // Add notes to their folders
            this.notes.forEach(note => {
                if (!note.folder) {
                    // Root level note
                    if (!tree['__root__']) {
                        tree['__root__'] = {
                            name: '',
                            path: '',
                            children: {},
                            notes: []
                        };
                    }
                    tree['__root__'].notes.push(note);
                } else {
                    // Navigate to the folder and add note
                    const parts = note.folder.split('/');
                    let current = tree;
                    
                    for (let i = 0; i < parts.length; i++) {
                        if (!current[parts[i]]) {
                            current[parts[i]] = {
                                name: parts[i],
                                path: parts.slice(0, i + 1).join('/'),
                                children: {},
                                notes: []
                            };
                        }
                        if (i === parts.length - 1) {
                            current[parts[i]].notes.push(note);
                        } else {
                            current = current[parts[i]].children;
                        }
                    }
                }
            });
            
            // Sort all notes arrays alphabetically (create new sorted arrays for reactivity)
            const sortNotes = (obj) => {
                if (obj.notes && obj.notes.length > 0) {
                    // Create a new sorted array instead of mutating for Alpine reactivity
                    obj.notes = [...obj.notes].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
                }
                if (obj.children && Object.keys(obj.children).length > 0) {
                    Object.values(obj.children).forEach(child => sortNotes(child));
                }
            };
            
            // Sort notes in root (create new array for reactivity)
            if (tree['__root__'] && tree['__root__'].notes) {
                tree['__root__'].notes = [...tree['__root__'].notes].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
            }
            
            // Sort notes in all folders
            Object.values(tree).forEach(folder => {
                if (folder.path !== undefined) { // Skip __root__ as it was already sorted
                    sortNotes(folder);
                }
            });
            
            // Force Alpine reactivity by creating a new object reference
            this.folderTree = { ...tree };
        },
        
        // Render folder recursively (helper for deep nesting)
        renderFolderRecursive(folder, level = 0, isTopLevel = false) {
            if (!folder) return '';
            
            let html = '';
            const isExpanded = this.expandedFolders.has(folder.path);
            
            // Render this folder's header
            html += `
                <div>
                    <div 
                        draggable="true"
                        x-data="{}"
                        @dragstart="onFolderDragStart('${folder.path.replace(/'/g, "\\'")}', $event)"
                        @dragend="onFolderDragEnd()"
                        @dragover.prevent="dragOverFolder = '${folder.path.replace(/'/g, "\\'")}'"
                        @dragenter.prevent="dragOverFolder = '${folder.path.replace(/'/g, "\\'")}'"
                        @dragleave="dragOverFolder = null"
                        @drop.stop="onFolderDrop('${folder.path.replace(/'/g, "\\'")}' )"
                        class="folder-item px-3 py-3 mb-1 text-sm rounded transition-all relative"
                        style="color: var(--text-primary); cursor: pointer;"
                        :class="{
                            'border-2 border-dashed bg-accent-light': (draggedNote || draggedFolder) && dragOverFolder === '${folder.path.replace(/'/g, "\\'")}',
                            'border-2 border-dashed': (draggedNote || draggedFolder) && dragOverFolder !== '${folder.path.replace(/'/g, "\\'")}',
                            'border-2 border-transparent': !draggedNote && !draggedFolder
                        }"
                        :style="{
                            'border-color': (draggedNote || draggedFolder) && dragOverFolder === '${folder.path.replace(/'/g, "\\'")}'  ? 'var(--accent-primary)' : 'var(--border-secondary)',
                            'background-color': dragOverFolder === '${folder.path.replace(/'/g, "\\'")}'  ? 'var(--accent-light)' : ''
                        }"
                        @mouseover="if(!draggedNote && !draggedFolder) $el.style.backgroundColor='var(--bg-hover)'"
                        @mouseout="if(!draggedNote && !draggedFolder && dragOverFolder !== '${folder.path.replace(/'/g, "\\'")}'  ) $el.style.backgroundColor='transparent'"
                        @click="toggleFolder('${folder.path.replace(/'/g, "\\'")}')"
                    >
                        <div class="flex items-center gap-1">
                            <button 
                                class="flex-shrink-0 w-4 h-4 flex items-center justify-center"
                                style="color: var(--text-tertiary); cursor: pointer; transition: transform 0.2s; pointer-events: none; ${isExpanded ? 'transform: rotate(90deg);' : ''}"
                            >
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
                                    <path d="M6 4l4 4-4 4V4z"/>
                                </svg>
                            </button>
                            <span class="flex items-center gap-1 flex-1" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; pointer-events: none;">
                                <span>${folder.name}</span>
                                ${folder.notes.length === 0 && (!folder.children || Object.keys(folder.children).length === 0) ? '<span class="text-xs" style="color: var(--text-tertiary); font-weight: 400;">(empty)</span>' : ''}
                            </span>
                        </div>
                        <div class="hover-buttons flex gap-1 transition-opacity absolute right-2 top-1/2 transform -translate-y-1/2" style="opacity: 0; pointer-events: none; background: linear-gradient(to right, transparent, var(--bg-hover) 20%, var(--bg-hover)); padding-left: 20px;" @click.stop>
                            <button 
                                @click="createNote('${folder.path.replace(/'/g, "\\'")}')"
                                class="px-1.5 py-0.5 text-xs rounded hover:brightness-110"
                                style="background-color: var(--bg-tertiary); color: var(--text-secondary);"
                                title="New note here"
                            >📄</button>
                            <button 
                                @click="createFolder('${folder.path.replace(/'/g, "\\'")}')"
                                class="px-1.5 py-0.5 text-xs rounded hover:brightness-110"
                                style="background-color: var(--bg-tertiary); color: var(--text-secondary);"
                                title="New subfolder"
                            >📁</button>
                            <button 
                                @click="renameFolder('${folder.path.replace(/'/g, "\\'")}', '${folder.name.replace(/'/g, "\\'")}')"
                                class="px-1.5 py-0.5 text-xs rounded hover:brightness-110"
                                style="background-color: var(--bg-tertiary); color: var(--text-secondary);"
                                title="Rename folder"
                            >✏️</button>
                            <button 
                                @click="deleteFolder('${folder.path.replace(/'/g, "\\'")}', '${folder.name.replace(/'/g, "\\'")}')"
                                class="px-1 py-0.5 text-xs rounded hover:brightness-110"
                                style="color: var(--error);"
                                title="Delete folder"
                            >
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                                </svg>
                            </button>
                        </div>
                    </div>
            `;
            
            // If expanded, render folder contents (child folders + notes)
            if (isExpanded) {
                html += `<div class="folder-contents" style="padding-left: 12px;">`;
                
                // First, render child folders (if any)
                if (folder.children && Object.keys(folder.children).length > 0) {
                    const children = Object.entries(folder.children).sort((a, b) => 
                        a[1].name.toLowerCase().localeCompare(b[1].name.toLowerCase())
                    );
                    
                    children.forEach(([childKey, childFolder]) => {
                        html += this.renderFolderRecursive(childFolder, 0, false);
                    });
                }
                
                // Then, render notes in this folder (after subfolders)
                if (folder.notes && folder.notes.length > 0) {
                    folder.notes.forEach(note => {
                        const isCurrentNote = this.currentNote === note.path;
                        html += `
                            <div 
                                draggable="true"
                                x-data="{}"
                                @dragstart="onNoteDragStart('${note.path.replace(/'/g, "\\'")}', $event)"
                                @dragend="onNoteDragEnd()"
                                @click="loadNote('${note.path.replace(/'/g, "\\'")}')"
                                class="note-item px-3 py-2 mb-1 text-sm rounded relative border-2 border-transparent"
                                style="${isCurrentNote ? 'background-color: var(--accent-light); color: var(--accent-primary);' : 'color: var(--text-primary);'} cursor: pointer;"
                                @mouseover="if('${note.path}' !== currentNote) $el.style.backgroundColor='var(--bg-hover)'"
                                @mouseout="if('${note.path}' !== currentNote) $el.style.backgroundColor='transparent'"
                            >
                                <span class="truncate">${note.name}</span>
                                <button 
                                    @click.stop="deleteNote('${note.path.replace(/'/g, "\\'")}', '${note.name.replace(/'/g, "\\'")}')"
                                    class="note-delete-btn absolute right-2 top-1/2 transform -translate-y-1/2 px-1 py-0.5 text-xs rounded hover:brightness-110 transition-opacity"
                                    style="opacity: 0; color: var(--error);"
                                    title="Delete note"
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                                    </svg>
                                </button>
                            </div>
                        `;
                    });
                }
                
                html += `</div>`; // Close folder-contents
            }
            
            html += `</div>`; // Close folder wrapper
            return html;
        },
        
        // Toggle folder expansion
        toggleFolder(folderPath) {
            if (this.expandedFolders.has(folderPath)) {
                this.expandedFolders.delete(folderPath);
            } else {
                this.expandedFolders.add(folderPath);
            }
            // Force Alpine reactivity by creating new Set reference
            this.expandedFolders = new Set(this.expandedFolders);
            // Also trigger folderTree reactivity to re-render x-html
            this.folderTree = { ...this.folderTree };
        },
        
        // Check if folder is expanded
        isFolderExpanded(folderPath) {
            return this.expandedFolders.has(folderPath);
        },
        
        // Expand all folders
        expandAllFolders() {
            // Add all folder paths to expandedFolders
            this.allFolders.forEach(folder => {
                this.expandedFolders.add(folder);
            });
            // Force Alpine reactivity by creating new object reference (no rebuild needed)
            this.folderTree = { ...this.folderTree };
        },
        
        // Collapse all folders
        collapseAllFolders() {
            this.expandedFolders.clear();
            // Force Alpine reactivity by creating new object reference (no rebuild needed)
            this.folderTree = { ...this.folderTree };
        },
        
        // Expand folder tree to show a specific note
        expandFolderForNote(notePath) {
            // Extract folder path from note path
            // e.g., "folder1/folder2/note.md" -> ["folder1", "folder1/folder2"]
            const parts = notePath.split('/');
            
            // If note is in root, no folders to expand
            if (parts.length <= 1) return;
            
            // Remove the note name (last part)
            parts.pop();
            
            // Build and expand all parent folders
            let currentPath = '';
            parts.forEach((part, index) => {
                currentPath = index === 0 ? part : `${currentPath}/${part}`;
                this.expandedFolders.add(currentPath);
            });
            
            // Force Alpine reactivity by creating new object reference
            // This ensures the UI updates to show the expanded folders
            this.folderTree = { ...this.folderTree };
            
            // Also force a re-evaluation by modifying the Set (create new Set)
            const oldFolders = this.expandedFolders;
            this.expandedFolders = new Set(oldFolders);
        },
        
        // Scroll note into view in the sidebar navigation
        scrollNoteIntoView(notePath) {
            // Find the note element in the sidebar
            // Use a slight delay to ensure DOM is fully rendered with Alpine bindings applied
            setTimeout(() => {
                const sidebar = document.querySelector('.flex-1.overflow-y-auto.custom-scrollbar');
                if (!sidebar) return;
                
                const noteElements = sidebar.querySelectorAll('[class*="px-3 py-2 mb-1"]');
                let targetElement = null;
                const noteName = notePath.split('/').pop().replace('.md', '');
                
                // Find the element that corresponds to this note
                noteElements.forEach(el => {
                    // Check if this is a note element (not folder) by checking if it has the note name
                    if (el.textContent.trim().startsWith(noteName) || el.textContent.includes(noteName)) {
                        // Check computed style to see if it's highlighted
                        const computedStyle = window.getComputedStyle(el);
                        const bgColor = computedStyle.backgroundColor;
                        
                        // Check if background has the accent color (not transparent or default)
                        if (bgColor && bgColor !== 'rgba(0, 0, 0, 0)' && bgColor !== 'transparent' && !bgColor.includes('255, 255, 255')) {
                            targetElement = el;
                        }
                    }
                });
                
                // If found, scroll it into view
                if (targetElement) {
                    targetElement.scrollIntoView({ 
                        behavior: 'smooth', 
                        block: 'center',
                        inline: 'nearest'
                    });
                }
            }, 200); // Increased delay to ensure Alpine has finished rendering
        },
        
        // Drag and drop handlers
        onNoteDragStart(notePath, event) {
            // Check if Ctrl/Cmd is held for link mode
            if (event.ctrlKey || event.metaKey) {
                // Link mode: drag to create internal link
                this.draggedNoteForLink = notePath;
                event.dataTransfer.effectAllowed = 'link';
            } else {
                // Move mode: drag to move note
                this.draggedNote = notePath;
                event.dataTransfer.effectAllowed = 'move';
                // Make drag image semi-transparent
                if (event.target) {
                    event.target.style.opacity = '0.5';
                }
            }
        },
        
        onNoteDragEnd() {
            this.draggedNote = null;
            this.draggedNoteForLink = null;
            this.dragOverFolder = null;
            // Reset opacity of all note items
            document.querySelectorAll('.note-item').forEach(el => {
                el.style.opacity = '1';
            });
        },
        
        // Handle dragover on editor to show cursor position
        onEditorDragOver(event) {
            if (!this.draggedNoteForLink) return;
            
            // Update cursor position as user drags over text
            const textarea = event.target;
            const textLength = textarea.value.length;
            
            // Calculate approximate cursor position based on mouse position
            // This gives a rough idea of where the link will be inserted
            textarea.focus();
            
            // Try to set cursor at click position (works in most browsers)
            if (textarea.setSelectionRange && document.caretPositionFromPoint) {
                const pos = document.caretPositionFromPoint(event.clientX, event.clientY);
                if (pos && pos.offsetNode === textarea) {
                    textarea.setSelectionRange(pos.offset, pos.offset);
                }
            }
        },
        
        // Handle dragenter on editor
        onEditorDragEnter(event) {
            if (!this.draggedNoteForLink) return;
            event.preventDefault();
        },
        
        // Handle dragleave on editor
        onEditorDragLeave(event) {
            // Note: draggedNoteForLink will be cleared on dragend anyway
        },
        
        // Handle drop into editor to create internal link
        onEditorDrop(event) {
            event.preventDefault();
            
            if (!this.draggedNoteForLink) return;
            
            const notePath = this.draggedNoteForLink;
            const noteName = notePath.split('/').pop().replace('.md', '');
            
            // Create markdown link
            const link = `[${noteName}](${notePath})`;
            
            // Insert at cursor position
            const textarea = event.target;
            const cursorPos = textarea.selectionStart || 0;
            const textBefore = this.noteContent.substring(0, cursorPos);
            const textAfter = this.noteContent.substring(cursorPos);
            
            this.noteContent = textBefore + link + textAfter;
            
            // Move cursor after the link
            this.$nextTick(() => {
                textarea.selectionStart = textarea.selectionEnd = cursorPos + link.length;
                textarea.focus();
            });
            
            // Trigger autosave
            this.autoSave();
            
            this.draggedNoteForLink = null;
        },
        
        // Handle clicks on internal links in preview
        handleInternalLink(event) {
            // Check if clicked element is a link
            const link = event.target.closest('a');
            if (!link) return;
            
            const href = link.getAttribute('href');
            if (!href) return;
            
            // Check if it's an external link
            if (href.startsWith('http://') || href.startsWith('https://') || href.startsWith('//') || href.startsWith('mailto:')) {
                return; // Let external links work normally
            }
            
            // Prevent default navigation for internal links
            event.preventDefault();
            
            // Remove any anchor from the href (e.g., "note.md#section" -> "note.md")
            const notePath = href.split('#')[0];
            
            // Skip if it's just an anchor link
            if (!notePath) return;
            
            // Find the note by path
            const note = this.notes.find(n => n.path === notePath);
            if (note) {
                this.loadNote(notePath);
            } else {
                // Try to find by name (in case link uses just the note name)
                const noteByName = this.notes.find(n => n.name === notePath || n.name === notePath + '.md');
                if (noteByName) {
                    this.loadNote(noteByName.path);
                } else {
                    alert(`Note not found: ${notePath}`);
                }
            }
        },
        
        // Folder drag handlers
        onFolderDragStart(folderPath, event) {
            this.draggedFolder = folderPath;
            // Make drag image semi-transparent
            if (event && event.target) {
                event.target.style.opacity = '0.5';
            }
        },
        
        onFolderDragEnd() {
            this.draggedFolder = null;
            this.dragOverFolder = null;
            // Reset opacity of all folder items
            document.querySelectorAll('.folder-item').forEach(el => {
                el.style.opacity = '1';
            });
        },
        
        async onFolderDrop(targetFolderPath) {
            // Handle note drop into folder
            if (this.draggedNote) {
                const note = this.notes.find(n => n.path === this.draggedNote);
                if (!note) return;
                
                // Get note filename
                const filename = note.path.split('/').pop();
                const newPath = targetFolderPath ? `${targetFolderPath}/${filename}` : filename;
                
                if (newPath === this.draggedNote) {
                    this.draggedNote = null;
                    return;
                }
                
                try {
                    const response = await fetch('/api/notes/move', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            oldPath: this.draggedNote,
                            newPath: newPath
                        })
                    });
                    
                    if (response.ok) {
                        await this.loadNotes();
                        // Keep current note open if it was the moved note
                        if (this.currentNote === this.draggedNote) {
                            this.currentNote = newPath;
                        }
                    } else {
                        alert('Failed to move note.');
                    }
                } catch (error) {
                    console.error('Failed to move note:', error);
                    alert('Failed to move note.');
                }
                
                this.draggedNote = null;
                return;
            }
            
            // Handle folder drop into folder
            if (this.draggedFolder) {
                // Prevent dropping folder into itself or its subfolders
                if (targetFolderPath === this.draggedFolder || 
                    targetFolderPath.startsWith(this.draggedFolder + '/')) {
                    alert('Cannot move folder into itself or its subfolder.');
                    this.draggedFolder = null;
                    return;
                }
                
                const folderName = this.draggedFolder.split('/').pop();
                const newPath = targetFolderPath ? `${targetFolderPath}/${folderName}` : folderName;
                
                if (newPath === this.draggedFolder) {
                    this.draggedFolder = null;
                    return;
                }
                
                try {
                    const response = await fetch('/api/folders/move', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            oldPath: this.draggedFolder,
                            newPath: newPath
                        })
                    });
                    
                    if (response.ok) {
                        await this.loadNotes();
                        // Update current note path if it was in the moved folder
                        if (this.currentNote && this.currentNote.startsWith(this.draggedFolder + '/')) {
                            this.currentNote = this.currentNote.replace(this.draggedFolder, newPath);
                        }
                    } else {
                        alert('Failed to move folder.');
                    }
                } catch (error) {
                    console.error('Failed to move folder:', error);
                    alert('Failed to move folder.');
                }
                
                this.draggedFolder = null;
            }
        },
        
        // Load a specific note
        async loadNote(notePath, updateHistory = true, searchQuery = '') {
            try {
                // Close mobile sidebar when a note is selected
                this.mobileSidebarOpen = false;
                
                const response = await fetch(`/api/notes/${notePath}`);
                
                // Check if note exists
                if (!response.ok) {
                    if (response.status === 404) {
                        // Note not found - silently redirect to home
                        window.history.replaceState({}, '', '/');
                        this.currentNote = '';
                        this.noteContent = '';
                        return;
                    }
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                
                this.currentNote = notePath;
                this.noteContent = data.content;
                this.currentNoteName = notePath.split('/').pop().replace('.md', '');
                this.lastSaved = false;
                
                // Initialize undo/redo history for this note
                this.undoHistory = [data.content];
                this.redoHistory = [];
                
                // Update browser URL and history
                if (updateHistory) {
                    // Encode the path properly (spaces become %20, etc.)
                    const pathWithoutExtension = notePath.replace('.md', '');
                    // Encode each path segment to handle special characters
                    const encodedPath = pathWithoutExtension.split('/').map(segment => encodeURIComponent(segment)).join('/');
                    let url = `/${encodedPath}`;
                    // Add search query parameter if present
                    if (searchQuery) {
                        url += `?search=${encodeURIComponent(searchQuery)}`;
                    }
                    window.history.pushState(
                        { notePath: notePath, searchQuery: searchQuery },
                        '',
                        url
                    );
                }
                
                // Calculate stats if plugin enabled
                if (this.statsPluginEnabled) {
                    this.calculateStats();
                }
                
                // Store search query for highlighting
                if (searchQuery) {
                    this.currentSearchHighlight = searchQuery;
                } else {
                    // Clear highlights if no search query
                    this.currentSearchHighlight = '';
                }
                
                // Expand folder tree to show the loaded note
                this.expandFolderForNote(notePath);
                
                // Use $nextTick twice to ensure Alpine.js has time to:
                // 1. First tick: expand folders and update DOM
                // 2. Second tick: highlight the note and setup everything else
                this.$nextTick(() => {
                    this.$nextTick(() => {
                        this.refreshDOMCache();
                        this.setupScrollSync();
                        this.scrollToTop();
                        
                        // Apply or clear search highlighting
                        if (searchQuery) {
                            // Pass true to focus editor when loading from search result
                            this.highlightSearchTerm(searchQuery, true);
                        } else {
                            this.clearSearchHighlights();
                        }
                        
                        // Scroll note into view in sidebar if needed
                        this.scrollNoteIntoView(notePath);
                    });
                });
                
            } catch (error) {
                ErrorHandler.handle('load note', error);
            }
        },
        
        // Load note from URL path
        loadNoteFromURL() {
            // Get path from URL (e.g., /folder/note or /note)
            const path = window.location.pathname;
            
            // Skip if root path or static assets
            if (path === '/' || path.startsWith('/static/') || path.startsWith('/api/')) {
                return;
            }
            
            // Remove leading slash, decode URL encoding (e.g., %20 -> space), and add .md extension
            const decodedPath = decodeURIComponent(path.substring(1));
            const notePath = decodedPath + '.md';
            
            // Parse query string for search parameter
            const urlParams = new URLSearchParams(window.location.search);
            const searchParam = urlParams.get('search');
            
            // Try to load the note directly - the backend will handle 404 if it doesn't exist
            // This is more robust than checking the frontend notes list
            this.loadNote(notePath, false, searchParam || '');
            
            // If there's a search parameter, populate the search box and trigger search
            if (searchParam) {
                this.searchQuery = searchParam;
                // Trigger search to populate results list
                this.searchNotes();
            }
        },
        
        // Highlight search term in editor and preview
        highlightSearchTerm(query, focusEditor = false) {
            if (!query || !query.trim()) {
                this.clearSearchHighlights();
                return;
            }
            
            const searchTerm = query.trim();
            
            // Highlight in editor (textarea)
            this.highlightInEditor(searchTerm, focusEditor);
            
            // Highlight in preview (rendered HTML)
            this.highlightInPreview(searchTerm);
        },
        
        // Highlight search term in the editor textarea
        highlightInEditor(searchTerm, shouldFocus = false) {
            const editor = this._domCache.editor || document.getElementById('editor');
            if (!editor) return;
            
            // For textarea, we can't directly highlight text, but we can scroll to first match
            const content = editor.value;
            const lowerContent = content.toLowerCase();
            const lowerTerm = searchTerm.toLowerCase();
            const index = lowerContent.indexOf(lowerTerm);
            
            if (index !== -1) {
                // Calculate line number to scroll to
                const textBefore = content.substring(0, index);
                const lineNumber = textBefore.split('\n').length;
                
                // Scroll to approximate position
                const lineHeight = 20; // Approximate line height in pixels
                editor.scrollTop = (lineNumber - 5) * lineHeight; // Scroll a bit above to show context
                
                // Only focus and select if explicitly requested (e.g., from search result click)
                if (shouldFocus) {
                    editor.focus();
                    editor.setSelectionRange(index, index + searchTerm.length);
                    
                    // Blur immediately so the selection stays visible but editor isn't focused
                    setTimeout(() => editor.blur(), 100);
                }
            }
        },
        
        // Highlight search term in the preview pane
        highlightInPreview(searchTerm) {
            const preview = document.querySelector('.markdown-preview');
            if (!preview) return;
            
            // Remove existing highlights
            this.clearSearchHighlights();
            
            // Create a tree walker to find all text nodes
            const walker = document.createTreeWalker(
                preview,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );
            
            const textNodes = [];
            let node;
            while (node = walker.nextNode()) {
                // Skip code blocks and pre tags
                if (node.parentElement.tagName === 'CODE' || 
                    node.parentElement.tagName === 'PRE') {
                    continue;
                }
                textNodes.push(node);
            }
            
            const lowerTerm = searchTerm.toLowerCase();
            let matchIndex = 0;
            
            // Highlight matches in text nodes
            textNodes.forEach(textNode => {
                const text = textNode.textContent;
                const lowerText = text.toLowerCase();
                
                if (lowerText.includes(lowerTerm)) {
                    const fragment = document.createDocumentFragment();
                    let lastIndex = 0;
                    let index;
                    
                    while ((index = lowerText.indexOf(lowerTerm, lastIndex)) !== -1) {
                        // Add text before match
                        if (index > lastIndex) {
                            fragment.appendChild(
                                document.createTextNode(text.substring(lastIndex, index))
                            );
                        }
                        
                        // Add highlighted match
                        const mark = document.createElement('mark');
                        mark.className = 'search-highlight';
                        mark.setAttribute('data-match-index', matchIndex);
                        mark.textContent = text.substring(index, index + searchTerm.length);
                        mark.style.padding = '2px 4px';
                        mark.style.borderRadius = '3px';
                        mark.style.transition = 'all 0.2s';
                        
                        // Style first match as active, others as inactive
                        if (matchIndex === 0) {
                            mark.style.backgroundColor = 'var(--accent-primary)';
                            mark.style.color = 'white';
                            mark.classList.add('active-match');
                        } else {
                            mark.style.backgroundColor = 'rgba(255, 193, 7, 0.4)';
                            mark.style.color = 'var(--text-primary)';
                        }
                        
                        fragment.appendChild(mark);
                        matchIndex++;
                        
                        lastIndex = index + searchTerm.length;
                    }
                    
                    // Add remaining text
                    if (lastIndex < text.length) {
                        fragment.appendChild(
                            document.createTextNode(text.substring(lastIndex))
                        );
                    }
                    
                    // Replace text node with highlighted fragment
                    textNode.parentNode.replaceChild(fragment, textNode);
                }
            });
            
            // Update total matches and reset current index
            this.totalMatches = matchIndex;
            this.currentMatchIndex = matchIndex > 0 ? 0 : -1;
            
            // Scroll to first match
            if (this.totalMatches > 0) {
                this.scrollToMatch(0);
            }
        },
        
        // Navigate to next search match
        nextMatch() {
            if (this.totalMatches === 0) return;
            
            this.currentMatchIndex = (this.currentMatchIndex + 1) % this.totalMatches;
            this.scrollToMatch(this.currentMatchIndex);
        },
        
        // Navigate to previous search match
        previousMatch() {
            if (this.totalMatches === 0) return;
            
            this.currentMatchIndex = (this.currentMatchIndex - 1 + this.totalMatches) % this.totalMatches;
            this.scrollToMatch(this.currentMatchIndex);
        },
        
        // Scroll to a specific match index
        scrollToMatch(index) {
            const preview = document.querySelector('.markdown-preview');
            if (!preview) return;
            
            const allMatches = preview.querySelectorAll('mark.search-highlight');
            if (index < 0 || index >= allMatches.length) return;
            
            // Update styling - make current match prominent
            allMatches.forEach((mark, i) => {
                if (i === index) {
                    mark.style.backgroundColor = 'var(--accent-primary)';
                    mark.style.color = 'white';
                    mark.classList.add('active-match');
                } else {
                    mark.style.backgroundColor = 'rgba(255, 193, 7, 0.4)';
                    mark.style.color = 'var(--text-primary)';
                    mark.classList.remove('active-match');
                }
            });
            
            // Scroll to the match
            const targetMatch = allMatches[index];
            const previewContainer = this._domCache.previewContainer;
            if (previewContainer && targetMatch) {
                const elementTop = targetMatch.offsetTop;
                previewContainer.scrollTop = elementTop - 100; // Scroll with some offset
            }
        },
        
        // Clear search highlights
        clearSearchHighlights() {
            const preview = document.querySelector('.markdown-preview');
            if (!preview) return;
            
            const highlights = preview.querySelectorAll('mark.search-highlight');
            highlights.forEach(mark => {
                const text = document.createTextNode(mark.textContent);
                mark.parentNode.replaceChild(text, mark);
            });
            
            // Normalize text nodes to merge adjacent text nodes
            preview.normalize();
            
            // Reset match counters
            this.totalMatches = 0;
            this.currentMatchIndex = -1;
        },
        
        // =====================================================
        // DROPDOWN MENU SYSTEM
        // =====================================================
        
        toggleNewDropdown() {
            this.showNewDropdown = !this.showNewDropdown;
        },
        
        closeDropdown() {
            this.showNewDropdown = false;
        },
        
        // =====================================================
        // UNIFIED CREATION FUNCTIONS (reusable from anywhere)
        // =====================================================
        
        async createNote(folderPath = '') {
            this.closeDropdown();
            
            const promptText = folderPath 
                ? `Create note in "${folderPath}".\nEnter note name:`
                : 'Enter note name (you can use folder/name):';
            
            const noteName = prompt(promptText);
            if (!noteName) return;
            
            const sanitizedName = noteName.trim().replace(/[^a-zA-Z0-9-_\s\/]/g, '');
            if (!sanitizedName) {
                alert('Invalid note name.');
                return;
            }
            
            let notePath;
            if (folderPath) {
                notePath = `${folderPath}/${sanitizedName}.md`;
            } else {
                notePath = sanitizedName.endsWith('.md') ? sanitizedName : `${sanitizedName}.md`;
            }
            
            // CRITICAL: Check if note already exists
            const existingNote = this.notes.find(note => note.path === notePath);
            if (existingNote) {
                alert(`A note named "${sanitizedName}" already exists in this location.\nPlease choose a different name.`);
                return;
            }
            
            try {
                const response = await fetch(`/api/notes/${notePath}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: '' })
                });
                
                if (response.ok) {
                    if (folderPath) {
                        this.expandedFolders.add(folderPath);
                    }
                    await this.loadNotes();
                    await this.loadNote(notePath);
                } else {
                    ErrorHandler.handle('create note', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('create note', error);
            }
        },
        
        async createFolder(parentPath = '') {
            this.closeDropdown();
            
            const promptText = parentPath 
                ? `Create subfolder in "${parentPath}".\nEnter folder name:`
                : 'Create new folder.\nEnter folder path (e.g., "Projects" or "Work/2025"):';
            
            const folderName = prompt(promptText);
            if (!folderName) return;
            
            const sanitizedName = folderName.trim().replace(/[^a-zA-Z0-9-_\s\/]/g, '');
            if (!sanitizedName) {
                alert('Invalid folder name.');
                return;
            }
            
            const folderPath = parentPath ? `${parentPath}/${sanitizedName}` : sanitizedName;
            
            // Check if folder already exists
            const existingFolder = this.allFolders.find(folder => folder === folderPath);
            if (existingFolder) {
                alert(`A folder named "${sanitizedName}" already exists in this location.\nPlease choose a different name.`);
                return;
            }
            
            try {
                const response = await fetch('/api/folders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: folderPath })
                });
                
                if (response.ok) {
                    if (parentPath) {
                        this.expandedFolders.add(parentPath);
                    }
                    this.expandedFolders.add(folderPath);
                    await this.loadNotes();
                } else {
                    ErrorHandler.handle('create folder', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('create folder', error);
            }
        },
        
        // Rename a folder
        async renameFolder(folderPath, currentName) {
            const newName = prompt(`Rename folder "${currentName}" to:`, currentName);
            if (!newName || newName === currentName) return;
            
            const sanitizedName = newName.trim().replace(/[^a-zA-Z0-9-_\s]/g, '');
            if (!sanitizedName) {
                alert('Invalid folder name.');
                return;
            }
            
            // Calculate new path
            const pathParts = folderPath.split('/');
            pathParts[pathParts.length - 1] = sanitizedName;
            const newPath = pathParts.join('/');
            
            try {
                const response = await fetch('/api/folders/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        oldPath: folderPath,
                        newPath: newPath
                    })
                });
                
                if (response.ok) {
                    // Update expanded folders state
                    if (this.expandedFolders.has(folderPath)) {
                        this.expandedFolders.delete(folderPath);
                        this.expandedFolders.add(newPath);
                    }
                    
                    // Update current note path if it's in the renamed folder
                    if (this.currentNote && this.currentNote.startsWith(folderPath + '/')) {
                        this.currentNote = this.currentNote.replace(folderPath, newPath);
                    }
                    
                    await this.loadNotes();
                } else {
                    ErrorHandler.handle('rename folder', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('rename folder', error);
            }
        },
        
        // Delete folder
        async deleteFolder(folderPath, folderName) {
            const confirmation = confirm(
                `⚠️ WARNING ⚠️\n\n` +
                `Are you sure you want to delete the folder "${folderName}"?\n\n` +
                `This will PERMANENTLY delete:\n` +
                `• All notes inside this folder\n` +
                `• All subfolders and their contents\n\n` +
                `This action CANNOT be undone!`
            );
            
            if (!confirmation) return;
            
            try {
                const response = await fetch(`/api/folders/${encodeURIComponent(folderPath)}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                if (response.ok) {
                    // Remove from expanded folders
                    this.expandedFolders.delete(folderPath);
                    
                    // Clear current note if it was in the deleted folder
                    if (this.currentNote && this.currentNote.startsWith(folderPath + '/')) {
                        this.currentNote = '';
                        this.noteContent = '';
                    }
                    
                    await this.loadNotes();
                } else {
                    ErrorHandler.handle('delete folder', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('delete folder', error);
            }
        },
        
        // Auto-save with debounce
        autoSave() {
            if (this.saveTimeout) {
                clearTimeout(this.saveTimeout);
            }
            
            this.lastSaved = false;
            
            // Push to undo history (but not during undo/redo operations)
            if (!this.isUndoRedo) {
                this.pushToHistory();
            }
            
            // Calculate stats in real-time if plugin enabled
            if (this.statsPluginEnabled) {
                this.calculateStats();
            }
            
            this.saveTimeout = setTimeout(() => {
                this.saveNote();
            }, CONFIG.AUTOSAVE_DELAY);
        },
        
        // Push current content to undo history
        pushToHistory() {
            // Only push if content actually changed
            if (this.undoHistory.length > 0 && 
                this.undoHistory[this.undoHistory.length - 1] === this.noteContent) {
                return;
            }
            
            this.undoHistory.push(this.noteContent);
            
            // Limit history size
            if (this.undoHistory.length > this.maxHistorySize) {
                this.undoHistory.shift();
            }
            
            // Clear redo history when new change is made
            this.redoHistory = [];
        },
        
        // Undo last change
        undo() {
            if (!this.currentNote || this.undoHistory.length <= 1) return;
            
            // Pop current state to redo history
            const currentContent = this.undoHistory.pop();
            this.redoHistory.push(currentContent);
            
            // Get previous state
            const previousContent = this.undoHistory[this.undoHistory.length - 1];
            
            // Apply previous state
            this.isUndoRedo = true;
            this.noteContent = previousContent;
            
            // Recalculate stats with new content
            if (this.statsPluginEnabled) {
                this.calculateStats();
            }
            
            // Save the undone state
            this.$nextTick(() => {
                this.saveNote();
                this.isUndoRedo = false;
            });
        },
        
        // Redo last undone change
        redo() {
            if (!this.currentNote || this.redoHistory.length === 0) return;
            
            // Pop from redo history
            const nextContent = this.redoHistory.pop();
            
            // Push to undo history
            this.undoHistory.push(nextContent);
            
            // Apply next state
            this.isUndoRedo = true;
            this.noteContent = nextContent;
            
            // Recalculate stats with new content
            if (this.statsPluginEnabled) {
                this.calculateStats();
            }
            
            // Save the redone state
            this.$nextTick(() => {
                this.saveNote();
                this.isUndoRedo = false;
            });
        },
        
        // Save current note
        async saveNote() {
            if (!this.currentNote) return;
            
            this.isSaving = true;
            
            try {
                const response = await fetch(`/api/notes/${this.currentNote}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: this.noteContent })
                });
                
                if (response.ok) {
                    this.lastSaved = true;
                    
                    // Update only the modified timestamp for the current note (no full reload needed)
                    const note = this.notes.find(n => n.path === this.currentNote);
                    if (note) {
                        note.modified = new Date().toISOString();
                    }
                    
                    // Hide "saved" indicator
                    setTimeout(() => {
                        this.lastSaved = false;
                    }, CONFIG.SAVE_INDICATOR_DURATION);
                } else {
                    ErrorHandler.handle('save note', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('save note', error);
            } finally {
                this.isSaving = false;
            }
        },
        
        // Rename current note
        async renameNote() {
            if (!this.currentNote) return;
            
            const oldPath = this.currentNote;
            const newName = this.currentNoteName.trim();
            
            if (!newName) {
                alert('Note name cannot be empty.');
                return;
            }
            
            const folder = oldPath.split('/').slice(0, -1).join('/');
            const newPath = folder ? `${folder}/${newName}.md` : `${newName}.md`;
            
            if (oldPath === newPath) return;
            
            // Create new note with same content
            try {
                const response = await fetch(`/api/notes/${newPath}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: this.noteContent })
                });
                
                if (response.ok) {
                    // Delete old note
                    await fetch(`/api/notes/${oldPath}`, { method: 'DELETE' });
                    
                    this.currentNote = newPath;
                    await this.loadNotes();
                } else {
                    ErrorHandler.handle('rename note', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('rename note', error);
            }
        },
        
        // Delete current note
        async deleteCurrentNote() {
            if (!this.currentNote) return;
            
            if (!confirm(`Delete "${this.currentNoteName}"?`)) return;
            
            try {
                const response = await fetch(`/api/notes/${this.currentNote}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    this.currentNote = '';
                    this.noteContent = '';
                    this.currentNoteName = '';
                    await this.loadNotes();
                } else {
                    ErrorHandler.handle('delete note', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('delete note', error);
            }
        },
        
        // Delete any note from sidebar
        async deleteNote(notePath, noteName) {
            if (!confirm(`Delete "${noteName}"?`)) return;
            
            try {
                const response = await fetch(`/api/notes/${notePath}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    // If the deleted note is currently open, clear it
                    if (this.currentNote === notePath) {
                        this.currentNote = '';
                        this.noteContent = '';
                        this.currentNoteName = '';
                        // Redirect to root
                        window.history.replaceState({}, '', '/');
                    }
                    
                    await this.loadNotes();
                } else {
                    ErrorHandler.handle('delete note', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('delete note', error);
            }
        },
        
        // Search notes
        async searchNotes() {
            if (!this.searchQuery.trim()) {
                this.searchResults = [];
                this.currentSearchHighlight = '';
                this.clearSearchHighlights();
                return;
            }
            
            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(this.searchQuery)}`);
                const data = await response.json();
                this.searchResults = data.results;
                
                // If a note is currently open, highlight the search term in real-time
                if (this.currentNote && this.noteContent) {
                    this.currentSearchHighlight = this.searchQuery;
                    this.$nextTick(() => {
                        // Don't focus editor during real-time search (false)
                        this.highlightSearchTerm(this.searchQuery, false);
                    });
                }
            } catch (error) {
                console.error('Search failed:', error);
            }
        },
        
        // Trigger MathJax typesetting after DOM update
        typesetMath() {
            if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
                // Use a small delay to ensure DOM is updated
                setTimeout(() => {
                    const previewContent = document.querySelector('.markdown-preview');
                    if (previewContent) {
                        MathJax.typesetPromise([previewContent]).catch((err) => {
                            console.error('MathJax typesetting failed:', err);
                        });
                    }
                }, 10);
            }
        },
        
        // Render Mermaid diagrams
        async renderMermaid() {
            if (typeof window.mermaid === 'undefined') {
                console.warn('Mermaid not loaded yet');
                return;
            }
            
            // Use requestAnimationFrame for better performance than setTimeout
            requestAnimationFrame(async () => {
                const previewContent = document.querySelector('.markdown-preview');
                if (!previewContent) return;
                
                // Get the appropriate theme based on current app theme
                const themeType = this.getThemeType();
                const mermaidTheme = themeType === 'light' ? 'default' : 'dark';
                
                // Only reinitialize if theme changed (performance optimization)
                if (this.lastMermaidTheme !== mermaidTheme) {
                    window.mermaid.initialize({ 
                        startOnLoad: false,
                        theme: mermaidTheme,
                        securityLevel: 'strict', // Use strict for better security
                        fontFamily: 'inherit'
                    });
                    this.lastMermaidTheme = mermaidTheme;
                }
                
                // Find all code blocks with language 'mermaid'
                const mermaidBlocks = previewContent.querySelectorAll('pre code.language-mermaid');
                
                // Early return if no diagrams to render
                if (mermaidBlocks.length === 0) return;
                
                for (let i = 0; i < mermaidBlocks.length; i++) {
                    const block = mermaidBlocks[i];
                    const pre = block.parentElement;
                    
                    // Skip if already rendered (performance optimization)
                    if (pre.querySelector('.mermaid-rendered')) continue;
                    
                    try {
                        const code = block.textContent;
                        const id = `mermaid-diagram-${Date.now()}-${i}`;
                        
                        // Render the diagram
                        const { svg } = await window.mermaid.render(id, code);
                        
                        // Create a container for the rendered diagram
                        const container = document.createElement('div');
                        container.className = 'mermaid-rendered';
                        container.style.cssText = 'background-color: transparent; padding: 20px; text-align: center; overflow-x: auto;';
                        container.innerHTML = svg;
                        // Store original code for theme re-rendering
                        container.dataset.originalCode = code;
                        
                        // Replace the code block with the rendered diagram
                        pre.parentElement.replaceChild(container, pre);
                    } catch (error) {
                        console.error('Mermaid rendering error:', error);
                        // Add error indicator to the code block
                        const errorMsg = document.createElement('div');
                        errorMsg.style.cssText = 'color: var(--error); padding: 10px; border-left: 3px solid var(--error); margin-top: 10px;';
                        errorMsg.textContent = `⚠️ Mermaid diagram error: ${error.message}`;
                        pre.parentElement.insertBefore(errorMsg, pre.nextSibling);
                    }
                }
            });
        },
        
        // Get current theme type (light or dark)
        // Returns: 'light' or 'dark'
        // Used by features that need to adapt to theme brightness (e.g., Mermaid diagrams, Chart.js)
        getThemeType() {
            // Handle system theme
            if (this.currentTheme === 'system') {
                const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                return isDark ? 'dark' : 'light';
            }
            
            // Try to get theme type from loaded theme metadata
            const currentThemeData = this.availableThemes.find(t => t.id === this.currentTheme);
            if (currentThemeData && currentThemeData.type) {
                // Use metadata from theme file (light or dark)
                return currentThemeData.type; // Already 'light' or 'dark'
            }
            
            // Backward compatibility: fallback to hardcoded map if metadata not available
            const fallbackMap = {
                'light': 'light',
                'vs-blue': 'light'
            };
            
            return fallbackMap[this.currentTheme] || 'dark';
        },
        
        
        // Computed property for rendered markdown
        get renderedMarkdown() {
            if (!this.noteContent) return '<p style="color: var(--text-tertiary);">Nothing to preview yet...</p>';
            
            // Configure marked with syntax highlighting
            marked.setOptions({
                breaks: true,
                gfm: true,
                highlight: function(code, lang) {
                    if (lang && hljs.getLanguage(lang)) {
                        try {
                            return hljs.highlight(code, { language: lang }).value;
                        } catch (err) {
                            console.error('Highlight error:', err);
                        }
                    }
                    return hljs.highlightAuto(code).value;
                }
            });
            
            // Convert wiki-style links [[link]] to HTML links
            let content = this.noteContent.replace(/\[\[([^\]]+)\]\]/g, (match, linkText) => {
                return `<a href="#" style="color: var(--accent-primary);" onclick="return false;">[[${linkText}]]</a>`;
            });
            
            // Parse markdown
            let html = marked.parse(content);
            
            // Post-process: Add target="_blank" to external links
            // Parse as DOM to safely manipulate
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html;
            
            // Find all links
            const links = tempDiv.querySelectorAll('a');
            links.forEach(link => {
                const href = link.getAttribute('href');
                if (href && typeof href === 'string') {
                    // Check if it's an external link
                    const isExternal = href.indexOf('http://') === 0 || 
                                      href.indexOf('https://') === 0 || 
                                      href.indexOf('//') === 0;
                    
                    if (isExternal) {
                        link.setAttribute('target', '_blank');
                        link.setAttribute('rel', 'noopener noreferrer');
                    }
                }
            });
            
            html = tempDiv.innerHTML;
            
            // Trigger MathJax rendering after DOM updates
            this.typesetMath();
            
            // Render Mermaid diagrams
            this.renderMermaid();
            
            // Apply syntax highlighting and add copy buttons to code blocks
            setTimeout(() => {
                // Use cached reference if available, otherwise query
                const previewEl = this._domCache.previewContent || document.querySelector('.markdown-preview');
                if (previewEl) {
                    // Exclude code blocks that are rendered by other tools (e.g., Mermaid diagrams)
                    // Note: MathJax uses $$...$$ delimiters (not code blocks) so no exclusion needed
                    previewEl.querySelectorAll('pre code:not(.language-mermaid)').forEach((block) => {
                        // Apply syntax highlighting
                        if (!block.classList.contains('hljs')) {
                            hljs.highlightElement(block);
                        }
                        
                        // Add copy button if not already present
                        const pre = block.parentElement;
                        if (pre && !pre.querySelector('.copy-code-button')) {
                            this.addCopyButtonToCodeBlock(pre);
                        }
                    });
                }
            }, 0);
            
            return html;
        },
        
        // Refresh DOM element cache
        refreshDOMCache() {
            this._domCache.editor = document.querySelector('.editor-textarea');
            this._domCache.previewContent = document.querySelector('.markdown-preview');
            this._domCache.previewContainer = this._domCache.previewContent ? this._domCache.previewContent.parentElement : null;
        },
        
        // Add copy button to code block
        addCopyButtonToCodeBlock(preElement) {
            // Create copy button
            const button = document.createElement('button');
            button.className = 'copy-code-button';
            button.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
            `;
            button.title = 'Copy to clipboard';
            
            // Style the button
            button.style.position = 'absolute';
            button.style.top = '8px';
            button.style.right = '8px';
            button.style.padding = '6px';
            button.style.backgroundColor = 'rgba(0, 0, 0, 0.6)';
            button.style.border = 'none';
            button.style.borderRadius = '4px';
            button.style.cursor = 'pointer';
            button.style.opacity = '0';
            button.style.transition = 'opacity 0.2s, background-color 0.2s';
            button.style.color = 'white';
            button.style.display = 'flex';
            button.style.alignItems = 'center';
            button.style.justifyContent = 'center';
            button.style.zIndex = '10';
            
            // Style the pre element to be relative
            preElement.style.position = 'relative';
            
            // Show button on hover
            preElement.addEventListener('mouseenter', () => {
                button.style.opacity = '1';
            });
            
            preElement.addEventListener('mouseleave', () => {
                button.style.opacity = '0';
            });
            
            // Copy to clipboard on click
            button.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                
                const codeElement = preElement.querySelector('code');
                if (!codeElement) return;
                
                const code = codeElement.textContent;
                
                try {
                    await navigator.clipboard.writeText(code);
                    
                    // Visual feedback - change icon to checkmark
                    button.innerHTML = `
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                    `;
                    button.style.backgroundColor = 'rgba(34, 197, 94, 0.8)';
                    button.title = 'Copied!';
                    
                    // Reset after 2 seconds
                    setTimeout(() => {
                        button.innerHTML = `
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                            </svg>
                        `;
                        button.style.backgroundColor = 'rgba(0, 0, 0, 0.6)';
                        button.title = 'Copy to clipboard';
                    }, 2000);
                } catch (err) {
                    console.error('Failed to copy code:', err);
                    
                    // Fallback for older browsers
                    const textArea = document.createElement('textarea');
                    textArea.value = code;
                    textArea.style.position = 'fixed';
                    textArea.style.left = '-999999px';
                    document.body.appendChild(textArea);
                    textArea.select();
                    
                    try {
                        document.execCommand('copy');
                        button.innerHTML = `
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                        `;
                        button.style.backgroundColor = 'rgba(34, 197, 94, 0.8)';
                        setTimeout(() => {
                            button.innerHTML = `
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                </svg>
                            `;
                            button.style.backgroundColor = 'rgba(0, 0, 0, 0.6)';
                        }, 2000);
                    } catch (fallbackErr) {
                        console.error('Fallback copy failed:', fallbackErr);
                    }
                    
                    document.body.removeChild(textArea);
                }
            });
            
            // Add button to pre element
            preElement.appendChild(button);
        },
        
        // Setup scroll synchronization
        setupScrollSync() {
            // Use cached references (refresh if not available)
            if (!this._domCache.editor || !this._domCache.previewContainer) {
                this.refreshDOMCache();
            }
            
            const editor = this._domCache.editor;
            const preview = this._domCache.previewContainer;
            
            if (!editor || !preview) {
                // If elements don't exist yet, retry with limit
                if (!this._setupScrollSyncRetries) this._setupScrollSyncRetries = 0;
                if (this._setupScrollSyncRetries < CONFIG.SCROLL_SYNC_MAX_RETRIES) {
                    this._setupScrollSyncRetries++;
                    setTimeout(() => this.setupScrollSync(), CONFIG.SCROLL_SYNC_RETRY_INTERVAL);
                } else {
                    console.warn(`setupScrollSync: Failed to find editor/preview elements after ${CONFIG.SCROLL_SYNC_MAX_RETRIES} retries`);
                }
                return;
            }
            
            // Reset retry counter on success
            this._setupScrollSyncRetries = 0;
            
            // Remove old listeners if they exist
            if (this._editorScrollHandler) {
                editor.removeEventListener('scroll', this._editorScrollHandler);
            }
            if (this._previewScrollHandler) {
                preview.removeEventListener('scroll', this._previewScrollHandler);
            }
            
            // Create new scroll handlers
            this._editorScrollHandler = () => {
                if (this.isScrolling) {
                    this.isScrolling = false;
                    return;
                }
                
                const scrollableHeight = editor.scrollHeight - editor.clientHeight;
                if (scrollableHeight <= 0) return; // No scrolling needed
                
                const scrollPercentage = editor.scrollTop / scrollableHeight;
                const previewScrollableHeight = preview.scrollHeight - preview.clientHeight;
                
                if (previewScrollableHeight > 0) {
                    this.isScrolling = true;
                    preview.scrollTop = scrollPercentage * previewScrollableHeight;
                }
            };
            
            this._previewScrollHandler = () => {
                if (this.isScrolling) {
                    this.isScrolling = false;
                    return;
                }
                
                const scrollableHeight = preview.scrollHeight - preview.clientHeight;
                if (scrollableHeight <= 0) return; // No scrolling needed
                
                const scrollPercentage = preview.scrollTop / scrollableHeight;
                const editorScrollableHeight = editor.scrollHeight - editor.clientHeight;
                
                if (editorScrollableHeight > 0) {
                    this.isScrolling = true;
                    editor.scrollTop = scrollPercentage * editorScrollableHeight;
                }
            };
            
            // Attach new listeners
            editor.addEventListener('scroll', this._editorScrollHandler);
            preview.addEventListener('scroll', this._previewScrollHandler);
        },
        
        // Check if stats plugin is enabled
        async checkStatsPlugin() {
            try {
                const response = await fetch('/api/plugins');
                const data = await response.json();
                const statsPlugin = data.plugins.find(p => p.id === 'note_stats');
                this.statsPluginEnabled = statsPlugin && statsPlugin.enabled;
                
                // Calculate stats for current note if enabled
                if (this.statsPluginEnabled && this.noteContent) {
                    this.calculateStats();
                }
            } catch (error) {
                console.error('Failed to check stats plugin:', error);
                this.statsPluginEnabled = false;
            }
        },
        
        // Calculate note statistics (client-side)
        calculateStats() {
            if (!this.statsPluginEnabled || !this.noteContent) {
                this.noteStats = null;
                return;
            }
            
            const content = this.noteContent;
            
            // Word count
            const words = (content.match(/\S+/g) || []).length;
            
            // Character count
            const chars = content.replace(/\s/g, '').length;
            const totalChars = content.length;
            
            // Reading time (200 words per minute)
            const readingTime = Math.max(1, Math.round(words / 200));
            
            // Line count
            const lines = content.split('\n').length;
            
            // Paragraph count
            const paragraphs = content.split('\n\n').filter(p => p.trim()).length;
            
            // Link count
            const linkMatches = content.match(/\[([^\]]+)\]\(([^\)]+)\)/g) || [];
            const links = linkMatches.length;
            const internalLinks = linkMatches.filter(l => l.includes('.md')).length;
            
            // Code blocks
            const codeBlocks = (content.match(/```[\s\S]*?```/g) || []).length;
            const inlineCode = (content.match(/`[^`]+`/g) || []).length;
            
            // Headings
            const h1 = (content.match(/^# /gm) || []).length;
            const h2 = (content.match(/^## /gm) || []).length;
            const h3 = (content.match(/^### /gm) || []).length;
            
            // Tasks
            const totalTasks = (content.match(/- \[[ x]\]/gi) || []).length;
            const completedTasks = (content.match(/- \[x\]/gi) || []).length;
            const pendingTasks = totalTasks - completedTasks;
            const completionRate = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0;
            
            // Images
            const images = (content.match(/!\[([^\]]*)\]\(([^\)]+)\)/g) || []).length;
            
            // Blockquotes
            const blockquotes = (content.match(/^> /gm) || []).length;
            
            this.noteStats = {
                words,
                characters: chars,
                total_characters: totalChars,
                reading_time_minutes: readingTime,
                lines,
                paragraphs,
                links,
                internal_links: internalLinks,
                external_links: links - internalLinks,
                code_blocks: codeBlocks,
                inline_code: inlineCode,
                headings: {
                    h1,
                    h2,
                    h3,
                    total: h1 + h2 + h3
                },
                tasks: {
                    total: totalTasks,
                    completed: completedTasks,
                    pending: pendingTasks,
                    completion_rate: completionRate
                },
                images,
                blockquotes
            };
        },
        
        // Load sidebar width from localStorage
        loadSidebarWidth() {
            const saved = localStorage.getItem('sidebarWidth');
            if (saved) {
                const width = parseInt(saved, 10);
                if (width >= 200 && width <= 600) {
                    this.sidebarWidth = width;
                }
            }
        },
        
        // Save sidebar width to localStorage
        saveSidebarWidth() {
            localStorage.setItem('sidebarWidth', this.sidebarWidth.toString());
        },
        
        // Load view mode from localStorage
        loadViewMode() {
            try {
                const saved = localStorage.getItem('viewMode');
                if (saved && ['edit', 'split', 'preview'].includes(saved)) {
                    this.viewMode = saved;
                }
            } catch (error) {
                console.error('Error loading view mode:', error);
            }
        },
        
        // Save view mode to localStorage
        saveViewMode() {
            try {
                localStorage.setItem('viewMode', this.viewMode);
            } catch (error) {
                console.error('Error saving view mode:', error);
            }
        },
        
        // Start resizing sidebar
        startResize(event) {
            this.isResizing = true;
            event.preventDefault();
            
            const resize = (e) => {
                if (!this.isResizing) return;
                
                // Calculate new width based on mouse position
                const newWidth = e.clientX;
                
                // Clamp between min and max
                if (newWidth >= 200 && newWidth <= 600) {
                    this.sidebarWidth = newWidth;
                }
            };
            
            const stopResize = () => {
                if (this.isResizing) {
                    this.isResizing = false;
                    this.saveSidebarWidth();
                    document.removeEventListener('mousemove', resize);
                    document.removeEventListener('mouseup', stopResize);
                }
            };
            
            document.addEventListener('mousemove', resize);
            document.addEventListener('mouseup', stopResize);
        },
        
        // Start resizing split panes (editor/preview)
        startSplitResize(event) {
            this.isResizingSplit = true;
            event.preventDefault();
            
            const container = event.target.parentElement;
            
            const resize = (e) => {
                if (!this.isResizingSplit) return;
                
                const containerRect = container.getBoundingClientRect();
                const mouseX = e.clientX - containerRect.left;
                const percentage = (mouseX / containerRect.width) * 100;
                
                // Clamp between 20% and 80%
                if (percentage >= 20 && percentage <= 80) {
                    this.editorWidth = percentage;
                }
            };
            
            const stopResize = () => {
                if (this.isResizingSplit) {
                    this.isResizingSplit = false;
                    this.saveEditorWidth();
                    document.removeEventListener('mousemove', resize);
                    document.removeEventListener('mouseup', stopResize);
                }
            };
            
            document.addEventListener('mousemove', resize);
            document.addEventListener('mouseup', stopResize);
        },
        
        // Setup mobile view mode handler (auto-switch from split to edit on mobile)
        setupMobileViewMode() {
            const MOBILE_BREAKPOINT = 768; // Match CSS breakpoint
            let previousWidth = window.innerWidth;
            
            const handleResize = () => {
                const currentWidth = window.innerWidth;
                const wasMobile = previousWidth <= MOBILE_BREAKPOINT;
                const isMobile = currentWidth <= MOBILE_BREAKPOINT;
                
                // If switching from desktop to mobile and in split mode
                if (!wasMobile && isMobile && this.viewMode === 'split') {
                    this.viewMode = 'edit';
                }
                
                previousWidth = currentWidth;
            };
            
            // Listen for window resize
            window.addEventListener('resize', handleResize);
            
            // Check initial state
            if (window.innerWidth <= MOBILE_BREAKPOINT && this.viewMode === 'split') {
                this.viewMode = 'edit';
            }
        },
        
        // Load editor width from localStorage
        loadEditorWidth() {
            const saved = localStorage.getItem('editorWidth');
            if (saved) {
                const width = parseFloat(saved);
                if (width >= 20 && width <= 80) {
                    this.editorWidth = width;
                }
            }
        },
        
        // Save editor width to localStorage
        saveEditorWidth() {
            localStorage.setItem('editorWidth', this.editorWidth.toString());
        },
        
        // Scroll to top of editor and preview
        scrollToTop() {
            // Disable scroll sync temporarily to prevent interference
            this.isScrolling = true;
            
            // Use cached references (refresh if not available)
            if (!this._domCache.editor || !this._domCache.previewContainer) {
                this.refreshDOMCache();
            }
            
            // Only scroll the visible panes based on viewMode
            if (this.viewMode === 'edit' || this.viewMode === 'split') {
                if (this._domCache.editor) {
                    this._domCache.editor.scrollTop = 0;
                }
            }
            
            if (this.viewMode === 'preview' || this.viewMode === 'split') {
                // Scroll the preview container (parent of .markdown-preview)
                if (this._domCache.previewContainer) {
                    this._domCache.previewContainer.scrollTop = 0;
                }
            }
            
            // Re-enable scroll sync after a short delay
            setTimeout(() => {
                this.isScrolling = false;
            }, CONFIG.SCROLL_SYNC_DELAY);
        },
        
        // Export current note as HTML
        async exportToHTML() {
            if (!this.currentNote || !this.noteContent) {
                alert('No note content to export');
                return;
            }
            
            try {
                // Get the note name without extension
                const noteName = this.currentNoteName || 'note';
                
                // Get current rendered HTML (this already has markdown converted and will have LaTeX delimiters)
                const renderedHTML = this.renderedMarkdown;
                
                // Get current theme CSS
                const currentTheme = this.currentTheme || 'light';
                const themeResponse = await fetch(`/api/themes/${currentTheme}`);
                const themeText = await themeResponse.text();
                
                // Check if response is JSON or plain CSS
                let themeCss;
                try {
                    const themeJson = JSON.parse(themeText);
                    // If it's JSON, extract the css field
                    themeCss = themeJson.css || themeText;
                } catch (e) {
                    // If it's not JSON, use it as-is
                    themeCss = themeText;
                }
                
                // Theme CSS uses :root[data-theme="..."] selector, but we need plain :root for export
                // Strip the data-theme attribute selector so variables apply globally
                themeCss = themeCss.replace(/:root\[data-theme="[^"]+"\]/g, ':root');
                
                // Get highlight.js theme URL from current page
                const highlightLinkElement = document.getElementById('highlight-theme');
                if (!highlightLinkElement || !highlightLinkElement.href) {
                    console.warn('Could not detect highlight.js theme, export may not match preview exactly');
                }
                const highlightTheme = highlightLinkElement ? highlightLinkElement.href : '';
                
                // Extract all markdown preview styles from current page
                let markdownStyles = '';
                const styleSheets = Array.from(document.styleSheets);
                
                for (const sheet of styleSheets) {
                    try {
                        // Skip external stylesheets (CDN resources) to avoid CORS errors
                        // We link them directly in the exported HTML anyway
                        if (sheet.href && (sheet.href.startsWith('http://') || sheet.href.startsWith('https://'))) {
                            const currentOrigin = window.location.origin;
                            const sheetURL = new URL(sheet.href);
                            if (sheetURL.origin !== currentOrigin) {
                                // Skip cross-origin stylesheets (they're linked directly in export)
                                continue;
                            }
                        }
                        
                        const rules = Array.from(sheet.cssRules || []);
                        for (const rule of rules) {
                            const cssText = rule.cssText;
                            // Include rules that target markdown-preview, mjx-container, or mermaid-rendered
                            if (cssText.includes('.markdown-preview') || 
                                cssText.includes('mjx-container') ||
                                cssText.includes('.MathJax') ||
                                cssText.includes('.mermaid-rendered')) {
                                markdownStyles += cssText + '\n';
                            }
                        }
                    } catch (e) {
                        // Gracefully skip stylesheets that can't be accessed
                        // (This should rarely happen now that we skip external stylesheets)
                        console.debug('Skipping stylesheet:', sheet.href);
                    }
                }
                
                // Create standalone HTML document with MathJax
                const htmlDocument = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${noteName}</title>
    
    <!-- Highlight.js for code syntax highlighting -->
    ${highlightTheme ? `<link rel="stylesheet" href="${highlightTheme}">` : '<!-- No highlight.js theme detected -->'}
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    
    <!-- MathJax for LaTeX math rendering (same config as preview) -->
    <script>
        MathJax = {
            tex: {
                inlineMath: [['$', '$']],
                displayMath: [['$$', '$$']],
                processEscapes: true,
                processEnvironments: true
            },
            options: {
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
            },
            startup: {
                pageReady: () => {
                    return MathJax.startup.defaultPageReady().then(() => {
                        // Highlight code blocks after MathJax is done (exclude diagram renderers)
                        document.querySelectorAll('pre code:not(.language-mermaid)').forEach((block) => {
                            hljs.highlightElement(block);
                        });
                    });
                }
            }
        };
    </script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    
    <!-- Mermaid.js for diagrams (if used in note) -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        const isDark = ${this.getThemeType() === 'dark'};
        mermaid.initialize({ 
            startOnLoad: false,
            theme: isDark ? 'dark' : 'default',
            securityLevel: 'strict',
            fontFamily: 'inherit'
        });
        
        // Render any Mermaid code blocks
        document.addEventListener('DOMContentLoaded', async () => {
            const mermaidBlocks = document.querySelectorAll('pre code.language-mermaid');
            for (let i = 0; i < mermaidBlocks.length; i++) {
                const block = mermaidBlocks[i];
                const pre = block.parentElement;
                try {
                    const code = block.textContent;
                    const id = 'mermaid-diagram-' + i;
                    const { svg } = await mermaid.render(id, code);
                    const container = document.createElement('div');
                    container.className = 'mermaid-rendered';
                    container.style.cssText = 'background-color: transparent; padding: 20px; text-align: center; overflow-x: auto;';
                    container.innerHTML = svg;
                    pre.parentElement.replaceChild(container, pre);
                } catch (error) {
                    console.error('Mermaid rendering error:', error);
                }
            }
        });
    </script>
    
    <style>
        /* Theme CSS */
        ${themeCss}
        
        /* Base styles */
        * {
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 2rem;
            max-width: 900px;
            margin-left: auto;
            margin-right: auto;
            background-color: var(--bg-primary);
            color: var(--text-primary);
        }
        
        /* Markdown preview styles extracted from current page */
        ${markdownStyles}
        
        @media (max-width: 768px) {
            body {
                padding: 1rem;
            }
        }
        
        @media print {
            body {
                padding: 0.5in;
                max-width: none;
            }
        }
    </style>
</head>
<body>
    <div class="markdown-preview">
        ${renderedHTML}
    </div>
</body>
</html>`;
                
                // Create blob and download
                const blob = new Blob([htmlDocument], { type: 'text/html;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${noteName}.html`;
                document.body.appendChild(a);
                a.click();
                
                // Cleanup
                URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
            } catch (error) {
                console.error('HTML export failed:', error);
                alert(`Failed to export HTML: ${error.message}`);
            }
        }
    }
}

