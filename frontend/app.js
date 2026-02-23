// NoteDiscovery Frontend Application

// Configuration constants
const CONFIG = {
    AUTOSAVE_DELAY: 1000,              // ms - Delay before triggering autosave
    SEARCH_DEBOUNCE_DELAY: 500,        // ms - Delay before running note search while typing
    SAVE_INDICATOR_DURATION: 2000,     // ms - How long to show "saved" indicator
    SCROLL_SYNC_DELAY: 50,             // ms - Delay to prevent scroll sync interference
    SCROLL_SYNC_MAX_RETRIES: 10,       // Maximum attempts to find editor/preview elements
    SCROLL_SYNC_RETRY_INTERVAL: 100,   // ms - Time between setupScrollSync retries
    MAX_UNDO_HISTORY: 50,              // Maximum number of undo steps to keep
    DEFAULT_SIDEBAR_WIDTH: 256,        // px - Default sidebar width (w-64 in Tailwind)
};

// localStorage settings configuration - centralized definition of all persisted settings
const LOCAL_SETTINGS = {
    // Boolean settings
    syntaxHighlightEnabled: { key: 'syntaxHighlightEnabled', type: 'boolean', default: false },
    readableLineLength: { key: 'readableLineLength', type: 'boolean', default: true },
    favoritesExpanded: { key: 'favoritesExpanded', type: 'boolean', default: true },
    tagsExpanded: { key: 'tagsExpanded', type: 'boolean', default: false },
    hideUnderscoreFolders: { key: 'hideUnderscoreFolders', type: 'boolean', default: false },
    // Number settings with validation
    sidebarWidth: { key: 'sidebarWidth', type: 'number', default: CONFIG.DEFAULT_SIDEBAR_WIDTH, min: 200, max: 600 },
    editorWidth: { key: 'editorWidth', type: 'number', default: 50, min: 20, max: 80 },
    // String settings with validation
    viewMode: { key: 'viewMode', type: 'string', default: 'split', valid: ['edit', 'split', 'preview'] },
    // JSON settings
    favorites: { key: 'noteFavorites', type: 'json', default: [] },
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
            // Note: ErrorHandler doesn't have access to Alpine's t() function
            // This message remains in English as a fallback
            alert(`Failed to ${operation}. Please try again.`);
        }
    }
};

/**
 * Centralized filename validation
 * Supports Unicode characters (international text) but blocks dangerous filesystem characters.
 * Does NOT silently modify filenames - validates and returns status.
 */
const FilenameValidator = {
    // Characters that are forbidden in filenames across Windows/macOS/Linux
    // Windows: \ / : * ? " < > |
    // macOS: / :
    // Linux: / \0
    // Common set to block (including control characters)
    FORBIDDEN_CHARS: /[\\/:*?"<>|\x00-\x1f]/,
    
    // For display purposes - human readable list
    FORBIDDEN_CHARS_DISPLAY: '\\ / : * ? " < > |',
    
    /**
     * Validate a filename (single segment, no path separators)
     * @param {string} name - The filename to validate
     * @returns {{ valid: boolean, error?: string, sanitized?: string }}
     */
    validateFilename(name) {
        if (!name || typeof name !== 'string') {
            return { valid: false, error: 'empty' };
        }
        
        const trimmed = name.trim();
        if (!trimmed) {
            return { valid: false, error: 'empty' };
        }
        
        // Check for forbidden characters
        if (this.FORBIDDEN_CHARS.test(trimmed)) {
            return { 
                valid: false, 
                error: 'forbidden_chars',
                forbiddenChars: this.FORBIDDEN_CHARS_DISPLAY
            };
        }
        
        // Check for reserved Windows names (case-insensitive)
        const reservedNames = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)/i;
        if (reservedNames.test(trimmed)) {
            return { valid: false, error: 'reserved_name' };
        }
        
        // Check for names starting/ending with dots or spaces (problematic on some systems)
        if (trimmed.startsWith('.') && trimmed.length === 1) {
            return { valid: false, error: 'invalid_dot' };
        }
        if (trimmed.endsWith('.') || trimmed.endsWith(' ')) {
            return { valid: false, error: 'trailing_dot_space' };
        }
        
        return { valid: true, sanitized: trimmed };
    },
    
    /**
     * Validate a path (may contain forward slashes for folder separators)
     * @param {string} path - The path to validate
     * @returns {{ valid: boolean, error?: string, sanitized?: string }}
     */
    validatePath(path) {
        if (!path || typeof path !== 'string') {
            return { valid: false, error: 'empty' };
        }
        
        const trimmed = path.trim();
        if (!trimmed) {
            return { valid: false, error: 'empty' };
        }
        
        // Split by forward slash and validate each segment
        const segments = trimmed.split('/').filter(s => s.length > 0);
        if (segments.length === 0) {
            return { valid: false, error: 'empty' };
        }
        
        for (const segment of segments) {
            const result = this.validateFilename(segment);
            if (!result.valid) {
                return result;
            }
        }
        
        // Rebuild path without empty segments
        return { valid: true, sanitized: segments.join('/') };
    }
};

function noteApp() {
    return {
        // App state
        appName: 'NoteDiscovery',
        appVersion: '0.0.0',
        authEnabled: false,
        demoMode: false,
        alreadyDonated: false,
        notes: [],
        currentNote: '',
        currentNoteName: '',
        noteContent: '',
        viewMode: 'split', // 'edit', 'split', 'preview'
        searchQuery: '',
        
        // Graph state (separate overlay, doesn't affect viewMode)
        showGraph: false,
        graphInstance: null,
        graphLoaded: false,
        graphData: null,
        searchResults: [],
        currentSearchHighlight: '', // Track current highlighted search term
        currentMatchIndex: 0, // Current match being viewed
        totalMatches: 0, // Total number of matches in the note
        isSaving: false,
        lastSaved: false,
        linkCopied: false,
        zenMode: false,
        previousViewMode: 'split',
        favorites: [],
        favoritesSet: new Set(), // For O(1) lookups
        favoritesExpanded: true,
        saveTimeout: null,
        
        // Note lookup maps for O(1) wikilink resolution (built on loadNotes)
        _noteLookup: {
            byPath: new Map(),           // path -> true
            byPathLower: new Map(),      // path.toLowerCase() -> true
            byName: new Map(),           // name (without .md) -> true  
            byNameLower: new Map(),      // name.toLowerCase() -> true
            byEndPath: new Map(),        // '/filename' and '/filename.md' -> true
        },
        
        // Media lookup map for O(1) media wikilink resolution (built on loadNotes)
        // Maps media filename (case-insensitive) -> full path
        _mediaLookup: new Map(),
        
        // Preview rendering debounce
        _previewDebounceTimeout: null,
        _lastRenderedContent: '',
        _cachedRenderedHTML: '',
        _mathDebounceTimeout: null,
        _mermaidDebounceTimeout: null,
        
        // Theme state
        currentTheme: 'light',
        availableThemes: [],
        
        // Locale/i18n state
        currentLocale: localStorage.getItem('locale') || 'en-US',
        availableLocales: [],
        // Translations loaded from backend (preloaded before Alpine init via window.__preloadedTranslations)
        translations: window.__preloadedTranslations || {},
        
        // Syntax highlighting
        syntaxHighlightEnabled: false,
        syntaxHighlightTimeout: null,
        
        // Readable line length (preview max-width)
        readableLineLength: true,
        
        // Hide underscore-prefixed folders (_attachments, _templates) from sidebar
        // Read synchronously to prevent flash on initial render
        hideUnderscoreFolders: localStorage.getItem('hideUnderscoreFolders') === 'true',
        
        // Icon rail / panel state
        activePanel: 'files', // 'files', 'search', 'tags', 'settings'
        
        // Folder state
        folderTree: [],
        allFolders: [],
        expandedFolders: new Set(),
        dragOverFolder: null,  // Track which folder is being hovered during drag
        
        // Tags state
        allTags: {},
        selectedTags: [],
        tagsExpanded: false,
        tagReloadTimeout: null, // For debouncing tag reloads

        // Search state
        searchDebounceTimeout: null,
        isSearching: false,
        
        // Outline (TOC) state
        outline: [], // [{level: 1, text: 'Heading', slug: 'heading'}, ...]
        
        // Scroll sync state
        isScrolling: false,
        
        // Unified drag state for notes, folders, and media
        draggedItem: null,  // { path: string, type: 'note' | 'folder' | 'image' | 'audio' | 'video' | 'document' }
        dropTarget: null,   // 'editor' | 'folder' | null
        
        // Undo/Redo history
        undoHistory: [],
        redoHistory: [],
        maxHistorySize: CONFIG.MAX_UNDO_HISTORY,
        isUndoRedo: false,
        hasPendingHistoryChanges: false,
        
        // Stats plugin state
        statsPluginEnabled: false,
        noteStats: null,
        statsExpanded: false,
        
        // Note metadata (frontmatter) state
        noteMetadata: null,
        metadataExpanded: false,
        _lastFrontmatter: null, // Cache to avoid re-parsing unchanged frontmatter
        
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
        dropdownTargetFolder: null, // Folder context for "New" dropdown ('' = root, null = not set)
        dropdownPosition: { top: 0, left: 0 }, // Position for contextual dropdown
        
        // Template state
        showTemplateModal: false,
        availableTemplates: [],
        selectedTemplate: '',
        newTemplateNoteName: '',
        
        // Share state
        showShareModal: false,
        shareInfo: null,
        shareLoading: false,
        showShareQR: false,
        shareLinkCopied: false,
        _sharedNotePaths: new Set(),  // O(1) lookup for shared note indicators
        
        // Quick Switcher state (Ctrl+Alt+P)
        showQuickSwitcher: false,
        quickSwitcherQuery: '',
        quickSwitcherIndex: 0,
        quickSwitcherResults: [],
        
        // Homepage state
        selectedHomepageFolder: '',
        _homepageCache: {
            folderPath: null,
            notes: null,
            folders: null,
            breadcrumb: null
        },
        
        // Homepage constants
        HOMEPAGE_MAX_NOTES: 50,
        
        // Computed-like helpers for homepage (cached for performance)
        homepageNotes() {
            // Return cached result if folder hasn't changed
            if (this._homepageCache.folderPath === this.selectedHomepageFolder && this._homepageCache.notes) {
                return this._homepageCache.notes;
            }
            
            if (!this.folderTree || typeof this.folderTree !== 'object') {
                return [];
            }
            
            const folderNode = this.getFolderNode(this.selectedHomepageFolder || '');
            const result = (folderNode && Array.isArray(folderNode.notes)) ? folderNode.notes : [];
            
            // Cache the result
            this._homepageCache.notes = result;
            this._homepageCache.folderPath = this.selectedHomepageFolder;
            
            return result;
        },
        
        homepageFolders() {
            // Return cached result if folder hasn't changed
            if (this._homepageCache.folderPath === this.selectedHomepageFolder && this._homepageCache.folders) {
                return this._homepageCache.folders;
            }
            
            if (!this.folderTree || typeof this.folderTree !== 'object') {
                return [];
            }
            
            // Get child folders
            let childFolders = [];
            if (!this.selectedHomepageFolder) {
                // Root level: all top-level folders
                childFolders = Object.entries(this.folderTree)
                    .filter(([key]) => key !== '__root__')
                    .map(([, folder]) => folder);
            } else {
                // Inside a folder: get its children
                const parentFolder = this.getFolderNode(this.selectedHomepageFolder);
                if (parentFolder && parentFolder.children) {
                    childFolders = Object.values(parentFolder.children);
                }
            }
            
            // Map to simplified structure (note count already cached in folder node)
            const result = childFolders
                .map(folder => ({
                    name: folder.name,
                    path: folder.path,
                    noteCount: folder.noteCount || 0  // Use pre-calculated count
                }))
                .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
            
            // Cache the result
            this._homepageCache.folders = result;
            this._homepageCache.folderPath = this.selectedHomepageFolder;
            
            return result;
        },
        
        homepageBreadcrumb() {
            // Return cached result if folder hasn't changed
            if (this._homepageCache.folderPath === this.selectedHomepageFolder && this._homepageCache.breadcrumb) {
                return this._homepageCache.breadcrumb;
            }
            
            const breadcrumb = [{ name: this.t('homepage.title'), path: '' }];
            
            if (this.selectedHomepageFolder) {
                const parts = this.selectedHomepageFolder.split('/').filter(Boolean);
                let currentPath = '';
                
                parts.forEach(part => {
                    currentPath = currentPath ? `${currentPath}/${part}` : part;
                    breadcrumb.push({ name: part, path: currentPath });
                });
            }
            
            // Cache the result
            this._homepageCache.breadcrumb = breadcrumb;
            this._homepageCache.folderPath = this.selectedHomepageFolder;
            
            return breadcrumb;
        },
        
        // Helper: Format file size nicely
        formatSize(bytes) {
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        },
        
        // Helper: Format date using current locale
        formatDate(dateStr) {
            if (!dateStr) return '';
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return '';
            return date.toLocaleDateString(this.currentLocale, { 
                year: 'numeric', 
                month: 'short', 
                day: 'numeric' 
            });
        },
        
        getFolderNode(folderPath = '') {
            if (!this.folderTree || typeof this.folderTree !== 'object') {
                return null;
            }
            
            if (!folderPath) {
                return this.folderTree['__root__'] || { name: '', path: '', children: {}, notes: [], noteCount: 0 };
            }
            
            const parts = folderPath.split('/').filter(Boolean);
            let currentLevel = this.folderTree;
            let node = null;
            
            for (const part of parts) {
                if (!currentLevel[part]) {
                    return null;
                }
                node = currentLevel[part];
                currentLevel = node.children || {};
            }
            
            return node;
        },
        
        // Check if app is empty (no notes and no folders)
        get isAppEmpty() {
            const notesArray = Array.isArray(this.notes) ? this.notes : [];
            const foldersArray = Array.isArray(this.allFolders) ? this.allFolders : [];
            return notesArray.length === 0 && foldersArray.length === 0;
        }, 
        
        // Mermaid state cache
        lastMermaidTheme: null,
        
        // Media viewer state
        currentMedia: '',  // Path to current media file (kept as 'currentMedia' for compatibility)
        currentMediaType: 'image',  // 'image', 'audio', 'video', 'document'
        
        // DOM element cache (to avoid repeated querySelector calls)
        _domCache: {
            editor: null,
            previewContainer: null,
            previewContent: null
        },
        
        // Initialize app
        async init() {
            // Prevent double initialization (Alpine.js may call x-init twice in some cases)
            if (window.__noteapp_initialized) return;
            window.__noteapp_initialized = true;
            
            // Store global reference for native event handlers in x-html content
            window.$root = this;
            
            // ESC key to cancel drag operations
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.draggedItem) {
                    this.cancelDrag();
                }
            });
            
            await this.loadConfig();
            await this.loadThemes();
            await this.initTheme();
            await this.loadAvailableLocales();
            // Note: Translations are preloaded synchronously before Alpine init (see index.html)
            // loadLocale() is only called when user changes language from settings
            await this.loadNotes();
            await this.loadSharedNotePaths();
            await this.loadTemplates();
            await this.checkStatsPlugin();
            this.loadLocalSettings();
            
            // Parse URL and load specific note if provided
            this.loadItemFromURL();
            
            // Set initial homepage state ONLY if we're actually on the homepage
            if (window.location.pathname === '/') {
                window.history.replaceState({ homepageFolder: '' }, '', '/');
                document.title = this.appName;
            }
            
            // Listen for browser back/forward navigation
            window.addEventListener('popstate', (e) => {
                if (e.state && e.state.notePath) {
                    // Navigating to a note
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
                } else if (e.state && e.state.mediaPath) {
                    // Navigating to a media file
                    this.viewMedia(e.state.mediaPath, null, false);
                } else {
                    // Navigating back to homepage
                    this.currentNote = '';
                    this.noteContent = '';
                    this.currentNoteName = '';
                    this.outline = [];
                    this.shareInfo = null; // Reset share info
                    document.title = this.appName;
                    
                    // Restore homepage folder state if it was saved
                    if (e.state && e.state.homepageFolder !== undefined) {
                        this.selectedHomepageFolder = e.state.homepageFolder || '';
                    } else {
                        // No folder state in history, go to root
                        this.selectedHomepageFolder = '';
                    }
                    
                    // Invalidate cache to force recalculation
                    this._homepageCache = {
                        folderPath: null,
                        notes: null,
                        folders: null,
                        breadcrumb: null
                    };
                    
                    // Clear search
                    this.searchQuery = '';
                    this.searchResults = [];
                    this.clearSearchHighlights();
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
            
            // Watch tags panel expanded state and save to localStorage
            this.$watch('tagsExpanded', () => {
                this.saveTagsExpanded();
            });
            
            // Watch favorites expanded state and save to localStorage
            this.$watch('favoritesExpanded', () => {
                this.saveFavoritesExpanded();
            });
            
            // Setup keyboard shortcuts (only once to prevent double triggers)
            if (!window.__noteapp_shortcuts_initialized) {
                window.__noteapp_shortcuts_initialized = true;
                window.addEventListener('keydown', (e) => {
                    // Use e.key (not e.code) for letter keys to support non-QWERTY keyboard layouts
                    
                    // Ctrl/Cmd + S to save
                    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                        e.preventDefault();
                        this.saveNote();
                    }
                    
                    // Ctrl/Cmd + Alt + P for Quick Switcher
                    if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.toLowerCase() === 'p') {
                        e.preventDefault();
                        this.openQuickSwitcher();
                        return;
                    }
                    
                    // Ctrl/Cmd + Alt/Option + N for new note
                    if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.toLowerCase() === 'n') {
                        e.preventDefault();
                        this.createNote();
                    }
                    
                    // Ctrl/Cmd + Alt/Option + F for new folder
                    if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.toLowerCase() === 'f') {
                        e.preventDefault();
                        this.createFolder();
                    }
                    
                    // Ctrl/Cmd + Z for undo (without shift or alt)
                    // Use e.key instead of e.code to support non-QWERTY keyboard layouts
                    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'z') {
                        e.preventDefault();
                        this.undo();
                    }
                    
                    // Ctrl/Cmd + Y OR Ctrl/Cmd+Shift+Z for redo
                    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
                        e.preventDefault();
                        this.redo();
                    }
                    if ((e.ctrlKey || e.metaKey) && e.shiftKey && !e.altKey && e.key.toLowerCase() === 'z') {
                        e.preventDefault();
                        this.redo();
                    }
                    
                    // F3 for next search match
                    if (e.code === 'F3' && !e.shiftKey) {
                        e.preventDefault();
                        this.nextMatch();
                    }
                    
                    // Shift + F3 for previous search match
                    if (e.code === 'F3' && e.shiftKey) {
                        e.preventDefault();
                        this.previousMatch();
                    }
                    
                    // Only apply markdown shortcuts when editor is focused and a note is open
                    const isEditorFocused = document.activeElement?.id === 'note-editor';
                    if (isEditorFocused && this.currentNote) {
                        // Ctrl/Cmd + B for bold
                        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
                            e.preventDefault();
                            this.wrapSelection('**', '**', 'bold text');
                        }
                        
                        // Ctrl/Cmd + I for italic
                        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'i') {
                            e.preventDefault();
                            this.wrapSelection('*', '*', 'italic text');
                        }
                        
                        // Ctrl/Cmd + K for link
                        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                            e.preventDefault();
                            this.insertLink();
                        }
                        
                        // Ctrl/Cmd + Alt/Option + T for table
                        if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.toLowerCase() === 't') {
                            e.preventDefault();
                            this.insertTable();
                        }
                        
                        // Ctrl/Cmd + Alt/Option + Z for Zen mode
                        if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.toLowerCase() === 'z') {
                            e.preventDefault();
                            this.toggleZenMode();
                        }
                    }
                    
                    // Escape to exit Zen mode (works anywhere)
                    if (e.key === 'Escape' && this.zenMode) {
                        e.preventDefault();
                        this.toggleZenMode();
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
            
            // Listen for fullscreen changes (to sync zen mode state)
            document.addEventListener('fullscreenchange', () => {
                if (!document.fullscreenElement && this.zenMode) {
                    // User exited fullscreen manually, exit zen mode too
                    this.zenMode = false;
                    this.viewMode = this.previousViewMode;
                }
            });
        },
        
        // Load app configuration
        async loadConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                this.appName = config.name;
                this.appVersion = config.version || '0.0.0';
                this.authEnabled = config.authentication?.enabled || false;
                this.demoMode = config.demoMode || false;
                this.alreadyDonated = config.alreadyDonated || false;
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
        
        // Syntax highlighting toggle
        toggleSyntaxHighlight() {
            this.syntaxHighlightEnabled = !this.syntaxHighlightEnabled;
            localStorage.setItem('syntaxHighlightEnabled', this.syntaxHighlightEnabled);
            if (this.syntaxHighlightEnabled) {
                this.updateSyntaxHighlight();
            }
        },
        
        // Load all localStorage settings at once using centralized config
        loadLocalSettings() {
            for (const [prop, config] of Object.entries(LOCAL_SETTINGS)) {
                try {
                    const saved = localStorage.getItem(config.key);
                    
                    if (saved === null) {
                        // Use default value if not set
                        this[prop] = config.default;
                    } else if (config.type === 'boolean') {
                        this[prop] = saved === 'true';
                    } else if (config.type === 'number') {
                        const num = parseFloat(saved);
                        // Validate range if specified
                        if (!isNaN(num) && 
                            (config.min === undefined || num >= config.min) && 
                            (config.max === undefined || num <= config.max)) {
                            this[prop] = num;
                        } else {
                            this[prop] = config.default;
                        }
                    } else if (config.type === 'string') {
                        // Validate against allowed values if specified
                        if (!config.valid || config.valid.includes(saved)) {
                            this[prop] = saved;
                        } else {
                            this[prop] = config.default;
                        }
                    } else if (config.type === 'json') {
                        this[prop] = JSON.parse(saved);
                    }
                } catch (error) {
                    console.error(`Error loading setting ${prop}:`, error);
                    this[prop] = config.default;
                }
            }
            
            // Special case: favorites also needs to update the Set for O(1) lookups
            this.favoritesSet = new Set(this.favorites);
        },
        
        // Readable line length toggle (for preview max-width)
        toggleReadableLineLength() {
            this.readableLineLength = !this.readableLineLength;
            localStorage.setItem('readableLineLength', this.readableLineLength);
        },
        
        // Hide underscore folders toggle (hides _attachments, _templates, etc. from sidebar)
        toggleHideUnderscoreFolders() {
            this.hideUnderscoreFolders = !this.hideUnderscoreFolders;
            localStorage.setItem('hideUnderscoreFolders', this.hideUnderscoreFolders);
        },
        
        // Update syntax highlight overlay (debounced, called on input)
        updateSyntaxHighlight() {
            if (!this.syntaxHighlightEnabled) return;
            
            clearTimeout(this.syntaxHighlightTimeout);
            this.syntaxHighlightTimeout = setTimeout(() => {
                const overlay = document.getElementById('syntax-overlay');
                if (overlay) {
                    overlay.innerHTML = this.highlightMarkdown(this.noteContent);
                }
            }, 50); // 50ms debounce
        },
        
        // Sync overlay scroll with textarea
        syncOverlayScroll() {
            const textarea = document.getElementById('note-editor');
            const overlay = document.getElementById('syntax-overlay');
            if (textarea && overlay) {
                overlay.scrollTop = textarea.scrollTop;
                overlay.scrollLeft = textarea.scrollLeft;
            }
        },
        
        // Highlight markdown syntax
        highlightMarkdown(text) {
            if (!text) return '';
            
            // Escape HTML first
            let html = this.escapeHtml(text);
            
            // Store code blocks and inline code with placeholders to protect from other patterns
            const codePlaceholders = [];
            
            // Code blocks FIRST - protect them before anything else
            html = html.replace(/(```[\s\S]*?```)/g, (match) => {
                codePlaceholders.push('<span class="md-codeblock">' + match + '</span>');
                return `\x00CODE${codePlaceholders.length - 1}\x00`;
            });
            
            // Frontmatter (must be at VERY start of document, not any line)
            if (html.startsWith('---\n')) {
                html = html.replace(/^(---\n[\s\S]*?\n---)/, (match) => {
                    codePlaceholders.push('<span class="md-frontmatter">' + match + '</span>');
                    return `\x00CODE${codePlaceholders.length - 1}\x00`;
                });
            }
            
            // Inline code - protect it
            html = html.replace(/`([^`\n]+)`/g, (match) => {
                codePlaceholders.push('<span class="md-code">' + match + '</span>');
                return `\x00CODE${codePlaceholders.length - 1}\x00`;
            });
            
            // Now apply other patterns (they won't match inside protected code)
            
            // Headings - capture the whitespace to preserve exact characters (tabs vs spaces)
            // This prevents cursor/selection misalignment
            html = html.replace(/^(#{1,6})(\s)(.*)$/gm, '<span class="md-heading">$1$2$3</span>');
            
            // Bold (must come before italic)
            html = html.replace(/\*\*([^*]+)\*\*/g, '<span class="md-bold">**$1**</span>');
            html = html.replace(/__([^_]+)__/g, '<span class="md-bold">__$1__</span>');
            
            // Italic
            html = html.replace(/(?<![*\\])\*([^*\n]+)\*(?!\*)/g, '<span class="md-italic">*$1*</span>');
            html = html.replace(/(?<![_\\])_([^_\n]+)_(?!_)/g, '<span class="md-italic">_$1_</span>');
            
            // Wikilinks [[...]]
            html = html.replace(/\[\[([^\]]+)\]\]/g, '<span class="md-wikilink">[[$1]]</span>');
            
            // Links [text](url)
            html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="md-link">[$1]</span><span class="md-link-url">($2)</span>');
            
            // Lists - use ([ \t]) to capture the space/tab and preserve exact characters
            // IMPORTANT: Don't add any characters (like \u200B) that aren't in the original,
            // as this breaks cursor/selection alignment between textarea and overlay
            html = html.replace(/^(\s*)([-*+])([ \t])(.*)$/gm, (match, indent, bullet, space, rest) => {
                return `${indent}<span class="md-list">${bullet}</span>${space}${rest}`;
            });
            html = html.replace(/^(\s*)(\d+\.)([ \t])(.*)$/gm, (match, indent, bullet, space, rest) => {
                return `${indent}<span class="md-list">${bullet}</span>${space}${rest}`;
            });
            
            // Blockquotes
            html = html.replace(/^(&gt;.*)$/gm, '<span class="md-blockquote">$1</span>');
            
            // Horizontal rules
            html = html.replace(/^([-*_]{3,})$/gm, '<span class="md-hr">$1</span>');
            
            // Restore protected code blocks
            html = html.replace(/\x00CODE(\d+)\x00/g, (match, index) => codePlaceholders[parseInt(index)]);
            
            // Add trailing space to match textarea's phantom line for cursor
            // This ensures the overlay and textarea have the same content height
            html += '\n ';
            
            return html;
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
                
                // Refresh graph if visible (longer delay to ensure CSS is applied)
                if (this.showGraph) {
                    setTimeout(() => this.initGraph(), 300);
                }
                
                // Update PWA theme-color meta tag to match current theme
                const themeColorMeta = document.querySelector('meta[name="theme-color"]');
                if (themeColorMeta) {
                    // Get the accent color from CSS variables
                    const accentColor = getComputedStyle(document.documentElement)
                        .getPropertyValue('--accent-primary').trim() || '#667eea';
                    themeColorMeta.setAttribute('content', accentColor);
                }
            } catch (error) {
                console.error('Failed to load theme:', error);
            }
        },
        
        // ==================== INTERNATIONALIZATION ====================
        
        // Translation function - get translated string by key
        t(key, params = {}) {
            const keys = key.split('.');
            let value = this.translations;
            
            for (const k of keys) {
                value = value?.[k];
            }
            
            // Fallback to key if translation not found (silently - default translations are inline)
            if (typeof value !== 'string') {
                return key;
            }
            
            // Replace {{param}} placeholders
            return value.replace(/\{\{(\w+)\}\}/g, (_, name) => params[name] ?? `{{${name}}}`);
        },
        
        /**
         * Get localized error message from FilenameValidator result
         * @param {object} validation - The validation result from FilenameValidator
         * @param {string} type - 'note' or 'folder'
         * @returns {string} Localized error message
         */
        getValidationErrorMessage(validation, type = 'note') {
            switch (validation.error) {
                case 'empty':
                    return type === 'note' 
                        ? this.t('notes.empty_name') 
                        : this.t('folders.invalid_name');
                case 'forbidden_chars':
                    return this.t('validation.forbidden_chars', { 
                        chars: validation.forbiddenChars 
                    });
                case 'reserved_name':
                    return this.t('validation.reserved_name');
                case 'invalid_dot':
                    return this.t('validation.invalid_dot');
                case 'trailing_dot_space':
                    return this.t('validation.trailing_dot_space');
                default:
                    return type === 'note' 
                        ? this.t('notes.invalid_name') 
                        : this.t('folders.invalid_name');
            }
        },
        
        // Load available locales from backend
        async loadAvailableLocales() {
            try {
                const response = await fetch('/api/locales');
                const data = await response.json();
                this.availableLocales = data.locales || [];
            } catch (error) {
                console.error('Failed to load available locales:', error);
                this.availableLocales = [{ code: 'en-US', name: 'English', flag: '🇺🇸' }];
            }
        },
        
        // Load translations for a specific locale
        async loadLocale(localeCode = null) {
            const targetLocale = localeCode || localStorage.getItem('locale') || 'en-US';
            
            try {
                const response = await fetch(`/api/locales/${targetLocale}`);
                if (response.ok) {
                    this.translations = await response.json();
                    this.currentLocale = targetLocale;
                    localStorage.setItem('locale', targetLocale);
                } else if (targetLocale !== 'en-US') {
                    // Fallback to en-US if requested locale not found
                    await this.loadLocale('en-US');
                }
            } catch (error) {
                console.error('Failed to load locale:', error);
                // If en-US also fails, translations will be empty and t() will return keys
                if (targetLocale !== 'en-US') {
                    await this.loadLocale('en-US');
                }
            }
        },
        
        // Change locale and reload translations
        async changeLocale(localeCode) {
            await this.loadLocale(localeCode);
        },
        
        // ==================== END INTERNATIONALIZATION ====================
        
        // Load all notes
        async loadNotes() {
            try {
                const response = await fetch('/api/notes');
                const data = await response.json();
                this.notes = data.notes;
                this.allFolders = data.folders || [];
                this.buildNoteLookupMaps(); // Build O(1) lookup maps
                this.buildFolderTree();
                await this.loadTags(); // Load tags after notes are loaded
            } catch (error) {
                ErrorHandler.handle('load notes', error);
            }
        },
        
        // Build lookup maps for O(1) wikilink resolution
        buildNoteLookupMaps() {
            // Clear existing maps
            this._noteLookup.byPath.clear();
            this._noteLookup.byPathLower.clear();
            this._noteLookup.byName.clear();
            this._noteLookup.byNameLower.clear();
            this._noteLookup.byEndPath.clear();
            this._mediaLookup.clear();
            
            for (const note of this.notes) {
                const path = note.path;
                const pathLower = path.toLowerCase();
                const name = note.name;
                const nameLower = name.toLowerCase();
                
                // Handle media files separately - build media lookup map
                if (note.type !== 'note') {
                    // Map filename WITH extension (case-insensitive) to full path
                    // Use path to get filename with extension (note.name is stem without extension)
                    const filenameWithExt = path.split('/').pop().toLowerCase();
                    // First match wins if there are duplicates
                    if (!this._mediaLookup.has(filenameWithExt)) {
                        this._mediaLookup.set(filenameWithExt, path);
                    }
                    continue;
                }
                
                // Notes only from here
                const nameWithoutMd = name.replace(/\.md$/i, '');
                const nameWithoutMdLower = nameWithoutMd.toLowerCase();
                
                // Store all variations for fast lookup
                this._noteLookup.byPath.set(path, true);
                this._noteLookup.byPath.set(path.replace(/\.md$/i, ''), true);
                this._noteLookup.byPathLower.set(pathLower, true);
                this._noteLookup.byPathLower.set(pathLower.replace(/\.md$/i, ''), true);
                this._noteLookup.byName.set(name, true);
                this._noteLookup.byName.set(nameWithoutMd, true);
                this._noteLookup.byNameLower.set(nameLower, true);
                this._noteLookup.byNameLower.set(nameWithoutMdLower, true);
                
                // End path matching (for /folder/note style links)
                this._noteLookup.byEndPath.set('/' + nameWithoutMdLower, true);
                this._noteLookup.byEndPath.set('/' + nameLower, true);
            }
        },
        
        // Fast O(1) check if a wikilink target exists
        wikiLinkExists(linkTarget) {
            const targetLower = linkTarget.toLowerCase();
            
            // Check all lookup maps
            return (
                this._noteLookup.byPath.has(linkTarget) ||
                this._noteLookup.byPath.has(linkTarget + '.md') ||
                this._noteLookup.byPathLower.has(targetLower) ||
                this._noteLookup.byPathLower.has(targetLower + '.md') ||
                this._noteLookup.byName.has(linkTarget) ||
                this._noteLookup.byNameLower.has(targetLower) ||
                this._noteLookup.byEndPath.has('/' + targetLower) ||
                this._noteLookup.byEndPath.has('/' + targetLower + '.md')
            );
        },
        
        // Resolve media wikilink to full path (O(1) lookup)
        // Returns the full path if found, null otherwise
        resolveMediaWikilink(mediaName) {
            const nameLower = mediaName.toLowerCase();
            return this._mediaLookup.get(nameLower) || null;
        },
        
        // Load all tags
        async loadTags() {
            try {
                const response = await fetch('/api/tags');
                const data = await response.json();
                this.allTags = data.tags || {};
            } catch (error) {
                ErrorHandler.handle('load tags', error, false); // Don't show alert, tags are optional
            }
        },
        
        // Debounced tag reload (prevents excessive API calls during typing)
        loadTagsDebounced() {
            // Clear existing timeout
            if (this.tagReloadTimeout) {
                clearTimeout(this.tagReloadTimeout);
            }
            
            // Set new timeout - reload tags 2 seconds after last save
            this.tagReloadTimeout = setTimeout(() => {
                this.loadTags();
            }, 2000);
        },
        
        // Toggle tag selection for filtering
        toggleTag(tag) {
            const index = this.selectedTags.indexOf(tag);
            if (index > -1) {
                this.selectedTags.splice(index, 1);
            } else {
                this.selectedTags.push(tag);
            }
            
            // Apply unified filtering
            this.applyFilters();
        },
        
        // ========================================================================
        // Template Methods
        // ========================================================================
        
        // Load available templates from _templates folder
        async loadTemplates() {
            try {
                const response = await fetch('/api/templates');
                const data = await response.json();
                this.availableTemplates = data.templates || [];
            } catch (error) {
                ErrorHandler.handle('load templates', error, false); // Don't show alert, templates are optional
            }
        },
        
        // Create a new note from a template
        async createNoteFromTemplate() {
            if (!this.selectedTemplate || !this.newTemplateNoteName.trim()) {
                return;
            }
            
            try {
                // Validate the note name
                const validation = FilenameValidator.validateFilename(this.newTemplateNoteName);
                if (!validation.valid) {
                    alert(this.getValidationErrorMessage(validation, 'note'));
                    return;
                }
                
                // Determine the note path based on dropdown context
                let notePath = validation.sanitized;
                if (!notePath.endsWith('.md')) {
                    notePath += '.md';
                }
                
                // Determine target folder: use dropdown context if set, otherwise homepage folder
                let targetFolder;
                if (this.dropdownTargetFolder !== null && this.dropdownTargetFolder !== undefined) {
                    targetFolder = this.dropdownTargetFolder; // Can be '' for root or a folder path
                } else {
                    targetFolder = this.selectedHomepageFolder || '';
                }
                
                // If we have a target folder, create note in that folder
                if (targetFolder) {
                    notePath = `${targetFolder}/${notePath}`;
                }
                
                // CRITICAL: Check if note already exists
                const existingNote = this.notes.find(note => note.path === notePath);
                if (existingNote) {
                    alert(this.t('notes.already_exists', { name: validation.sanitized }));
                    return;
                }
                
                // Create note from template
                const response = await fetch('/api/templates/create-note', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        templateName: this.selectedTemplate,
                        notePath: notePath
                    })
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    alert(error.detail || this.t('templates.create_failed'));
                    return;
                }
                
                const data = await response.json();
                
                // Close modal and reset state
                this.showTemplateModal = false;
                this.selectedTemplate = '';
                this.newTemplateNoteName = '';
                
                // Reload notes and open the new note
                await this.loadNotes();
                await this.loadNote(data.path);
                this.focusEditorForNewNote();
                
            } catch (error) {
                ErrorHandler.handle('create note from template', error);
            }
        },
        
        // Clear all tag filters
        clearTagFilters() {
            this.selectedTags = [];
            
            // Apply unified filtering
            this.applyFilters();
        },
        
        // ========================================================================
        // Outline (TOC) Methods
        // ========================================================================
        
        // Extract headings from markdown content for the outline
        extractOutline(content) {
            if (!content) {
                this.outline = [];
                return;
            }
            
            const headings = [];
            const lines = content.split('\n');
            const slugCounts = {}; // Track duplicate slugs
            
            // Skip frontmatter and code blocks
            let inFrontmatter = false;
            let inCodeBlock = false;
            
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                
                // Handle frontmatter
                if (i === 0 && line.trim() === '---') {
                    inFrontmatter = true;
                    continue;
                }
                if (inFrontmatter) {
                    if (line.trim() === '---') {
                        inFrontmatter = false;
                    }
                    continue;
                }
                
                // Handle fenced code blocks (``` or ~~~)
                if (line.trim().startsWith('```') || line.trim().startsWith('~~~')) {
                    inCodeBlock = !inCodeBlock;
                    continue;
                }
                if (inCodeBlock) {
                    continue;
                }
                
                // Match heading lines (# to ######)
                const match = line.match(/^(#{1,6})\s+(.+)$/);
                if (match) {
                    const level = match[1].length;
                    const text = match[2].trim();
                    
                    // Generate slug (GitHub-style)
                    let slug = text
                        .toLowerCase()
                        .replace(/[^\w\s-]/g, '') // Remove special chars
                        .replace(/\s+/g, '-')     // Spaces to dashes
                        .replace(/-+/g, '-');     // Multiple dashes to single
                    
                    // Handle duplicate slugs
                    if (slugCounts[slug] !== undefined) {
                        slugCounts[slug]++;
                        slug = `${slug}-${slugCounts[slug]}`;
                    } else {
                        slugCounts[slug] = 0;
                    }
                    
                    headings.push({
                        level,
                        text,
                        slug,
                        line: i + 1 // 1-indexed line number
                    });
                }
            }
            
            this.outline = headings;
        },
        
        // Scroll to a heading in the editor or preview
        scrollToHeading(heading) {
            if (this.viewMode === 'preview' || this.viewMode === 'split') {
                // In preview/split mode, scroll the preview pane
                const preview = document.querySelector('.markdown-preview');
                if (preview) {
                    // Find the heading element by text content (more reliable than ID)
                    const headingElements = preview.querySelectorAll('h1, h2, h3, h4, h5, h6');
                    for (const el of headingElements) {
                        if (el.textContent.trim() === heading.text) {
                            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                            // Add a brief highlight effect
                            el.style.transition = 'background-color 0.3s';
                            el.style.backgroundColor = 'var(--accent-light)';
                            setTimeout(() => {
                                el.style.backgroundColor = '';
                            }, 1000);
                            return;
                        }
                    }
                }
            }
            
            if (this.viewMode === 'edit' || this.viewMode === 'split') {
                // In edit/split mode, scroll the editor to the line
                const textarea = document.querySelector('.editor-textarea');
                if (textarea && heading.line) {
                    const lines = textarea.value.split('\n');
                    let charPos = 0;
                    
                    // Calculate character position of the heading line
                    for (let i = 0; i < heading.line - 1 && i < lines.length; i++) {
                        charPos += lines[i].length + 1; // +1 for newline
                    }
                    
                    // Set cursor position and scroll
                    textarea.focus();
                    textarea.setSelectionRange(charPos, charPos);
                    
                    // Calculate scroll position (approximate)
                    const lineHeight = parseFloat(getComputedStyle(textarea).lineHeight) || 24;
                    const scrollTop = (heading.line - 1) * lineHeight - textarea.clientHeight / 3;
                    textarea.scrollTop = Math.max(0, scrollTop);
                }
            }
        },
        
        // Unified filtering logic combining tags and text search
        async applyFilters() {
            const hasTextSearch = this.searchQuery.trim().length > 0;
            const hasTagFilter = this.selectedTags.length > 0;
            
            // Case 1: No filters at all → show full folder tree
            if (!hasTextSearch && !hasTagFilter) {
                this.isSearching = false;
                this.searchResults = [];
                this.currentSearchHighlight = '';
                this.clearSearchHighlights();
                this.buildFolderTree();
                return;
            }
            
            // Case 2: Only tag filter → convert to flat list of matching notes
            if (hasTagFilter && !hasTextSearch) {
                this.isSearching = false;
                this.searchResults = this.notes.filter(note => 
                    note.type === 'note' && this.noteMatchesTags(note)
                );
                this.currentSearchHighlight = '';
                this.clearSearchHighlights();
                return;
            }
            
            // Case 3: Text search (with or without tag filter)
            if (hasTextSearch) {
                this.isSearching = true;
                try {
                    const response = await fetch(`/api/search?q=${encodeURIComponent(this.searchQuery)}`);
                    const data = await response.json();
                    
                    // Apply tag filtering to search results if tags are selected
                    let results = data.results;
                    if (hasTagFilter) {
                        results = results.filter(result => {
                            const note = this.notes.find(n => n.path === result.path);
                            return note ? this.noteMatchesTags(note) : false;
                        });
                    }
                    
                    this.searchResults = results;
                    
                    // Highlight search term in current note if open
                    if (this.currentNote && this.noteContent) {
                        this.currentSearchHighlight = this.searchQuery;
                        this.$nextTick(() => {
                            this.highlightSearchTerm(this.searchQuery, false);
                        });
                    }
                } catch (error) {
                    console.error('Search failed:', error);
                    this.searchResults = [];
                } finally {
                    this.isSearching = false;
                }
            }
        },
        
        // Check if a note matches selected tags (AND logic)
        noteMatchesTags(note) {
            if (this.selectedTags.length === 0) {
                return true; // No filter active
            }
            if (!note.tags || note.tags.length === 0) {
                return false; // Note has no tags but filter is active
            }
            // Check if note has ALL selected tags (AND logic)
            return this.selectedTags.every(tag => note.tags.includes(tag));
        },
        
        // Get all tags sorted by name
        get sortedTags() {
            return Object.entries(this.allTags).sort((a, b) => a[0].localeCompare(b[0]));
        },
        
        // Get tags for current note
        get currentNoteTags() {
            if (!this.currentNote) return [];
            const note = this.notes.find(n => n.path === this.currentNote);
            return note && note.tags ? note.tags : [];
        },
        
        // ==================== FAVORITES ====================
        
        // Save favorites to localStorage
        saveFavorites() {
            try {
                localStorage.setItem('noteFavorites', JSON.stringify(this.favorites));
            } catch (e) {
                console.warn('Could not save favorites to localStorage');
            }
        },
        
        // Check if a note is favorited (O(1) lookup)
        isFavorite(notePath) {
            return this.favoritesSet.has(notePath);
        },
        
        // Toggle favorite status for a note
        toggleFavorite(notePath = null) {
            const path = notePath || this.currentNote;
            if (!path) return;
            
            if (this.favoritesSet.has(path)) {
                // Remove from favorites
                this.favorites = this.favorites.filter(f => f !== path);
            } else {
                // Add to favorites
                this.favorites = [...this.favorites, path];
            }
            // Recreate Set from array for consistency
            this.favoritesSet = new Set(this.favorites);
            this.saveFavorites();
        },
        
        // Get favorite notes with full details (for display)
        get favoriteNotes() {
            return this.favorites
                .map(path => {
                    // Find note by exact path or case-insensitive match
                    let note = this.notes.find(n => n.path === path);
                    if (!note) {
                        note = this.notes.find(n => n.path.toLowerCase() === path.toLowerCase());
                    }
                    if (!note) return null;
                    return {
                        path: note.path, // Use actual path from notes (fixes case issues)
                        name: note.path.split('/').pop().replace('.md', ''),
                        folder: note.folder || ''
                    };
                })
                .filter(Boolean); // Remove nulls (deleted notes)
        },
        
        saveFavoritesExpanded() {
            try {
                localStorage.setItem('favoritesExpanded', this.favoritesExpanded.toString());
            } catch (e) {
                console.error('Error saving favorites expanded state:', e);
            }
        },
        
        // Get current note's last modified time as relative string
        get lastEditedText() {
            if (!this.currentNote) return '';
            const note = this.notes.find(n => n.path === this.currentNote);
            if (!note || !note.modified) return '';
            
            const modified = new Date(note.modified);
            const now = new Date();
            const diffMs = now - modified;
            const diffSecs = Math.floor(diffMs / 1000);
            const diffMins = Math.floor(diffSecs / 60);
            const diffHours = Math.floor(diffMins / 60);
            const diffDays = Math.floor(diffHours / 24);
            
            if (diffSecs < 60) return this.t('editor.just_now');
            if (diffMins < 60) return this.t('editor.minutes_ago', { count: diffMins });
            if (diffHours < 24) return this.t('editor.hours_ago', { count: diffHours });
            if (diffDays < 7) return this.t('editor.days_ago', { count: diffDays });
            
            // For older dates, show the date in selected locale
            return modified.toLocaleDateString(this.currentLocale, { month: 'short', day: 'numeric' });
        },
        
        // Parse tags from markdown content (matches backend logic)
        parseTagsFromContent(content) {
            if (!content || !content.trim().startsWith('---')) {
                return [];
            }
            
            try {
                const lines = content.split('\n');
                if (lines[0].trim() !== '---') return [];
                
                // Find closing ---
                let endIdx = -1;
                for (let i = 1; i < lines.length; i++) {
                    if (lines[i].trim() === '---') {
                        endIdx = i;
                        break;
                    }
                }
                
                if (endIdx === -1) return [];
                
                const frontmatterLines = lines.slice(1, endIdx);
                const tags = [];
                let inTagsList = false;
                
                for (const line of frontmatterLines) {
                    const stripped = line.trim();
                    
                    // Check for inline array: tags: [tag1, tag2]
                    if (stripped.startsWith('tags:')) {
                        const rest = stripped.substring(5).trim();
                        if (rest.startsWith('[') && rest.endsWith(']')) {
                            const tagsStr = rest.substring(1, rest.length - 1);
                            const rawTags = tagsStr.split(',').map(t => t.trim());
                            tags.push(...rawTags.filter(t => t).map(t => t.toLowerCase()));
                            break;
                        } else if (rest) {
                            tags.push(rest.toLowerCase());
                            break;
                        } else {
                            inTagsList = true;
                        }
                    } else if (inTagsList) {
                        if (stripped.startsWith('-')) {
                            const tag = stripped.substring(1).trim();
                            if (tag && !tag.startsWith('#')) {
                                tags.push(tag.toLowerCase());
                            }
                        } else if (stripped && !stripped.startsWith('#')) {
                            break;
                        }
                    }
                }
                
                return [...new Set(tags)].sort();
            } catch (e) {
                console.error('Error parsing tags:', e);
                return [];
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
            
            // Add ALL notes to their folders (no filtering - tree only shown when no filters active)
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
            
            // Calculate and cache note counts recursively (for performance)
            const calculateNoteCounts = (folderNode) => {
                const directNotes = folderNode.notes ? folderNode.notes.length : 0;
                
                if (!folderNode.children || Object.keys(folderNode.children).length === 0) {
                    folderNode.noteCount = directNotes;
                    return directNotes;
                }
                
                const childNotesCount = Object.values(folderNode.children).reduce(
                    (total, child) => total + calculateNoteCounts(child),
                    0
                );
                
                folderNode.noteCount = directNotes + childNotesCount;
                return folderNode.noteCount;
            };
            
            // Calculate note counts for all folders
            Object.values(tree).forEach(folder => {
                if (folder.path !== undefined || folder === tree['__root__']) {
                    calculateNoteCounts(folder);
                }
            });
            
            // Invalidate homepage cache when tree is rebuilt
            this._homepageCache = {
                folderPath: null,
                notes: null,
                folders: null,
                breadcrumb: null
            };
            
            // Assign new tree (Alpine will detect the change)
            this.folderTree = tree;
        },
        
        // =====================================================================
        // DATA-ATTRIBUTE BASED HANDLERS
        // These read path/name/type from data-* attributes, avoiding JS escaping issues
        // =====================================================================
        
        // Escape strings for HTML attributes (simpler than JS escaping)
        escapeHtmlAttr(str) {
            if (!str) return '';
            return str
                .replace(/&/g, '&amp;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
        
        // Folder handlers - read from dataset
        handleFolderClick(el) {
            this.toggleFolder(el.dataset.path);
        },
        handleFolderDragOver(el, event) {
            event.preventDefault();
            this.dragOverFolder = el.dataset.path;
            el.classList.add('drag-over');
        },
        handleFolderDragLeave(el) {
            this.dragOverFolder = null;
            el.classList.remove('drag-over');
        },
        handleFolderDrop(el, event) {
            event.stopPropagation();
            el.classList.remove('drag-over');
            this.onFolderDrop(el.dataset.path);
        },
        handleNewItemClick(el, event) {
            event.stopPropagation();
            this.dropdownTargetFolder = el.dataset.path;
            this.toggleNewDropdown(event);
        },
        handleRenameFolderClick(el, event) {
            event.stopPropagation();
            this.renameFolder(el.dataset.path, el.dataset.name);
        },
        handleDeleteFolderClick(el, event) {
            event.stopPropagation();
            this.deleteFolder(el.dataset.path, el.dataset.name);
        },
        
        // Item (note/media) handlers - read from dataset
        handleItemClick(el) {
            this.openItem(el.dataset.path, el.dataset.type);
        },
        handleItemHover(el, isEnter) {
            const path = el.dataset.path;
            if (path !== this.currentNote && path !== this.currentMedia) {
                el.style.backgroundColor = isEnter ? 'var(--bg-hover)' : 'transparent';
            }
        },
        handleDeleteItemClick(el, event) {
            event.stopPropagation();
            if (el.dataset.type === 'image') {
                this.deleteMedia(el.dataset.path);
            } else {
                this.deleteNote(el.dataset.path, el.dataset.name);
            }
        },
        
        // =====================================================================
        // FOLDER TREE RENDERING
        // =====================================================================
        
        // Render folder recursively (helper for deep nesting)
        // Uses data-* attributes to store path/name, avoiding JS string escaping issues
        renderFolderRecursive(folder, level = 0, isTopLevel = false) {
            if (!folder) return '';
            
            let html = '';
            const isExpanded = this.expandedFolders.has(folder.path);
            const esc = (s) => this.escapeHtmlAttr(s); // Shorthand for HTML escaping
            
            // Render this folder's header
            // Note: Using native event handlers with data-* attributes instead of Alpine directives
            // because x-html doesn't process Alpine directives in dynamically generated content
            html += `
                <div>
                    <div 
                        data-path="${esc(folder.path)}"
                        data-name="${esc(folder.name)}"
                        draggable="true"
                        ondragstart="window.$root.onItemDragStart(this.dataset.path, 'folder', event)"
                        ondragend="window.$root.onItemDragEnd()"
                        ondragover="window.$root.handleFolderDragOver(this, event)"
                        ondragenter="window.$root.handleFolderDragOver(this, event)"
                        ondragleave="window.$root.handleFolderDragLeave(this)"
                        ondrop="window.$root.handleFolderDrop(this, event)"
                        onclick="window.$root.handleFolderClick(this)"
                        class="folder-item hover-accent px-2 py-1 text-sm relative"
                        style="color: var(--text-primary); cursor: pointer;"
                    >
                        <div class="flex items-center gap-1">
                            <button 
                                class="flex-shrink-0 w-4 h-4 flex items-center justify-center"
                                style="color: var(--text-tertiary); cursor: pointer; transition: transform 0.2s; pointer-events: none; margin-left: -5px; ${isExpanded ? 'transform: rotate(90deg);' : ''}"
                            >
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
                                    <path d="M6 4l4 4-4 4V4z"/>
                                </svg>
                            </button>
                            <span class="flex items-center gap-1 flex-1" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; pointer-events: none;" title="${esc(folder.name)}">
                                <span>${esc(folder.name)}</span>
                                ${folder.notes.length === 0 && (!folder.children || Object.keys(folder.children).length === 0) ? `<span class="text-xs" style="color: var(--text-tertiary); font-weight: 400;">(${this.t('folders.empty')})</span>` : ''}
                            </span>
                        </div>
                        <div class="hover-buttons flex gap-1 transition-opacity absolute right-2 top-1/2 transform -translate-y-1/2" style="opacity: 0; pointer-events: none; background: linear-gradient(to right, transparent, var(--bg-hover) 20%, var(--bg-hover)); padding-left: 20px;" onclick="event.stopPropagation()">
                            <button 
                                data-path="${esc(folder.path)}"
                                onclick="window.$root.handleNewItemClick(this, event)"
                                class="px-1.5 py-0.5 text-xs rounded hover:brightness-110"
                                style="background-color: var(--bg-tertiary); color: var(--text-secondary);"
                                title="Add item here"
                            >+</button>
                            <button 
                                data-path="${esc(folder.path)}"
                                data-name="${esc(folder.name)}"
                                onclick="window.$root.handleRenameFolderClick(this, event)"
                                class="px-1.5 py-0.5 text-xs rounded hover:brightness-110"
                                style="background-color: var(--bg-tertiary); color: var(--text-secondary);"
                                title="Rename folder"
                            >✏️</button>
                            <button 
                                data-path="${esc(folder.path)}"
                                data-name="${esc(folder.name)}"
                                onclick="window.$root.handleDeleteFolderClick(this, event)"
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
                html += `<div class="folder-contents" style="padding-left: 10px;">`;
                
                // First, render child folders (if any)
                if (folder.children && Object.keys(folder.children).length > 0) {
                    const children = Object.entries(folder.children)
                        .filter(([k, v]) => !this.hideUnderscoreFolders || !v.name.startsWith('_'))
                        .sort((a, b) => a[1].name.toLowerCase().localeCompare(b[1].name.toLowerCase()));
                    
                    children.forEach(([childKey, childFolder]) => {
                        html += this.renderFolderRecursive(childFolder, 0, false);
                    });
                }
                
                // Then, render notes and images in this folder (after subfolders)
                if (folder.notes && folder.notes.length > 0) {
                    folder.notes.forEach(note => {
                        html += this.renderNoteItem(note);
                    });
                }
                
                html += `</div>`; // Close folder-contents
            }
            
            html += `</div>`; // Close folder wrapper
            return html;
        },
        
        // Render a single note/media item (used by both folders and root level)
        renderNoteItem(note) {
            const esc = (s) => this.escapeHtmlAttr(s);
            const isMediaFile = note.type !== 'note';
            const isCurrentNote = this.currentNote === note.path;
            const isCurrentMedia = this.currentMedia === note.path;
            const isCurrent = isMediaFile ? isCurrentMedia : isCurrentNote;
            
            // Share icon for shared notes
            const isShared = !isMediaFile && this.isNoteShared(note.path);
            const shareIcon = isShared ? '<svg title="Shared" style="display: inline-block; width: 12px; height: 12px; vertical-align: middle; margin-right: 2px; opacity: 0.7;" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"></path></svg>' : '';
            const icon = this.getMediaIcon(note.type);
            
            return `
                <div 
                    data-path="${esc(note.path)}"
                    data-name="${esc(note.name)}"
                    data-type="${note.type}"
                    draggable="true"
                    ondragstart="window.$root.onItemDragStart(this.dataset.path, this.dataset.type || 'note', event)"
                    ondragend="window.$root.onItemDragEnd()"
                    onclick="window.$root.handleItemClick(this)"
                    class="note-item px-2 py-1 text-sm relative"
                    style="${isCurrent ? 'background-color: var(--accent-light); color: var(--accent-primary);' : 'color: var(--text-primary);'} ${isMediaFile ? 'opacity: 0.85;' : ''} cursor: pointer;"
                    onmouseover="window.$root.handleItemHover(this, true)"
                    onmouseout="window.$root.handleItemHover(this, false)"
                >
                    <span class="truncate" style="display: block; padding-right: 30px;" title="${esc(note.name)}">${shareIcon}${icon}${icon ? ' ' : ''}${esc(note.name)}</span>
                    <button 
                        data-path="${esc(note.path)}"
                        data-name="${esc(note.name)}"
                        data-type="${note.type}"
                        onclick="window.$root.handleDeleteItemClick(this, event)"
                        class="note-delete-btn absolute right-2 top-1/2 transform -translate-y-1/2 px-1 py-0.5 text-xs rounded hover:brightness-110 transition-opacity"
                        style="opacity: 0; color: var(--error);"
                        title="${isMediaFile ? 'Delete file' : 'Delete note'}"
                    >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                        </svg>
                    </button>
                </div>
            `;
        },
        
        // Render root-level items (notes and media not in any folder)
        renderRootItems() {
            const root = this.folderTree['__root__'];
            if (!root || !root.notes || root.notes.length === 0) {
                return '';
            }
            return root.notes.map(note => this.renderNoteItem(note)).join('');
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
        },
        
        // Check if folder is expanded
        isFolderExpanded(folderPath) {
            return this.expandedFolders.has(folderPath);
        },
        
        // Expand all folders
        expandAllFolders() {
            this.allFolders.forEach(folder => {
                this.expandedFolders.add(folder);
            });
            // Force Alpine reactivity
            this.expandedFolders = new Set(this.expandedFolders);
        },
        
        // Collapse all folders
        collapseAllFolders() {
            this.expandedFolders.clear();
            // Force Alpine reactivity
            this.expandedFolders = new Set(this.expandedFolders);
        },
        
        // Expand folder tree to show a specific note
        expandFolderForNote(notePath) {
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
            
            // Force Alpine reactivity
            this.expandedFolders = new Set(this.expandedFolders);
        },
        
        // Scroll note into view in the sidebar navigation
        scrollNoteIntoView(notePath) {
            // Find the note element in the sidebar
            // Use a slight delay to ensure DOM is fully rendered with Alpine bindings applied
            setTimeout(() => {
                const sidebar = document.querySelector('.flex-1.overflow-y-auto.custom-scrollbar');
                if (!sidebar) return;
                
                const noteElements = sidebar.querySelectorAll('.note-item');
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
        
        // Unified drag and drop handlers for notes, folders, and media
        onItemDragStart(itemPath, itemType, event) {
            // Set unified drag state
            this.draggedItem = { path: itemPath, type: itemType };
            
            // Make drag image semi-transparent
            if (event.target) {
                event.target.style.opacity = '0.5';
            }
            
            event.dataTransfer.effectAllowed = 'all';
        },
        
        onItemDragEnd() {
            this.draggedItem = null;
            this.dropTarget = null;
            this.dragOverFolder = null;
            // Reset opacity of all draggable items
            document.querySelectorAll('.note-item, .folder-header').forEach(el => el.style.opacity = '1');
            // Reset drag-over class
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
        },
        
        
        // Handle dragover on editor to show cursor position
        onEditorDragOver(event) {
            if (!this.draggedItem) return;
            
            event.preventDefault();
            this.dropTarget = 'editor';
            
            // Focus the textarea
            const textarea = event.target;
            if (textarea.tagName !== 'TEXTAREA') return;
            
            textarea.focus();
            
            // Calculate cursor position from mouse coordinates
            const pos = this.getTextareaCursorFromPoint(textarea, event.clientX, event.clientY);
            if (pos >= 0) {
                textarea.setSelectionRange(pos, pos);
            }
        },
        
        // Calculate textarea cursor position from mouse coordinates
        getTextareaCursorFromPoint(textarea, x, y) {
            const rect = textarea.getBoundingClientRect();
            const style = window.getComputedStyle(textarea);
            const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;
            const paddingTop = parseFloat(style.paddingTop) || 0;
            const paddingLeft = parseFloat(style.paddingLeft) || 0;
            
            // Calculate which line we're on
            const relativeY = y - rect.top - paddingTop + textarea.scrollTop;
            const lineIndex = Math.max(0, Math.floor(relativeY / lineHeight));
            
            // Split content into lines
            const lines = textarea.value.split('\n');
            
            // Find the character position at the start of this line
            let charPos = 0;
            for (let i = 0; i < Math.min(lineIndex, lines.length); i++) {
                charPos += lines[i].length + 1; // +1 for newline
            }
            
            // If we're beyond the last line, position at end
            if (lineIndex >= lines.length) {
                return textarea.value.length;
            }
            
            // Approximate character position within the line based on X coordinate
            const relativeX = x - rect.left - paddingLeft;
            const charWidth = parseFloat(style.fontSize) * 0.6; // Approximate for monospace
            const charInLine = Math.max(0, Math.floor(relativeX / charWidth));
            const lineLength = lines[lineIndex]?.length || 0;
            
            return charPos + Math.min(charInLine, lineLength);
        },
        
        // Handle dragenter on editor
        onEditorDragEnter(event) {
            if (!this.draggedItem) return;
            event.preventDefault();
            this.dropTarget = 'editor';
        },
        
        // Handle dragleave on editor
        onEditorDragLeave(event) {
            // Only clear dropTarget if we're actually leaving the editor
            // (not just moving between child elements)
            if (event.target.tagName === 'TEXTAREA') {
                this.dropTarget = null;
            }
        },
        
        // Handle drop into editor to create internal link or upload media
        async onEditorDrop(event) {
            event.preventDefault();
            this.dropTarget = null;
            
            // Check if files are being dropped (media from file system)
            if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length > 0) {
                await this.handleMediaDrop(event);
                return;
            }
            
            // Otherwise, handle note/media link drop from sidebar
            if (!this.draggedItem) return;
            
            const notePath = this.draggedItem.path;
            const isMediaFile = this.draggedItem.type !== 'note';
            
            let link;
            if (isMediaFile) {
                // For media files (images, audio, video, PDF), use wiki-style embed link
                const filename = notePath.split('/').pop();
                link = `![[${filename}]]`;
            } else {
                // For notes, insert note link
                const noteName = notePath.split('/').pop().replace('.md', '');
                const encodedPath = notePath.split('/').map(segment => encodeURIComponent(segment)).join('/');
                link = `[${noteName}](${encodedPath})`;
            }
            
            // Insert at drop position
            const textarea = event.target;
            // Recalculate position from drop coordinates for accuracy
            let cursorPos = this.getTextareaCursorFromPoint(textarea, event.clientX, event.clientY);
            if (cursorPos < 0) cursorPos = textarea.selectionStart || 0;
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
            
            this.draggedItem = null;
        },
        
        // Handle media files dropped into editor
        async handleMediaDrop(event) {
            if (!this.currentNote) {
                alert(this.t('notes.open_first'));
                return;
            }
            
            const files = Array.from(event.dataTransfer.files);
            
            // Filter for allowed media types
            const allowedTypes = [
                // Images
                'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
                // Audio
                'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/m4a', 'audio/x-m4a',
                // Video
                'video/mp4', 'video/webm', 'video/quicktime',
                // Documents
                'application/pdf'
            ];
            const mediaFiles = files.filter(file => allowedTypes.includes(file.type.toLowerCase()));
            
            if (mediaFiles.length === 0) {
                alert(this.t('media.no_valid_files'));
                return;
            }
            
            const textarea = event.target;
            // Calculate cursor position from drop coordinates
            let cursorPos = this.getTextareaCursorFromPoint(textarea, event.clientX, event.clientY);
            if (cursorPos < 0) cursorPos = textarea.selectionStart || 0;
            
            // Upload each media file
            for (const file of mediaFiles) {
                try {
                    const mediaPath = await this.uploadMedia(file, this.currentNote);
                    if (mediaPath) {
                        await this.insertMediaMarkdown(mediaPath, file.name, cursorPos);
                    }
                } catch (error) {
                    ErrorHandler.handle(`upload file ${file.name}`, error);
                }
            }
        },
        
        // Upload a media file (image, audio, video, PDF)
        async uploadMedia(file, notePath) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('note_path', notePath);
            
            try {
                const response = await fetch('/api/upload-media', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Upload failed');
                }
                
                const data = await response.json();
                return data.path;
            } catch (error) {
                throw error;
            }
        },
        
        // Insert media markdown at cursor position using wiki-style syntax
        // This ensures media links don't break when notes are moved
        async insertMediaMarkdown(mediaPath, altText, cursorPos) {
            // Extract just the filename from the path (e.g., "folder/_attachments/image.png" -> "image.png")
            const filename = mediaPath.split('/').pop();
            
            // Use wiki-style embed link: ![[filename.png]] or ![[filename.png|alt text]]
            // The alt text is optional - only add if different from filename
            const filenameWithoutExt = filename.replace(/\.[^/.]+$/, '');
            const altWithoutExt = altText.replace(/\.[^/.]+$/, '');
            
            // If alt text is meaningful (not just "pasted-image"), include it
            const markdown = (altWithoutExt && altWithoutExt !== filenameWithoutExt && !altWithoutExt.startsWith('pasted-image'))
                ? `![[${filename}|${altWithoutExt}]]`
                : `![[${filename}]]`;
            
            // Reload notes FIRST to update image lookup maps before preview renders
            await this.loadNotes();
            
            const textBefore = this.noteContent.substring(0, cursorPos);
            const textAfter = this.noteContent.substring(cursorPos);
            
            this.noteContent = textBefore + markdown + '\n' + textAfter;
            
            // Trigger autosave
            this.autoSave();
        },
        
        // Handle paste event for clipboard media (images)
        async handlePaste(event) {
            if (!this.currentNote) return;
            
            const items = event.clipboardData?.items;
            if (!items) return;
            
            for (const item of items) {
                if (item.type.startsWith('image/')) {
                    event.preventDefault();
                    
                    const blob = item.getAsFile();
                    if (blob) {
                        try {
                            const textarea = event.target;
                            const cursorPos = textarea.selectionStart || 0;
                            
                            // Create a simple filename - backend will add timestamp to prevent collisions
                            const ext = item.type.split('/')[1] || 'png';
                            const filename = `pasted-image.${ext}`;
                            
                            // Create a File from the blob
                            const file = new File([blob], filename, { type: item.type });
                            
                            const mediaPath = await this.uploadMedia(file, this.currentNote);
                            if (mediaPath) {
                                await this.insertMediaMarkdown(mediaPath, filename, cursorPos);
                            }
                        } catch (error) {
                            ErrorHandler.handle('paste media', error);
                        }
                    }
                    break; // Only handle first media item
                }
            }
        },
        
        // Media type detection based on file extension
        getMediaType(filename) {
            if (!filename) return null;
            const ext = filename.split('.').pop().toLowerCase();
            const mediaTypes = {
                image: ['jpg', 'jpeg', 'png', 'gif', 'webp'],
                audio: ['mp3', 'wav', 'ogg', 'm4a'],
                video: ['mp4', 'webm', 'mov', 'avi'],
                document: ['pdf'],
            };
            for (const [type, extensions] of Object.entries(mediaTypes)) {
                if (extensions.includes(ext)) return type;
            }
            return null;
        },
        
        // Get icon for media type
        getMediaIcon(type) {
            const icons = {
                image: '🖼️',
                audio: '🎵',
                video: '🎬',
                document: '📄',
            };
            return icons[type] || '';
        },
        
        // Open a note or media file (unified handler for sidebar/homepage clicks)
        openItem(path, type = 'note', searchHighlight = '') {
            this.showGraph = false;
            // Check if it's a media file by type or extension
            const mediaType = type !== 'note' ? type : this.getMediaType(path);
            if (mediaType && mediaType !== 'note') {
                this.viewMedia(path, mediaType);
            } else {
                this.loadNote(path, true, searchHighlight);
            }
        },
        
        // View a media file (image, audio, video, PDF) in the main pane
        viewMedia(mediaPath, mediaType = null, updateHistory = true) {
            this.showGraph = false; // Ensure graph is closed
            this.currentNote = '';
            this.currentNoteName = '';
            this.noteContent = '';
            this.currentMedia = mediaPath; // Reuse currentMedia for all media
            this.currentMediaType = mediaType || this.getMediaType(mediaPath) || 'image';
            this.shareInfo = null; // Reset share info
            this.viewMode = 'preview'; // Use preview mode to show media
            
            // Update browser tab title
            const fileName = mediaPath.split('/').pop();
            document.title = `${fileName} - ${this.appName}`;
            
            // Expand folder tree to show the media file
            this.expandFolderForNote(mediaPath);
            
            // Update browser URL
            if (updateHistory) {
                // Encode each path segment to handle special characters
                const encodedPath = mediaPath.split('/').map(segment => encodeURIComponent(segment)).join('/');
                window.history.pushState(
                    { mediaPath: mediaPath },
                    '',
                    `/${encodedPath}`
                );
            }
        },
        
        // Backward compatibility alias
        viewImage(mediaPath, updateHistory = true) {
            this.viewMedia(mediaPath, 'image', updateHistory);
        },
        
        // Delete a media file (image, audio, video, PDF)
        async deleteMedia(mediaPath) {
            const filename = mediaPath.split('/').pop();
            if (!confirm(this.t('media.confirm_delete', { name: filename }))) return;
            
            try {
                const response = await fetch(`/api/notes/${encodeURIComponent(mediaPath)}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    await this.loadNotes(); // Refresh tree
                    
                    // Clear viewer if deleting currently viewed media
                    if (this.currentMedia === mediaPath) {
                        this.currentMedia = '';
                    }
                } else {
                    throw new Error('Failed to delete media file');
                }
            } catch (error) {
                ErrorHandler.handle('delete media', error);
            }
        },
        
        // Handle clicks on internal links in preview
        handleInternalLink(event) {
            // Check if clicked element is a link
            const link = event.target.closest('a');
            if (!link) return;
            
            const href = link.getAttribute('href');
            if (!href) return;
            
            // Check if it's an external link or API path (media files, etc.)
            if (href.startsWith('http://') || href.startsWith('https://') || href.startsWith('//') || href.startsWith('mailto:') || href.startsWith('/api/')) {
                return; // Let external links and API paths work normally
            }
            
            // Prevent default navigation for internal links
            event.preventDefault();
            
            // Parse href into note path and anchor (e.g., "note.md#section" -> notePath="note.md", anchor="section")
            const decodedHref = decodeURIComponent(href);
            const hashIndex = decodedHref.indexOf('#');
            const notePath = hashIndex !== -1 ? decodedHref.substring(0, hashIndex) : decodedHref;
            const anchor = hashIndex !== -1 ? decodedHref.substring(hashIndex + 1) : null;
            
            // If it's just an anchor link (#heading), scroll within current note
            if (!notePath && anchor) {
                this.scrollToAnchor(anchor);
                return;
            }
            
            // Skip if no path
            if (!notePath) return;
            
            // Find the note by path (try exact match first, then with .md extension)
            let targetNote = this.notes.find(n => 
                n.path === notePath || 
                n.path === notePath + '.md'
            );
            
            if (!targetNote) {
                // Try to find by name (in case link uses just the note name without path)
                targetNote = this.notes.find(n => 
                    n.name === notePath || 
                    n.name === notePath + '.md' ||
                    n.name.toLowerCase() === notePath.toLowerCase() ||
                    n.name.toLowerCase() === (notePath + '.md').toLowerCase()
                );
            }
            
            if (!targetNote) {
                // Last resort: case-insensitive path matching
                targetNote = this.notes.find(n => 
                    n.path.toLowerCase() === notePath.toLowerCase() ||
                    n.path.toLowerCase() === (notePath + '.md').toLowerCase()
                );
            }
            
            if (targetNote) {
                // Load the note, then scroll to anchor if present
                this.loadNote(targetNote.path).then(() => {
                    if (anchor) {
                        // Small delay to ensure content is rendered
                        setTimeout(() => this.scrollToAnchor(anchor), 100);
                    }
                });
            } else if (confirm(this.t('notes.create_from_link', { path: notePath }))) {
                // Note doesn't exist - create it (reuses createNote with duplicate check)
                this.createNote(null, notePath);
            }
        },
        
        // Scroll to an anchor (heading) by slug - reuses outline data
        scrollToAnchor(anchor) {
            // Normalize the anchor (GitHub-style slug)
            const targetSlug = anchor
                .toLowerCase()
                .replace(/[^\w\s-]/g, '')
                .replace(/\s+/g, '-')
                .replace(/-+/g, '-');
            
            // Find matching heading in outline
            const heading = this.outline.find(h => h.slug === targetSlug);
            
            if (heading) {
                this.scrollToHeading(heading);
            } else {
                // Fallback: try to find heading by exact text match
                const headingByText = this.outline.find(h => 
                    h.text.toLowerCase().replace(/\s+/g, '-') === anchor.toLowerCase()
                );
                if (headingByText) {
                    this.scrollToHeading(headingByText);
                }
            }
        },
        
        
        cancelDrag() {
            // Cancel any active drag operation (triggered by ESC key)
            this.draggedItem = null;
            this.dropTarget = null;
            this.dragOverFolder = null;
            // Reset styles - only query elements with drag-over class (more efficient)
            document.querySelectorAll('.folder-item').forEach(el => el.style.opacity = '1');
            document.querySelectorAll('.note-item').forEach(el => el.style.opacity = '1');
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
        },
        
        async onFolderDrop(targetFolderPath) {
            // Ignore if we're dropping into the editor
            if (this.dropTarget === 'editor') {
                return;
            }
            
            // Capture dragged item info immediately (ondragend may clear it)
            if (!this.draggedItem) return;
            const { path: draggedPath, type: draggedType } = this.draggedItem;
            
            // Determine item category for endpoint selection
            const isFolder = draggedType === 'folder';
            const isNote = draggedType === 'note';
            const isMedia = !isFolder && !isNote; // image, audio, video, document
            
            // Handle folder drop
            if (isFolder) {
                // Prevent dropping folder into itself or its subfolders
                if (targetFolderPath === draggedPath || 
                    targetFolderPath.startsWith(draggedPath + '/')) {
                    alert(this.t('folders.cannot_move_into_self'));
                    return;
                }
                
                const folderName = draggedPath.split('/').pop();
                const newPath = targetFolderPath ? `${targetFolderPath}/${folderName}` : folderName;
                
                if (newPath === draggedPath) return;
                
                // Capture favorites info before async call
                const oldPrefix = draggedPath + '/';
                const newPrefix = newPath + '/';
                
                try {
                    const response = await fetch('/api/folders/move', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ oldPath: draggedPath, newPath })
                    });
                    
                    if (response.ok) {
                        // Update favorites for notes inside moved folder
                        const favoritesInFolder = this.favorites.filter(f => f.startsWith(oldPrefix));
                        if (favoritesInFolder.length > 0) {
                            const newFavorites = this.favorites.map(f => 
                                f.startsWith(oldPrefix) ? newPrefix + f.substring(oldPrefix.length) : f
                            );
                            this.favorites = newFavorites;
                            this.favoritesSet = new Set(newFavorites);
                            this.saveFavorites();
                        }
                        
                        // Keep folder expanded if it was
                        const wasExpanded = this.expandedFolders.has(draggedPath);
                        
                        await this.loadNotes();
                        await this.loadSharedNotePaths();
                        
                        if (wasExpanded) {
                            this.expandedFolders.delete(draggedPath);
                            this.expandedFolders.add(newPath);
                            this.saveExpandedFolders();
                        }
                    } else {
                        const errorData = await response.json().catch(() => ({}));
                        alert(errorData.detail || this.t('move.failed_folder'));
                    }
                } catch (error) {
                    console.error('Failed to move folder:', error);
                    alert(this.t('move.failed_folder'));
                }
                return;
            }
            
            // Handle note or media drop into folder
            const item = this.notes.find(n => n.path === draggedPath);
            if (!item) return;
            
            const filename = draggedPath.split('/').pop();
            const newPath = targetFolderPath ? `${targetFolderPath}/${filename}` : filename;
            
            if (newPath === draggedPath) return;
            
            // Check if note is favorited (only for notes)
            const wasFavorited = isNote && this.favoritesSet.has(draggedPath);
            
            try {
                // Use different endpoint for media vs notes
                const endpoint = isMedia ? '/api/media/move' : '/api/notes/move';
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ oldPath: draggedPath, newPath })
                });
                
                if (response.ok) {
                    // Update favorites if the moved note was favorited
                    if (wasFavorited) {
                        const newFavorites = this.favorites.map(f => f === draggedPath ? newPath : f);
                        this.favorites = newFavorites;
                        this.favoritesSet = new Set(newFavorites);
                        this.saveFavorites();
                    }
                    
                    // Keep current item open if it was the moved one
                    const wasCurrentNote = this.currentNote === draggedPath;
                    const wasCurrentMedia = this.currentMedia === draggedPath;
                    
                    await this.loadNotes();
                    if (isNote) {
                        await this.loadSharedNotePaths();
                    }
                    
                    if (wasCurrentNote) this.currentNote = newPath;
                    if (wasCurrentMedia) this.currentMedia = newPath;
                } else {
                    const errorData = await response.json().catch(() => ({}));
                    const errorKey = isMedia ? 'move.failed_media' : 'move.failed_note';
                    alert(errorData.detail || this.t(errorKey));
                }
            } catch (error) {
                console.error(`Failed to move ${isMedia ? 'media' : 'note'}:`, error);
                const errorKey = isMedia ? 'move.failed_media' : 'move.failed_note';
                alert(this.t(errorKey));
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
                        window.history.replaceState({ homepageFolder: this.selectedHomepageFolder || '' }, '', '/');
                        this.currentNote = '';
                        this.noteContent = '';
                        this.currentMedia = '';
                        document.title = this.appName;
                        return;
                    }
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                
                this.currentNote = notePath;
                this._lastRenderedContent = ''; // Clear render cache for new note
                this._cachedRenderedHTML = '';
                this._initializedVideoSources = new Set(); // Clear video cache for new note
                this.noteContent = data.content;
                this.currentNoteName = notePath.split('/').pop().replace('.md', '');
                this.currentMedia = ''; // Clear image viewer when loading a note
                this.shareInfo = null; // Reset share info for new note
                
                // Update browser tab title
                document.title = `${this.currentNoteName} - ${this.appName}`;
                this.lastSaved = false;
                
                // Extract outline for TOC panel
                this.extractOutline(data.content);
                
                // Initialize undo/redo history for this note (with cursor at start)
                this.undoHistory = [{ content: data.content, cursorPos: 0 }];
                this.redoHistory = [];
                this.hasPendingHistoryChanges = false;
                
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
                        { 
                            notePath: notePath, 
                            searchQuery: searchQuery,
                            homepageFolder: this.selectedHomepageFolder || '' // Save current folder state
                        },
                        '',
                        url
                    );
                }
                
                // Calculate stats if plugin enabled
                if (this.statsPluginEnabled) {
                    this.calculateStats();
                }
                
                // Parse frontmatter metadata
                this.parseMetadata();
                
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
        
        // Load item (note or media) from URL path
        loadItemFromURL() {
            // Get path from URL (e.g., /folder/note or /folder/image.png)
            let path = window.location.pathname;
            
            // Strip .md extension if present (for MKdocs/Zensical integration)
            if (path.toLowerCase().endsWith('.md')) {
                path = path.slice(0, -3);
                // Update URL bar to show clean path without .md
                window.history.replaceState(null, '', path);
            }
            
            // Skip if root path or static assets
            if (path === '/' || path.startsWith('/static/') || path.startsWith('/api/')) {
                return;
            }
            
            // Remove leading slash and decode URL encoding (e.g., %20 -> space)
            const decodedPath = decodeURIComponent(path.substring(1));
            
            // Check if this is a media file (image, audio, video, PDF)
            const matchedItem = this.notes.find(n => n.path === decodedPath);
            
            if (matchedItem && matchedItem.type !== 'note') {
                // It's a media file, view it
                this.viewMedia(decodedPath, matchedItem.type, false); // false = don't update history
            } else {
                // It's a note, add .md extension and load it
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
                        
                        // First match is active (styled via CSS)
                        if (matchIndex === 0) {
                            mark.classList.add('active-match');
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
            
            // Update styling - make current match prominent (via CSS class)
            allMatches.forEach((mark, i) => {
                mark.classList.toggle('active-match', i === index);
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
        
        toggleNewDropdown(event) {
            this.showNewDropdown = true; // Always open (or keep open)
            
            if (event && event.target) {
                const rect = event.target.getBoundingClientRect();
                // Position dropdown next to the clicked element
                let top = rect.bottom + 4; // 4px spacing
                let left = rect.left;
                
                // Keep dropdown on screen
                const dropdownWidth = 200;
                const dropdownHeight = 150;
                if (left + dropdownWidth > window.innerWidth) {
                    left = rect.right - dropdownWidth;
                }
                if (top + dropdownHeight > window.innerHeight) {
                    top = rect.top - dropdownHeight - 4;
                }
                
                this.dropdownPosition = { top, left };
            }
        },
        
        closeDropdown() {
            this.showNewDropdown = false;
            this.dropdownTargetFolder = null; // Reset folder context
        },
        
        // =====================================================
        // UNIFIED CREATION FUNCTIONS (reusable from anywhere)
        // =====================================================
        
        // Switch to split view (if in preview-only mode) and focus editor for new notes
        focusEditorForNewNote() {
            // Only switch if in preview-only mode - don't disturb edit or split mode
            if (this.viewMode === 'preview') {
                this.viewMode = 'split';
                this.saveViewMode();
            }
            // Focus the editor after a short delay to ensure DOM is updated
            this.$nextTick(() => {
                const editor = document.getElementById('note-editor');
                if (editor) editor.focus();
            });
        },
        
        async createNote(folderPath = null, directPath = null) {
            let notePath;
            
            if (directPath) {
                // Direct path provided (e.g., from wiki link) - skip prompting
                notePath = directPath.endsWith('.md') ? directPath : `${directPath}.md`;
            } else {
                // Use provided folder path, or dropdown target folder context, or homepage folder
                // Note: Check dropdownTargetFolder !== null to distinguish between '' (root) and not set
                let targetFolder;
                if (folderPath !== null) {
                    targetFolder = folderPath;
                } else if (this.dropdownTargetFolder !== null && this.dropdownTargetFolder !== undefined) {
                    targetFolder = this.dropdownTargetFolder; // Can be '' for root or a folder path
                } else {
                    targetFolder = this.selectedHomepageFolder || '';
                }
                this.closeDropdown();
                
                const promptText = targetFolder 
                    ? this.t('notes.prompt_name_in_folder', { folder: targetFolder })
                    : this.t('notes.prompt_name_with_path');
                
                const noteName = prompt(promptText);
                if (!noteName) return;
                
                // Validate the name/path (may contain / for paths when no target folder)
                const validation = targetFolder 
                    ? FilenameValidator.validateFilename(noteName)
                    : FilenameValidator.validatePath(noteName);
                
                if (!validation.valid) {
                    alert(this.getValidationErrorMessage(validation, 'note'));
                    return;
                }
                
                const validatedName = validation.sanitized;
                
                if (targetFolder) {
                    notePath = `${targetFolder}/${validatedName}.md`;
                } else {
                    notePath = validatedName.endsWith('.md') ? validatedName : `${validatedName}.md`;
                }
            }
            
            // CRITICAL: Check if note already exists (applies to both prompt and direct path)
            const existingNote = this.notes.find(note => note.path === notePath);
            if (existingNote) {
                alert(this.t('notes.already_exists', { name: notePath }));
                return;
            }
            
            try {
                const response = await fetch(`/api/notes/${notePath}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: '' })
                });
                
                if (response.ok) {
                    // Expand parent folder if note is in a subfolder
                    const folderPart = notePath.includes('/') ? notePath.substring(0, notePath.lastIndexOf('/')) : '';
                    if (folderPart) this.expandedFolders.add(folderPart);
                    await this.loadNotes();
                    await this.loadNote(notePath);
                    this.focusEditorForNewNote();
                } else {
                    ErrorHandler.handle('create note', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('create note', error);
            }
        },
        
        async createFolder(parentPath = null) {
            // Use provided parent path, or dropdown target folder context, or homepage folder
            // Note: Check dropdownTargetFolder !== null to distinguish between '' (root) and not set
            let targetFolder;
            if (parentPath !== null) {
                targetFolder = parentPath;
            } else if (this.dropdownTargetFolder !== null && this.dropdownTargetFolder !== undefined) {
                targetFolder = this.dropdownTargetFolder; // Can be '' for root or a folder path
            } else {
                targetFolder = this.selectedHomepageFolder || '';
            }
            this.closeDropdown();
            
            const promptText = targetFolder 
                ? this.t('folders.prompt_name_in_folder', { folder: targetFolder })
                : this.t('folders.prompt_name_with_path');
            
            const folderName = prompt(promptText);
            if (!folderName) return;
            
            // Validate the name/path (may contain / for paths when no target folder)
            const validation = targetFolder 
                ? FilenameValidator.validateFilename(folderName)
                : FilenameValidator.validatePath(folderName);
            
            if (!validation.valid) {
                alert(this.getValidationErrorMessage(validation, 'folder'));
                return;
            }
            
            const validatedName = validation.sanitized;
            const folderPath = targetFolder ? `${targetFolder}/${validatedName}` : validatedName;
            
            // Check if folder already exists
            const existingFolder = this.allFolders.find(folder => folder === folderPath);
            if (existingFolder) {
                alert(this.t('folders.already_exists', { name: validatedName }));
                return;
            }
            
            try {
                const response = await fetch('/api/folders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: folderPath })
                });
                
                if (response.ok) {
                    if (targetFolder) {
                        this.expandedFolders.add(targetFolder);
                    }
                    this.expandedFolders.add(folderPath);
                    await this.loadNotes();
                    
                    // Navigate to the newly created folder on the homepage
                    this.goToHomepageFolder(folderPath);
                } else {
                    ErrorHandler.handle('create folder', new Error('Server returned error'));
                }
            } catch (error) {
                ErrorHandler.handle('create folder', error);
            }
        },
        
        // Rename a folder
        async renameFolder(folderPath, currentName) {
            const newName = prompt(this.t('folders.prompt_rename', { name: currentName }), currentName);
            if (!newName || newName === currentName) return;
            
            // Validate the new name (single segment, no path separators)
            const validation = FilenameValidator.validateFilename(newName);
            if (!validation.valid) {
                alert(this.getValidationErrorMessage(validation, 'folder'));
                return;
            }
            
            const validatedName = validation.sanitized;
            
            // Calculate new path
            const pathParts = folderPath.split('/');
            pathParts[pathParts.length - 1] = validatedName;
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
                    
                    // Update favorites that were in the renamed folder
                    const folderPrefix = folderPath + '/';
                    const newFolderPrefix = newPath + '/';
                    const newFavorites = this.favorites.map(f => {
                        if (f.startsWith(folderPrefix)) {
                            return f.replace(folderPrefix, newFolderPrefix);
                        }
                        return f;
                    });
                    // Check if anything changed
                    if (JSON.stringify(newFavorites) !== JSON.stringify(this.favorites)) {
                        this.favorites = newFavorites;
                        this.favoritesSet = new Set(newFavorites);
                        this.saveFavorites();
                    }
                    
                    // Update current note path if it's in the renamed folder
                    if (this.currentNote && this.currentNote.startsWith(folderPrefix)) {
                        this.currentNote = this.currentNote.replace(folderPrefix, newFolderPrefix);
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
            const confirmation = confirm(this.t('folders.confirm_delete', { name: folderName }));
            
            if (!confirmation) return;
            
            try {
                const response = await fetch(`/api/folders/${encodeURIComponent(folderPath)}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                if (response.ok) {
                    // Remove from expanded folders
                    this.expandedFolders.delete(folderPath);
                    
                    // Remove any favorites that were in the deleted folder
                    const folderPrefix = folderPath + '/';
                    const newFavorites = this.favorites.filter(f => !f.startsWith(folderPrefix));
                    if (newFavorites.length !== this.favorites.length) {
                        this.favorites = newFavorites;
                        this.favoritesSet = new Set(newFavorites);
                        this.saveFavorites();
                    }
                    
                    // Clear current note if it was in the deleted folder
                    if (this.currentNote && this.currentNote.startsWith(folderPrefix)) {
                        this.currentNote = '';
                        this.noteContent = '';
                        document.title = this.appName;
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
            
            // Parse metadata in real-time
            this.parseMetadata();
            
            // Update outline (TOC) in real-time
            this.extractOutline(this.noteContent);
            
            this.saveTimeout = setTimeout(() => {
                // Commit to undo history when autosave triggers (same debounce timing)
                if (this.hasPendingHistoryChanges) {
                    this.commitToHistory();
                }
                this.saveNote();
            }, CONFIG.AUTOSAVE_DELAY);
        },
        
        // Mark that we have pending changes (called on each keystroke)
        pushToHistory() {
            this.hasPendingHistoryChanges = true;
        },
        
        // Immediately commit pending changes to history (call before undo/redo)
        flushHistory() {
            if (this.hasPendingHistoryChanges) {
                this.commitToHistory();
            }
        },
        
        // Actually commit to undo history (internal)
        commitToHistory() {
            const editor = document.getElementById('note-editor');
            const cursorPos = editor ? editor.selectionStart : 0;
            
            // Only push if content actually changed from last history entry
            if (this.undoHistory.length > 0 && 
                this.undoHistory[this.undoHistory.length - 1].content === this.noteContent) {
                this.hasPendingHistoryChanges = false;
                return;
            }
            
            this.undoHistory.push({ content: this.noteContent, cursorPos });
            
            // Limit history size
            if (this.undoHistory.length > this.maxHistorySize) {
                this.undoHistory.shift();
            }
            
            // Clear redo history when new change is made
            this.redoHistory = [];
            this.hasPendingHistoryChanges = false;
        },
        
        // Undo last change
        undo() {
            if (!this.currentNote) return;
            
            // Flush any pending history changes first (so we don't lose unsaved edits)
            this.flushHistory();
            
            if (this.undoHistory.length <= 1) return;
            
            const editor = document.getElementById('note-editor');
            
            // Pop current state to redo history
            const currentState = this.undoHistory.pop();
            this.redoHistory.push(currentState);
            
            // Get previous state
            const previousState = this.undoHistory[this.undoHistory.length - 1];
            
            // Apply previous state
            this.isUndoRedo = true;
            this.noteContent = previousState.content;
            
            // Recalculate stats with new content
            if (this.statsPluginEnabled) {
                this.calculateStats();
            }
            
            // Restore cursor position from the state we're going back to
            this.$nextTick(() => {
                this.saveNote();
                this.isUndoRedo = false;
                if (editor) {
                    setTimeout(() => {
                        const newPos = Math.min(previousState.cursorPos, this.noteContent.length);
                        editor.setSelectionRange(newPos, newPos);
                        editor.focus();
                    }, 0);
                }
            });
        },
        
        // Redo last undone change
        redo() {
            if (!this.currentNote) return;
            
            // Flush any pending history changes first
            this.flushHistory();
            
            if (this.redoHistory.length === 0) return;
            
            const editor = document.getElementById('note-editor');
            
            // Pop from redo history
            const nextState = this.redoHistory.pop();
            
            // Push to undo history
            this.undoHistory.push(nextState);
            
            // Apply next state
            this.isUndoRedo = true;
            this.noteContent = nextState.content;
            
            // Recalculate stats with new content
            if (this.statsPluginEnabled) {
                this.calculateStats();
            }
            
            // Restore cursor position from the state we're going forward to
            this.$nextTick(() => {
                this.saveNote();
                this.isUndoRedo = false;
                if (editor) {
                    setTimeout(() => {
                        const newPos = Math.min(nextState.cursorPos, this.noteContent.length);
                        editor.setSelectionRange(newPos, newPos);
                        editor.focus();
                    }, 0);
                }
            });
        },
        
        // Markdown formatting helpers
        wrapSelection(before, after, placeholder) {
            const editor = document.getElementById('note-editor');
            if (!editor) return;
            
            const start = editor.selectionStart;
            const end = editor.selectionEnd;
            const selectedText = this.noteContent.substring(start, end);
            const textToWrap = selectedText || placeholder;
            
            // Build the new text
            const newText = before + textToWrap + after;
            
            // Update content
            this.noteContent = this.noteContent.substring(0, start) + newText + this.noteContent.substring(end);
            
            // Set cursor position (select the wrapped text or placeholder)
            this.$nextTick(() => {
                if (selectedText) {
                    // If text was selected, keep it selected (inside the wrapper)
                    editor.setSelectionRange(start + before.length, start + before.length + selectedText.length);
                } else {
                    // If no text selected, select the placeholder
                    editor.setSelectionRange(start + before.length, start + before.length + placeholder.length);
                }
                editor.focus();
            });
            
            // Trigger autosave
            this.autoSave();
        },
        
        insertLink() {
            const editor = document.getElementById('note-editor');
            if (!editor) return;
            
            const start = editor.selectionStart;
            const end = editor.selectionEnd;
            const selectedText = this.noteContent.substring(start, end);
            
            // If text is selected, use it as link text; otherwise use placeholder
            const linkText = selectedText || 'link text';
            const linkUrl = 'url';
            
            // Build the markdown link
            const newText = `[${linkText}](${linkUrl})`;
            
            // Update content
            this.noteContent = this.noteContent.substring(0, start) + newText + this.noteContent.substring(end);
            
            // Set cursor position to select the URL part for easy editing
            this.$nextTick(() => {
                const urlStart = start + linkText.length + 3; // After "[linkText]("
                const urlEnd = urlStart + linkUrl.length;
                editor.setSelectionRange(urlStart, urlEnd);
                editor.focus();
            });
            
            // Trigger autosave
            this.autoSave();
        },
        
        // Insert a markdown table placeholder
        insertTable() {
            const editor = document.getElementById('note-editor');
            if (!editor) return;
            
            const cursorPos = editor.selectionStart;
            
            // Basic 3x3 table placeholder
            const table = `| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Cell 1   | Cell 2   | Cell 3   |
| Cell 4   | Cell 5   | Cell 6   |
`;
            
            // Add newline before if not at start of line
            const textBefore = this.noteContent.substring(0, cursorPos);
            const needsNewlineBefore = textBefore.length > 0 && !textBefore.endsWith('\n');
            const prefix = needsNewlineBefore ? '\n\n' : '';
            
            // Insert the table
            this.noteContent = textBefore + prefix + table + this.noteContent.substring(cursorPos);
            
            // Position cursor at first header for easy editing
            this.$nextTick(() => {
                const newPos = cursorPos + prefix.length + 2; // After "| "
                editor.setSelectionRange(newPos, newPos + 8); // Select "Header 1"
                editor.focus();
            });
            
            // Trigger autosave
            this.autoSave();
        },
        
        // Format selected text or insert formatting at cursor
        formatText(type) {
            // Simple wrap cases - reuse wrapSelection()
            const wrapFormats = {
                'bold': ['**', '**', 'bold'],
                'italic': ['*', '*', 'italic'],
                'strikethrough': ['~~', '~~', 'strikethrough'],
                'code': ['`', '`', 'code']
            };
            
            if (wrapFormats[type]) {
                const [before, after, placeholder] = wrapFormats[type];
                this.wrapSelection(before, after, placeholder);
                return;
            }
            
            // Special cases that need custom handling
            switch (type) {
                case 'heading':
                    this.insertLinePrefix('## ', 'Heading');
                    break;
                case 'quote':
                    this.insertLinePrefix('> ', 'quote');
                    break;
                case 'bullet':
                    this.insertLinePrefix('- ', 'item');
                    break;
                case 'numbered':
                    this.insertLinePrefix('1. ', 'item');
                    break;
                case 'checkbox':
                    this.insertLinePrefix('- [ ] ', 'task');
                    break;
                case 'link':
                    this.insertLink();
                    break;
                case 'image':
                    this.wrapSelection('![', '](image-url)', 'alt text');
                    break;
                case 'codeblock':
                    this.wrapSelection('```\n', '\n```', 'code');
                    break;
                case 'table':
                    this.insertTable();
                    break;
            }
        },
        
        // Insert a line prefix (for headings, lists, quotes)
        insertLinePrefix(prefix, placeholder) {
            const editor = document.getElementById('note-editor');
            if (!editor) return;
            
            const start = editor.selectionStart;
            const end = editor.selectionEnd;
            const selectedText = this.noteContent.substring(start, end);
            const beforeText = this.noteContent.substring(0, start);
            const afterText = this.noteContent.substring(end);
            
            // Check if at start of line
            const atLineStart = beforeText.endsWith('\n') || beforeText === '';
            const newline = atLineStart ? '' : '\n';
            
            let replacement;
            if (selectedText) {
                // Prefix each line of selection
                replacement = newline + selectedText.split('\n').map((line, i) => {
                    // For numbered lists, increment the number
                    if (prefix === '1. ') return `${i + 1}. ${line}`;
                    return prefix + line;
                }).join('\n');
            } else {
                replacement = newline + prefix + placeholder;
            }
            
            this.noteContent = beforeText + replacement + afterText;
            
            this.$nextTick(() => {
                if (selectedText) {
                    editor.setSelectionRange(start + newline.length, start + replacement.length);
                } else {
                    const placeholderStart = start + newline.length + prefix.length;
                    editor.setSelectionRange(placeholderStart, placeholderStart + placeholder.length);
                }
                editor.focus();
            });
            
            this.autoSave();
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
                        note.size = new Blob([this.noteContent]).size;
                        
                        // Parse tags from content
                        note.tags = this.parseTagsFromContent(this.noteContent);
                    }
                    
                    // Reload tags to update sidebar counts (debounced to prevent spam)
                    this.loadTagsDebounced();
                    
                    // Rebuild folder tree if tag filters are active
                    if (this.selectedTags.length > 0) {
                        this.buildFolderTree();
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
                alert(this.t('notes.empty_name'));
                return;
            }
            
            // Validate the new name (single segment, no path separators)
            const validation = FilenameValidator.validateFilename(newName);
            if (!validation.valid) {
                alert(this.getValidationErrorMessage(validation, 'note'));
                // Reset the name in the UI
                this.currentNoteName = oldPath.split('/').pop().replace('.md', '');
                return;
            }
            
            const validatedName = validation.sanitized;
            const folder = oldPath.split('/').slice(0, -1).join('/');
            const newPath = folder ? `${folder}/${validatedName}.md` : `${validatedName}.md`;
            
            if (oldPath === newPath) return;
            
            // Check if a note with the new name already exists
            const existingNote = this.notes.find(n => n.path.toLowerCase() === newPath.toLowerCase());
            if (existingNote) {
                alert(this.t('notes.already_exists', { name: validatedName }));
                // Reset the name in the UI
                this.currentNoteName = oldPath.split('/').pop().replace('.md', '');
                return;
            }
            
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
                    
                    // Update favorites if the renamed note was favorited
                    if (this.favoritesSet.has(oldPath)) {
                        const newFavorites = this.favorites.map(f => f === oldPath ? newPath : f);
                        this.favorites = newFavorites;
                        this.favoritesSet = new Set(newFavorites);
                        this.saveFavorites();
                    }
                    
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
            
            // Just call deleteNote with current note details
            await this.deleteNote(this.currentNote, this.currentNoteName);
        },
        
        // Delete any note from sidebar
        async deleteNote(notePath, noteName) {
            if (!confirm(this.t('notes.confirm_delete', { name: noteName }))) return;
            
            try {
                const response = await fetch(`/api/notes/${notePath}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    // Remove from favorites if it was favorited
                    if (this.favoritesSet.has(notePath)) {
                        const newFavorites = this.favorites.filter(f => f !== notePath);
                        this.favorites = newFavorites;
                        this.favoritesSet = new Set(newFavorites);
                        this.saveFavorites();
                    }
                    
                    // If the deleted note is currently open, clear it
                    if (this.currentNote === notePath) {
                        this.currentNote = '';
                        this.noteContent = '';
                        this.currentNoteName = '';
                        this._lastRenderedContent = ''; // Clear render cache
                        this._cachedRenderedHTML = '';
                        document.title = this.appName;
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
        debouncedSearchNotes() {
            if (this.searchDebounceTimeout) {
                clearTimeout(this.searchDebounceTimeout);
            }

            const hasTextSearch = this.searchQuery.trim().length > 0;
            if (!hasTextSearch) {
                this.isSearching = false;
                this.searchNotes();
                return;
            }

            this.isSearching = true;
            this.searchResults = [];

            this.searchDebounceTimeout = setTimeout(() => {
                this.searchNotes();
            }, CONFIG.SEARCH_DEBOUNCE_DELAY);
        },

        // Search notes by text (calls unified filter logic)
        async searchNotes() {
            await this.applyFilters();
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
                        fontFamily: 'inherit',
                        // v11 changed useMaxWidth defaults - restore responsive behavior
                        flowchart: { useMaxWidth: true },
                        sequence: { useMaxWidth: true },
                        gantt: { useMaxWidth: true },
                        journey: { useMaxWidth: true },
                        timeline: { useMaxWidth: true },
                        class: { useMaxWidth: true },
                        state: { useMaxWidth: true },
                        er: { useMaxWidth: true },
                        pie: { useMaxWidth: true },
                        quadrantChart: { useMaxWidth: true },
                        requirement: { useMaxWidth: true },
                        mindmap: { useMaxWidth: true },
                        gitGraph: { useMaxWidth: true }
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
            
            // Performance: Return cached HTML if content hasn't changed
            if (this.noteContent === this._lastRenderedContent && this._cachedRenderedHTML) {
                return this._cachedRenderedHTML;
            }
            
            // Strip YAML frontmatter from content before rendering
            let contentToRender = this.noteContent;
            if (contentToRender.trim().startsWith('---')) {
                const lines = contentToRender.split('\n');
                if (lines[0].trim() === '---') {
                    // Find closing ---
                    let endIdx = -1;
                    for (let i = 1; i < lines.length; i++) {
                        if (lines[i].trim() === '---') {
                            endIdx = i;
                            break;
                        }
                    }
                    if (endIdx !== -1) {
                        // Remove frontmatter (including the closing ---) and any empty lines after it
                        contentToRender = lines.slice(endIdx + 1).join('\n').trim();
                    }
                }
            }
            
            // Convert Obsidian-style wikilinks: [[note]] or [[note|display text]]
            // Must be done before marked.parse() to avoid conflicts with markdown syntax
            // BUT we need to protect code blocks first to avoid converting [[text]] inside code
            const self = this; // Reference for closure
            
            // Step 1: Temporarily replace code blocks and inline code with placeholders
            const codeBlocks = [];
            // Protect fenced code blocks (```...```)
            contentToRender = contentToRender.replace(/```[\s\S]*?```/g, (match) => {
                codeBlocks.push(match);
                return `\x00CODEBLOCK${codeBlocks.length - 1}\x00`;
            });
            // Protect inline code (`...`)
            contentToRender = contentToRender.replace(/`[^`]+`/g, (match) => {
                codeBlocks.push(match);
                return `\x00CODEBLOCK${codeBlocks.length - 1}\x00`;
            });
            
            // Step 2: Convert media wikilinks FIRST: ![[file.png]] or ![[file.png|alt text]]
            // Must be before note wikilinks to prevent [[file.png]] from being matched first
            contentToRender = contentToRender.replace(
                /!\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
                (match, mediaName, altText) => {
                    const filename = mediaName.trim();
                    const alt = altText ? altText.trim() : filename.replace(/\.[^/.]+$/, '');
                    
                    // Resolve media path using O(1) lookup
                    const mediaPath = self.resolveMediaWikilink(filename);
                    
                    if (mediaPath) {
                        // URL-encode path segments for the API
                        const encodedPath = mediaPath.split('/').map(segment => {
                            try {
                                return encodeURIComponent(decodeURIComponent(segment));
                            } catch (e) {
                                return encodeURIComponent(segment);
                            }
                        }).join('/');
                        
                        const safeAlt = alt.replace(/"/g, '&quot;');
                        const mediaSrc = `/api/media/${encodedPath}`;
                        const mediaType = self.getMediaType(filename);
                        
                        // Return appropriate HTML based on media type
                        switch (mediaType) {
                            case 'audio':
                                return `<div class="media-embed media-audio"><audio controls preload="none" src="${mediaSrc}" title="${safeAlt}"></audio><span class="media-caption">${safeAlt}</span></div>`;
                            case 'video':
                                return `<div class="media-embed media-video"><video controls preload="none" poster="" src="${mediaSrc}" title="${safeAlt}"></video></div>`;
                            case 'document':
                                // Local PDFs: show iframe preview
                                return `<div class="media-embed media-pdf"><iframe src="${mediaSrc}" title="${safeAlt}"></iframe></div>`;
                            default: // image
                                return `<img src="${mediaSrc}" alt="${safeAlt}" title="${safeAlt}">`;
                        }
                    }
                    
                    // Media not found - return broken indicator
                    const safeFilename = filename.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    const mediaType = self.getMediaType(filename);
                    const icon = mediaType === 'audio' ? '🎵' : mediaType === 'video' ? '🎬' : mediaType === 'document' ? '📄' : '🖼️';
                    return `<span class="wikilink-broken" title="Media not found">${icon} ${safeFilename}</span>`;
                }
            );
            
            // Step 2b: Convert note wikilinks: [[note]] or [[note|display text]]
            contentToRender = contentToRender.replace(
                /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
                (match, target, displayText) => {
                    const linkTarget = target.trim();
                    const linkText = displayText ? displayText.trim() : linkTarget;
                    
                    // Fast O(1) check using pre-built lookup maps
                    // Handle section anchors: extract base note path
                    const hashIndex = linkTarget.indexOf('#');
                    const basePath = hashIndex !== -1 ? linkTarget.substring(0, hashIndex) : linkTarget;
                    const noteExists = basePath === '' || self.wikiLinkExists(basePath);
                    
                    // Escape special chars: href needs quote escaping, text needs HTML escaping
                    const safeHref = linkTarget.replace(/"/g, '%22');
                    const safeText = linkText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    
                    // Return link with data attribute for styling broken links
                    const brokenClass = noteExists ? '' : ' class="wikilink-broken"';
                    return `<a href="${safeHref}"${brokenClass} data-wikilink="true">${safeText}</a>`;
                }
            );
            
            // Step 3: Restore code blocks
            contentToRender = contentToRender.replace(/\x00CODEBLOCK(\d+)\x00/g, (match, index) => {
                return codeBlocks[parseInt(index)];
            });
            
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
            
            // Parse markdown
            let html = marked.parse(contentToRender);
            
            // Post-process: Add target="_blank" to external links and title attributes to images
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
            
            // Find all images and transform paths for display
            // Also convert non-image media (audio, video, PDF) to appropriate elements
            const images = tempDiv.querySelectorAll('img');
            images.forEach(img => {
                let src = img.getAttribute('src');
                if (src) {
                    const isExternal = src.startsWith('http://') || src.startsWith('https://') || src.startsWith('//');
                    const isLocal = !isExternal && !src.startsWith('data:');
                    
                    // Transform relative paths to /api/media/ for serving
                    if (isLocal && !src.startsWith('/api/media/')) {
                        // URL-encode path segments to handle spaces and special characters
                        const encodedPath = src.split('/').map(segment => {
                            try {
                                return encodeURIComponent(decodeURIComponent(segment));
                            } catch (e) {
                                return encodeURIComponent(segment);
                            }
                        }).join('/');
                        src = `/api/media/${encodedPath}`;
                        img.setAttribute('src', src);
                    }
                    
                    // Check if this is non-image media and convert to appropriate element
                    const mediaType = self.getMediaType(src);
                    const altText = img.getAttribute('alt') || src.split('/').pop().replace(/\.[^/.]+$/, '');
                    const safeAlt = altText.replace(/"/g, '&quot;');
                    
                    // Only convert LOCAL media to embedded elements (security)
                    // External non-image media gets styled links instead
                    if (isLocal || src.startsWith('/api/media/')) {
                        if (mediaType === 'audio') {
                            const wrapper = document.createElement('div');
                            wrapper.className = 'media-embed media-audio';
                            wrapper.innerHTML = `<audio controls preload="none" src="${src}" title="${safeAlt}"></audio><span class="media-caption">${safeAlt}</span>`;
                            img.replaceWith(wrapper);
                            return;
                        } else if (mediaType === 'video') {
                            const wrapper = document.createElement('div');
                            wrapper.className = 'media-embed media-video';
                            wrapper.innerHTML = `<video controls preload="none" poster="" src="${src}" title="${safeAlt}"></video>`;
                            img.replaceWith(wrapper);
                            return;
                        } else if (mediaType === 'document') {
                            // Local PDFs: show iframe preview
                            const wrapper = document.createElement('div');
                            wrapper.className = 'media-embed media-pdf';
                            wrapper.innerHTML = `<iframe src="${src}" title="${safeAlt}"></iframe>`;
                            img.replaceWith(wrapper);
                            return;
                        }
                    } else if (isExternal && mediaType === 'document') {
                        // External PDFs: styled link (opens in new tab)
                        const link = document.createElement('a');
                        link.href = src;
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.className = 'pdf-link';
                        link.title = `Open ${safeAlt}`;
                        link.innerHTML = `<span class="pdf-link-content">📄 ${safeAlt}</span><span class="pdf-link-note">Opens in new tab</span>`;
                        img.replaceWith(link);
                        return;
                    }
                    // External audio/video: leave as broken image for security
                }
                
                // For regular images, set title attribute
                const altText = img.getAttribute('alt');
                if (altText) {
                    img.setAttribute('title', altText);
                }
            });
            
            html = tempDiv.innerHTML;
            
            // Debounced MathJax rendering (avoid re-running on every keystroke)
            if (this._mathDebounceTimeout) clearTimeout(this._mathDebounceTimeout);
            this._mathDebounceTimeout = setTimeout(() => this.typesetMath(), 300);
            
            // Debounced Mermaid rendering
            if (this._mermaidDebounceTimeout) clearTimeout(this._mermaidDebounceTimeout);
            this._mermaidDebounceTimeout = setTimeout(() => this.renderMermaid(), 300);
            
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
                    
                    // Enable video metadata loading (for first frame preview)
                    // Track by source URL to prevent duplicate requests on re-renders
                    if (!this._initializedVideoSources) this._initializedVideoSources = new Set();
                    previewEl.querySelectorAll('video[preload="none"]').forEach((video) => {
                        const src = video.getAttribute('src');
                        if (src && !this._initializedVideoSources.has(src)) {
                            this._initializedVideoSources.add(src);
                            video.preload = 'metadata';
                        }
                    });
                }
            }, 0);
            
            // Cache the result for performance
            this._lastRenderedContent = this.noteContent;
            this._cachedRenderedHTML = html;
            
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
            // Extract language from code element class (e.g., "language-toml" -> "TOML")
            const codeElement = preElement.querySelector('code');
            let language = '';
            if (codeElement && codeElement.className) {
                const match = codeElement.className.match(/language-(\w+)/);
                if (match) {
                    const langMap = {
                        'js': 'JavaScript', 'ts': 'TypeScript', 'py': 'Python',
                        'rb': 'Ruby', 'cs': 'C#', 'cpp': 'C++', 'sh': 'Shell',
                        'bash': 'Bash', 'zsh': 'Zsh', 'yml': 'YAML', 'md': 'Markdown'
                    };
                    const rawLang = match[1].toLowerCase();
                    language = langMap[rawLang] || match[1].toUpperCase();
                }
            }
            
            // Create copy button with language label
            const button = document.createElement('button');
            button.className = 'copy-code-button';
            const displayText = language || this.t('common.copy_to_clipboard').split(' ')[0]; // Use first word as fallback
            button.innerHTML = `<span>${displayText}</span>`;
            button.dataset.originalText = displayText; // Store for restore after copy
            button.title = this.t('common.copy_to_clipboard');
            
            // Style the button
            button.style.position = 'absolute';
            button.style.top = '8px';
            button.style.right = '8px';
            button.style.padding = '4px 10px';
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
            button.style.fontSize = '11px';
            button.style.fontWeight = '600';
            button.style.fontFamily = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace';
            button.style.textTransform = 'uppercase';
            button.style.letterSpacing = '0.5px';
            
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
                
                const originalText = button.dataset.originalText;
                const copiedText = this.t('common.copied');
                const copyTitle = this.t('common.copy_to_clipboard');
                
                try {
                    await navigator.clipboard.writeText(code);
                    
                    // Visual feedback - show localized "Copied!"
                    button.innerHTML = `<span>${copiedText}</span>`;
                    button.style.backgroundColor = 'rgba(34, 197, 94, 0.8)';
                    button.title = copiedText;
                    
                    // Reset after 2 seconds
                    setTimeout(() => {
                        button.innerHTML = `<span>${originalText}</span>`;
                        button.style.backgroundColor = 'rgba(0, 0, 0, 0.6)';
                        button.title = copyTitle;
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
                        button.innerHTML = `<span>${copiedText}</span>`;
                        button.style.backgroundColor = 'rgba(34, 197, 94, 0.8)';
                        setTimeout(() => {
                            button.innerHTML = `<span>${originalText}</span>`;
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
            
            // Sentences: punctuation [.!?]+ followed by space or end-of-string
            const sentences = (content.match(/[.!?]+(?:\s|$)/g) || []).length;
            
            // List items: lines starting with -, *, + or a number (e.g. 1., 10.), excluding tasks [-]
            const listItems = (content.match(/^\s*(?:[-*+]|\d+\.)\s+(?!\[)/gm) || []).length;
            
            // Tables: markdown table separator rows (| --- | --- |)
            const tables = (content.match(/^\s*\|(?:\s*:?-+:?\s*\|){1,}\s*$/gm) || []).length;
            
            // Link count (standard markdown links)
            const markdownLinkMatches = content.match(/\[([^\]]+)\]\(([^\)]+)\)/g) || [];
            const markdownLinks = markdownLinkMatches.length;
            const markdownInternalLinks = markdownLinkMatches.filter(l => l.includes('.md')).length;
            
            // Wikilink count ([[note]] or [[note|display text]] format)
            const wikilinks = (content.match(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g) || []).length;
            
            // Total links (markdown + wikilinks)
            const links = markdownLinks + wikilinks;
            const internalLinks = markdownInternalLinks + wikilinks; // All wikilinks are internal
            
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
                sentences,
                characters: chars,
                total_characters: totalChars,
                reading_time_minutes: readingTime,
                lines,
                paragraphs,
                list_items: listItems,
                tables,
                links,
                internal_links: internalLinks,
                external_links: links - internalLinks,
                wikilinks,
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
        
        // Parse YAML frontmatter metadata from note content
        parseMetadata() {
            if (!this.noteContent) {
                this.noteMetadata = null;
                this._lastFrontmatter = null;
                return;
            }
            
            const content = this.noteContent;
            
            // Check if content starts with frontmatter
            if (!content.trim().startsWith('---')) {
                this.noteMetadata = null;
                this._lastFrontmatter = null;
                return;
            }
            
            try {
                const lines = content.split('\n');
                if (lines[0].trim() !== '---') {
                    this.noteMetadata = null;
                    this._lastFrontmatter = null;
                    return;
                }
                
                // Find closing ---
                let endIdx = -1;
                for (let i = 1; i < lines.length; i++) {
                    if (lines[i].trim() === '---') {
                        endIdx = i;
                        break;
                    }
                }
                
                if (endIdx === -1) {
                    this.noteMetadata = null;
                    this._lastFrontmatter = null;
                    return;
                }
                
                // Performance optimization: skip parsing if frontmatter unchanged
                const frontmatterRaw = lines.slice(0, endIdx + 1).join('\n');
                if (frontmatterRaw === this._lastFrontmatter) {
                    return; // No change, keep existing metadata
                }
                this._lastFrontmatter = frontmatterRaw;
                
                const frontmatterLines = lines.slice(1, endIdx);
                const metadata = {};
                let currentKey = null;
                let currentValue = [];
                
                for (const line of frontmatterLines) {
                    // Check for new key: value pair (supports keys with hyphens/underscores)
                    const keyMatch = line.match(/^([a-zA-Z_][\w-]*):\s*(.*)$/);
                    
                    if (keyMatch) {
                        // Save previous key if exists
                        if (currentKey) {
                            metadata[currentKey] = this.parseYamlValue(currentValue.join('\n'));
                        }
                        
                        currentKey = keyMatch[1];
                        const value = keyMatch[2].trim();
                        currentValue = [value];
                    } else if (line.match(/^\s+-\s+/) && currentKey) {
                        // List item continuation (e.g., "  - item")
                        currentValue.push(line);
                    } else if (line.startsWith('  ') && currentKey) {
                        // Indented content (multiline value)
                        currentValue.push(line);
                    }
                }
                
                // Save last key
                if (currentKey) {
                    metadata[currentKey] = this.parseYamlValue(currentValue.join('\n'));
                }
                
                this.noteMetadata = Object.keys(metadata).length > 0 ? metadata : null;
                
            } catch (error) {
                console.error('Failed to parse frontmatter:', error);
                this.noteMetadata = null;
                this._lastFrontmatter = null;
            }
        },
        
        // Parse a YAML value (handles arrays, strings, numbers, booleans)
        parseYamlValue(value) {
            if (!value || value.trim() === '') return null;
            
            value = value.trim();
            
            // Check for inline array: [item1, item2]
            if (value.startsWith('[') && value.endsWith(']')) {
                const inner = value.slice(1, -1);
                return inner.split(',').map(s => s.trim().replace(/^["']|["']$/g, '')).filter(s => s);
            }
            
            // Check for YAML list format (multiple lines starting with -)
            if (value.includes('\n  -') || value.startsWith('  -')) {
                const items = [];
                const lines = value.split('\n');
                for (const line of lines) {
                    const match = line.match(/^\s*-\s*(.+)$/);
                    if (match) {
                        items.push(match[1].trim().replace(/^["']|["']$/g, ''));
                    }
                }
                return items.length > 0 ? items : value;
            }
            
            // Check for boolean
            if (value.toLowerCase() === 'true') return true;
            if (value.toLowerCase() === 'false') return false;
            
            // Check for number
            if (/^-?\d+(\.\d+)?$/.test(value)) {
                return parseFloat(value);
            }
            
            // Return as string (remove quotes if present)
            return value.replace(/^["']|["']$/g, '');
        },
        
        // Check if a string is a URL
        isUrl(str) {
            if (typeof str !== 'string') return false;
            return /^https?:\/\/\S+$/i.test(str.trim());
        },
        
        // Escape HTML to prevent XSS
        escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        },
        
        // Format metadata value for display
        formatMetadataValue(key, value) {
            if (value === null || value === undefined) return '';
            
            // Arrays are handled separately in the template
            if (Array.isArray(value)) return value;
            
            // Format dates nicely
            if (key === 'date' || key === 'created' || key === 'modified' || key === 'updated') {
                let date;
                // Parse date-only strings (YYYY-MM-DD) as local dates to avoid timezone issues
                if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
                    const [year, month, day] = value.split('-').map(Number);
                    date = new Date(year, month - 1, day);  // month is 0-indexed
                } else {
                    date = new Date(value);
                }
                if (!isNaN(date.getTime())) {
                    return date.toLocaleDateString(this.currentLocale, { 
                        year: 'numeric', 
                        month: 'short', 
                        day: 'numeric' 
                    });
                }
            }
            
            // Booleans
            if (typeof value === 'boolean') {
                return value ? this.t('common.yes') : this.t('common.no');
            }
            
            return String(value);
        },
        
        // Format metadata value as HTML (for URL support)
        formatMetadataValueHtml(key, value) {
            const formatted = this.formatMetadataValue(key, value);
            
            // Check if it's a URL
            if (this.isUrl(formatted)) {
                const escaped = this.escapeHtml(formatted);
                // Truncate long URLs for display
                const displayUrl = formatted.length > 40 
                    ? formatted.substring(0, 37) + '...' 
                    : formatted;
                return `<a href="${escaped}" target="_blank" rel="noopener noreferrer" class="metadata-link">${this.escapeHtml(displayUrl)}</a>`;
            }
            
            return this.escapeHtml(formatted);
        },
        
        // Get priority metadata fields (shown in collapsed view)
        getPriorityMetadataFields() {
            if (!this.noteMetadata) return [];
            
            // Fields to show in collapsed view, in order of priority
            const priority = ['date', 'created', 'author', 'status', 'priority', 'type', 'category'];
            const fields = [];
            
            for (const key of priority) {
                if (this.noteMetadata[key] !== undefined && !Array.isArray(this.noteMetadata[key])) {
                    const formatted = this.formatMetadataValue(key, this.noteMetadata[key]);
                    const isUrl = this.isUrl(formatted);
                    fields.push({ 
                        key, 
                        value: formatted,
                        valueHtml: isUrl ? this.formatMetadataValueHtml(key, this.noteMetadata[key]) : this.escapeHtml(formatted),
                        isUrl
                    });
                }
            }
            
            return fields.slice(0, 3); // Show max 3 fields in collapsed view
        },
        
        // Get all metadata fields except tags (for expanded view)
        getAllMetadataFields() {
            if (!this.noteMetadata) return [];
            
            return Object.entries(this.noteMetadata)
                .filter(([key]) => key !== 'tags') // Tags shown separately
                .map(([key, value]) => {
                    const isArray = Array.isArray(value);
                    const formatted = this.formatMetadataValue(key, value);
                    const isUrl = !isArray && this.isUrl(formatted);
                    return {
                        key,
                        value: formatted,
                        valueHtml: isUrl ? this.formatMetadataValueHtml(key, value) : this.escapeHtml(formatted),
                        isArray,
                        isUrl
                    };
                });
        },
        
        // Check if note has any displayable metadata
        getHasMetadata() {
            const has = this.noteMetadata && Object.keys(this.noteMetadata).length > 0;
            return has;
        },
        
        // Get tags from metadata
        getMetadataTags() {
            if (!this.noteMetadata || !this.noteMetadata.tags) return [];
            return Array.isArray(this.noteMetadata.tags) ? this.noteMetadata.tags : [this.noteMetadata.tags];
        },
        
        // Save sidebar width to localStorage
        saveSidebarWidth() {
            localStorage.setItem('sidebarWidth', this.sidebarWidth.toString());
        },
        
        // Save view mode to localStorage
        saveViewMode() {
            try {
                localStorage.setItem('viewMode', this.viewMode);
            } catch (error) {
                console.error('Error saving view mode:', error);
            }
        },
        
        saveTagsExpanded() {
            try {
                localStorage.setItem('tagsExpanded', this.tagsExpanded.toString());
            } catch (error) {
                console.error('Error saving tags expanded state:', error);
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
                alert(this.t('notes.no_content'));
                return;
            }
            
            try {
                // Get the note name without extension
                const noteName = this.currentNoteName || 'note';
                
                // Get current rendered HTML (this already has markdown converted and will have LaTeX delimiters)
                let renderedHTML = this.renderedMarkdown;
                
                // Convert non-image media (audio, video, PDF) to placeholders first
                // These shouldn't be embedded as base64 (too large)
                // Use CSS variables with fallbacks for theme-aware styling (matches backend export.py)
                const mediaPlaceholder = (type, name) => {
                    const icons = { audio: '🎵', video: '🎬', document: '📄' };
                    const labels = { audio: 'Audio file', video: 'Video file', document: 'PDF document' };
                    const icon = icons[type] || '📎';
                    const label = labels[type] || 'Media file';
                    return `<div style="margin:1.5rem 0;padding:1.5rem;background:linear-gradient(135deg,var(--bg-tertiary,#f8f9fa) 0%,var(--bg-secondary,#e9ecef) 100%);border:1px solid var(--border-primary,#dee2e6);border-radius:0.5rem;display:flex;align-items:center;gap:1rem;">
<span style="font-size:2rem;">${icon}</span>
<div>
<div style="font-weight:600;color:var(--text-primary,#212529);">${name}</div>
<div style="font-size:0.875rem;color:var(--text-secondary,#6c757d);">${label} — not available in exported view</div>
</div>
</div>`;
                };
                
                // Replace audio embeds with placeholders
                renderedHTML = renderedHTML.replace(
                    /<div class="media-embed media-audio">.*?<audio[^>]*src="[^"]*\/([^"\/]+)"[^>]*>.*?<\/div>/gs,
                    (match, filename) => mediaPlaceholder('audio', decodeURIComponent(filename).replace(/\.[^.]+$/, ''))
                );
                
                // Replace video embeds with placeholders
                renderedHTML = renderedHTML.replace(
                    /<div class="media-embed media-video">.*?<video[^>]*src="[^"]*\/([^"\/]+)"[^>]*>.*?<\/div>/gs,
                    (match, filename) => mediaPlaceholder('video', decodeURIComponent(filename).replace(/\.[^.]+$/, ''))
                );
                
                // Replace PDF embeds with placeholders
                renderedHTML = renderedHTML.replace(
                    /<div class="media-embed media-pdf">.*?<iframe[^>]*src="[^"]*\/([^"\/]+)"[^>]*>.*?<\/div>/gs,
                    (match, filename) => mediaPlaceholder('document', decodeURIComponent(filename).replace(/\.[^.]+$/, ''))
                );
                
                // Embed local images as base64 for fully self-contained HTML
                // Handle both /api/media/ and legacy /api/images/ paths
                const imgRegex = /src="\/api\/(?:media|images)\/([^"]+)"/g;
                const imgMatches = [...renderedHTML.matchAll(imgRegex)];
                
                for (const match of imgMatches) {
                    const encodedPath = match[1];
                    // Skip non-image files (already handled above)
                    const ext = encodedPath.split('.').pop().toLowerCase();
                    if (!['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) {
                        continue;
                    }
                    
                    try {
                        // Fetch the image
                        const imgResponse = await fetch(`/api/media/${encodedPath}`);
                        if (imgResponse.ok) {
                            const blob = await imgResponse.blob();
                            // Convert to base64 data URL
                            const base64 = await new Promise((resolve) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result);
                                reader.readAsDataURL(blob);
                            });
                            // Replace the src with base64 data URL
                            renderedHTML = renderedHTML.replace(match[0], `src="${base64}"`);
                        }
                    } catch (e) {
                        console.warn(`Failed to embed image: ${encodedPath}`, e);
                        // Fall back to relative path
                        const decodedPath = decodeURIComponent(encodedPath);
                        renderedHTML = renderedHTML.replace(match[0], `src="${decodedPath}"`);
                    }
                }
                
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
    
    <!-- Highlight.js for code syntax highlighting (v11.9.0) -->
    ${highlightTheme ? `<link rel="stylesheet" href="${highlightTheme}">` : '<!-- No highlight.js theme detected -->'}
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    
    <!-- MathJax for LaTeX math rendering (v3.2.2) -->
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
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js"></script>
    
    <!-- Mermaid.js for diagrams -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11.12.2/dist/mermaid.esm.min.mjs';
        const isDark = ${this.getThemeType() === 'dark'};
        mermaid.initialize({ 
            startOnLoad: false,
            theme: isDark ? 'dark' : 'default',
            securityLevel: 'strict',
            fontFamily: 'inherit',
            flowchart: { useMaxWidth: true },
            sequence: { useMaxWidth: true },
            gantt: { useMaxWidth: true },
            state: { useMaxWidth: true },
            er: { useMaxWidth: true },
            pie: { useMaxWidth: true },
            mindmap: { useMaxWidth: true },
            gitGraph: { useMaxWidth: true }
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
                alert(this.t('export.failed', { error: error.message }));
            }
        },
        
        // Copy current note link to clipboard
        async copyNoteLink() {
            if (!this.currentNote) return;
            
            // Build the full URL
            const pathWithoutExtension = this.currentNote.replace('.md', '');
            const encodedPath = pathWithoutExtension.split('/').map(segment => encodeURIComponent(segment)).join('/');
            const url = `${window.location.origin}/${encodedPath}`;
            
            try {
                await navigator.clipboard.writeText(url);
            } catch (error) {
                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = url;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
            }
            
            // Show brief "Copied!" feedback
            this.linkCopied = true;
            setTimeout(() => {
                this.linkCopied = false;
            }, 1500);
        },
        
        // ============================================================================
        // Share Functions
        // ============================================================================
        
        // Load list of shared note paths (for visual indicators)
        async loadSharedNotePaths() {
            try {
                const response = await fetch('/api/shared-notes');
                if (response.ok) {
                    const data = await response.json();
                    this._sharedNotePaths = new Set(data.paths || []);
                }
            } catch (error) {
                console.error('Failed to load shared note paths:', error);
                this._sharedNotePaths = new Set();
            }
        },
        
        // Check if a note is currently shared (O(1) lookup)
        isNoteShared(notePath) {
            return this._sharedNotePaths.has(notePath);
        },
        
        // ============================================
        // Quick Switcher (Ctrl+Alt+P)
        // ============================================
        
        openQuickSwitcher() {
            this.showQuickSwitcher = true;
            this.quickSwitcherQuery = '';
            this.quickSwitcherIndex = 0;
            // Populate initial results
            this.quickSwitcherResults = (this.allNotes || []).slice(0, 10);
            // Focus the input after the modal renders
            this.$nextTick(() => {
                const input = document.getElementById('quickSwitcherInput');
                if (input) input.focus();
            });
        },
        
        closeQuickSwitcher() {
            this.showQuickSwitcher = false;
            this.quickSwitcherQuery = '';
            this.quickSwitcherIndex = 0;
        },
        
        // Filter notes for quick switcher based on query
        filterQuickSwitcher(query) {
            // Only include actual notes, not images
            const notes = (this.notes || []).filter(n => n.type === 'note');
            if (!query || !query.trim()) {
                // Show recent notes when no query
                return notes.slice(0, 10);
            }
            const q = query.toLowerCase();
            return notes
                .filter(n => 
                    n.name.toLowerCase().includes(q) || 
                    n.path.toLowerCase().includes(q)
                )
                .slice(0, 10);
        },
        
        // Handle keyboard navigation in quick switcher
        handleQuickSwitcherKeydown(e) {
            const results = this.quickSwitcherResults;
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.quickSwitcherIndex = Math.min(this.quickSwitcherIndex + 1, results.length - 1);
                this.scrollQuickSwitcherIntoView();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.quickSwitcherIndex = Math.max(this.quickSwitcherIndex - 1, 0);
                this.scrollQuickSwitcherIntoView();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                const note = results[this.quickSwitcherIndex];
                if (note) {
                    this.loadNote(note.path);
                    this.closeQuickSwitcher();
                }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                this.closeQuickSwitcher();
            }
        },
        
        // Scroll selected item into view in quick switcher
        scrollQuickSwitcherIntoView() {
            this.$nextTick(() => {
                const items = document.querySelectorAll('[data-quick-switcher-item]');
                if (items[this.quickSwitcherIndex]) {
                    items[this.quickSwitcherIndex].scrollIntoView({ block: 'nearest' });
                }
            });
        },
        
        // Select note from quick switcher by click
        selectQuickSwitcherNote(note) {
            this.loadNote(note.path);
            this.closeQuickSwitcher();
        },
        
        // Close share modal and reset state after animation
        closeShareModal() {
            this.showShareModal = false;
            // Delay state reset until modal is fully hidden
            setTimeout(() => {
                this.showShareQR = false;
                this.shareInfo = null;
                this.shareLoading = false;
            }, 200);
        },
        
        // Generate QR code for share URL
        generateQRCode(url) {
            if (!url || typeof qrcode === 'undefined') return '';
            try {
                const qr = qrcode(0, 'M'); // 0 = auto version, M = medium error correction
                qr.addData(url);
                qr.make();
                return qr.createDataURL(4); // 4 = module size in pixels
            } catch (e) {
                console.error('QR code generation failed:', e);
                return '';
            }
        },
        
        // Open share modal and fetch current share status
        async openShareModal() {
            if (!this.currentNote) return;
            
            // Reset state BEFORE showing modal to prevent flicker
            this.showShareQR = false;
            this.shareInfo = null;
            this.shareLoading = true;
            this.showShareModal = true;
            
            try {
                const notePath = this.currentNote.replace('.md', '');
                const encodedPath = notePath.split('/').map(segment => encodeURIComponent(segment)).join('/');
                const response = await fetch(`/api/share/${encodedPath}`);
                
                if (response.ok) {
                    this.shareInfo = await response.json();
                } else {
                    this.shareInfo = { shared: false };
                }
            } catch (error) {
                console.error('Failed to get share status:', error);
                this.shareInfo = { shared: false };
            } finally {
                this.shareLoading = false;
            }
        },
        
        // Create a share link for the current note (with current theme)
        async createShareLink() {
            if (!this.currentNote) return;
            
            this.shareLoading = true;
            
            try {
                const notePath = this.currentNote.replace('.md', '');
                const encodedPath = notePath.split('/').map(segment => encodeURIComponent(segment)).join('/');
                const response = await fetch(`/api/share/${encodedPath}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ theme: this.currentTheme || 'light' })
                });
                
                if (response.ok) {
                    this.shareInfo = await response.json();
                    this.shareInfo.shared = true;
                    // Update the shared paths set
                    this._sharedNotePaths.add(this.currentNote);
                } else {
                    const error = await response.json();
                    alert(this.t('share.error_creating', { error: error.detail || 'Unknown error' }));
                }
            } catch (error) {
                console.error('Failed to create share link:', error);
                alert(this.t('share.error_creating', { error: error.message }));
            } finally {
                this.shareLoading = false;
            }
        },
        
        // Copy share link to clipboard
        async copyShareLink() {
            if (!this.shareInfo?.url) return;
            
            try {
                await navigator.clipboard.writeText(this.shareInfo.url);
            } catch (error) {
                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = this.shareInfo.url;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
            }
            
            this.shareLinkCopied = true;
            setTimeout(() => {
                this.shareLinkCopied = false;
            }, 2000);
        },
        
        // Revoke share link
        async revokeShareLink() {
            if (!this.currentNote) return;
            
            if (!confirm(this.t('share.confirm_revoke'))) return;
            
            this.shareLoading = true;
            
            try {
                const notePath = this.currentNote.replace('.md', '');
                const encodedPath = notePath.split('/').map(segment => encodeURIComponent(segment)).join('/');
                const response = await fetch(`/api/share/${encodedPath}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    this.shareInfo = { shared: false };
                    // Update the shared paths set
                    this._sharedNotePaths.delete(this.currentNote);
                } else {
                    const error = await response.json();
                    alert(this.t('share.error_revoking', { error: error.detail || 'Unknown error' }));
                }
            } catch (error) {
                console.error('Failed to revoke share link:', error);
                alert(this.t('share.error_revoking', { error: error.message }));
            } finally {
                this.shareLoading = false;
            }
        },
        
        // Toggle Zen Mode (full immersive writing experience)
        async toggleZenMode() {
            if (!this.zenMode) {
                // Entering Zen Mode
                this.previousViewMode = this.viewMode;
                this.viewMode = 'edit';
                this.mobileSidebarOpen = false;
                this.zenMode = true;
                
                // Request fullscreen
                try {
                    const elem = document.documentElement;
                    if (elem.requestFullscreen) {
                        await elem.requestFullscreen();
                    } else if (elem.webkitRequestFullscreen) {
                        await elem.webkitRequestFullscreen();
                    } else if (elem.msRequestFullscreen) {
                        await elem.msRequestFullscreen();
                    }
                } catch (e) {
                    // Fullscreen not supported or denied, continue anyway
                    console.log('Fullscreen not available:', e);
                }
                
                // Focus editor after transition
                setTimeout(() => {
                    const editor = document.getElementById('note-editor');
                    if (editor) editor.focus();
                }, 300);
            } else {
                // Exiting Zen Mode
                this.zenMode = false;
                this.viewMode = this.previousViewMode;
                
                // Exit fullscreen
                try {
                    if (document.exitFullscreen) {
                        await document.exitFullscreen();
                    } else if (document.webkitExitFullscreen) {
                        await document.webkitExitFullscreen();
                    } else if (document.msExitFullscreen) {
                        await document.msExitFullscreen();
                    }
                } catch (e) {
                    console.log('Exit fullscreen error:', e);
                }
            }
        },
        
        // Homepage folder navigation methods
        goToHomepageFolder(folderPath) {
            this.showGraph = false; // Close graph when navigating
            this.selectedHomepageFolder = folderPath || '';
            
            // Clear editor state to show landing page
            this.currentNote = '';
            this.currentNoteName = '';
            this.noteContent = '';
            this.currentMedia = '';
            this.outline = [];
            document.title = this.appName;
            
            // Invalidate cache to force recalculation
            this._homepageCache = {
                folderPath: null,
                notes: null,
                folders: null,
                breadcrumb: null
            };
            
            window.history.pushState({ homepageFolder: folderPath || '' }, '', '/');
        },
        
        // Navigate to homepage root and clear all editor state
        goHome() {
            this.showGraph = false; // Close graph when going home
            this.selectedHomepageFolder = '';
            this.currentNote = '';
            this.currentNoteName = '';
            this.noteContent = '';
            this.currentMedia = '';
            this.outline = [];
            this.mobileSidebarOpen = false;
            document.title = this.appName;
            
            // Clear undo/redo history
            this.undoHistory = [];
            this.redoHistory = [];
            this.hasPendingHistoryChanges = false;
            
            // Invalidate cache to force recalculation
            this._homepageCache = {
                folderPath: null,
                notes: null,
                folders: null,
                breadcrumb: null
            };
            
            window.history.pushState({ homepageFolder: '' }, '', '/');
        },
        
        // Mobile files/home tab - context-aware behavior
        mobileFilesTabClick() {
            if (this.currentNote || this.currentMedia || this.showGraph) {
                // Viewing content → go home
                this.goHome();
            } else {
                // On homepage → toggle files sidebar
                this.activePanel = 'files';
                this.mobileSidebarOpen = !this.mobileSidebarOpen;
            }
        },
        
        // ==================== GRAPH VIEW ====================
        
        // Initialize the graph visualization
        async initGraph() {
            // Check if vis is loaded
            if (typeof vis === 'undefined') {
                console.error('vis-network library not loaded');
                return;
            }
            
            this.graphLoaded = false;
            
            try {
                // Fetch graph data from API
                const response = await fetch('/api/graph');
                if (!response.ok) throw new Error('Failed to fetch graph data');
                const data = await response.json();
                this.graphData = data;
                
                // Get container
                const container = document.getElementById('graph-overlay');
                if (!container) return;
                
                // Get theme colors (force reflow to ensure CSS is applied)
                document.body.offsetHeight; // Force reflow
                const style = getComputedStyle(document.documentElement);
                
                // Helper to get CSS variable with fallback
                const getCssVar = (name, fallback) => {
                    const value = style.getPropertyValue(name).trim();
                    return value || fallback;
                };
                
                const accentPrimary = getCssVar('--accent-primary', '#7c3aed');
                const accentSecondary = getCssVar('--accent-secondary', '#a78bfa');
                const textPrimary = getCssVar('--text-primary', '#111827');
                const textSecondary = getCssVar('--text-secondary', '#6b7280');
                const bgPrimary = getCssVar('--bg-primary', '#ffffff');
                const bgSecondary = getCssVar('--bg-secondary', '#f3f4f6');
                const borderColor = getCssVar('--border-primary', '#e5e7eb');
                
                // Prepare nodes with styling - all nodes same base color
                const nodes = new vis.DataSet(data.nodes.map(n => ({
                    id: n.id,
                    label: n.label,
                    title: n.id, // Tooltip shows full path
                    color: {
                        background: accentPrimary,
                        border: accentPrimary,
                        highlight: {
                            background: accentPrimary,
                            border: textPrimary  // Darker border when selected
                        },
                        hover: {
                            background: accentSecondary,
                            border: accentPrimary
                        }
                    },
                    font: {
                        color: textPrimary,
                        size: 12,
                        face: 'system-ui, -apple-system, sans-serif'
                    },
                    borderWidth: this.currentNote === n.id ? 4 : 2,
                    chosen: {
                        node: (values) => {
                            values.size = 22;
                            values.borderWidth = 4;
                            values.borderColor = textPrimary;
                        }
                    }
                })));
                
                // Prepare edges with styling based on type
                const edges = new vis.DataSet(data.edges.map((e, i) => ({
                    id: i,
                    from: e.source,
                    to: e.target,
                    color: {
                        color: e.type === 'wikilink' ? accentPrimary : borderColor,
                        highlight: accentPrimary,
                        hover: accentSecondary,
                        opacity: 0.8
                    },
                    width: e.type === 'wikilink' ? 2 : 1,
                    smooth: {
                        type: 'continuous',
                        roundness: 0.5
                    },
                    chosen: {
                        edge: (values) => {
                            values.width = 3;
                            values.color = accentPrimary;
                        }
                    }
                })));
                
                // Network options
                const options = {
                    nodes: {
                        shape: 'dot',
                        size: 16,
                        borderWidth: 2,
                        shadow: {
                            enabled: true,
                            color: 'rgba(0,0,0,0.1)',
                            size: 5,
                            x: 2,
                            y: 2
                        }
                    },
                    edges: {
                        arrows: {
                            to: {
                                enabled: true,
                                scaleFactor: 0.5,
                                type: 'arrow'
                            }
                        }
                    },
                    physics: {
                        enabled: true,
                        solver: 'forceAtlas2Based',
                        forceAtlas2Based: {
                            gravitationalConstant: -50,
                            centralGravity: 0.01,
                            springLength: 100,
                            springConstant: 0.08,
                            damping: 0.4,
                            avoidOverlap: 0.5
                        },
                        stabilization: {
                            enabled: true,
                            iterations: 200,
                            updateInterval: 25
                        }
                    },
                    interaction: {
                        hover: true,
                        tooltipDelay: 200,
                        navigationButtons: false,  // Using custom buttons instead
                        keyboard: {
                            enabled: true,
                            bindToWindow: false
                        },
                        zoomView: true,
                        dragView: true
                    },
                    layout: {
                        improvedLayout: true,
                        randomSeed: 42
                    }
                };
                
                // Destroy existing instance if any
                if (this.graphInstance) {
                    this.graphInstance.destroy();
                    this.graphInstance = null;
                }
                
                // Clear container to ensure clean state
                const graphCanvas = container.querySelector('canvas');
                if (graphCanvas) graphCanvas.remove();
                const visElements = container.querySelectorAll('.vis-network, .vis-navigation');
                visElements.forEach(el => el.remove());
                
                // Create the network
                this.graphInstance = new vis.Network(container, { nodes, edges }, options);
                
                // Store reference for callbacks
                const graphRef = this.graphInstance;
                const currentNoteRef = this.currentNote;
                
                // Wait for stabilization
                this.graphInstance.once('stabilizationIterationsDone', () => {
                    graphRef.setOptions({ physics: { enabled: false } });
                    this.graphLoaded = true;
                    
                    // Focus and select current note if one is loaded
                    if (currentNoteRef) {
                        setTimeout(() => {
                            try {
                                if (graphRef && this.showGraph) {
                                    const nodeIds = graphRef.body.data.nodes.getIds();
                                    if (nodeIds.includes(currentNoteRef)) {
                                        // Focus on the node
                                        graphRef.focus(currentNoteRef, {
                                            scale: 1.2,
                                            animation: {
                                                duration: 500,
                                                easingFunction: 'easeInOutQuad'
                                            }
                                        });
                                        // Select the node to highlight it
                                        graphRef.selectNodes([currentNoteRef]);
                                    }
                                }
                            } catch (e) {
                                // Ignore - graph may have been destroyed
                            }
                        }, 150);
                    }
                });
                
                // Click event - open note
                this.graphInstance.on('click', (params) => {
                    if (params.nodes.length > 0) {
                        const noteId = params.nodes[0];
                        this.loadNote(noteId);
                        // Node is already selected by vis-network on click, no need to call selectNodes
                    }
                });
                
                // Double-click event - open note and close graph
                this.graphInstance.on('doubleClick', (params) => {
                    if (params.nodes.length > 0) {
                        const noteId = params.nodes[0];
                        // Close graph and load note
                        this.showGraph = false;
                        this.loadNote(noteId);
                    }
                });
                
                // Hover event - highlight connections
                this.graphInstance.on('hoverNode', (params) => {
                    const nodeId = params.node;
                    const connectedNodes = this.graphInstance.getConnectedNodes(nodeId);
                    const connectedEdges = this.graphInstance.getConnectedEdges(nodeId);
                    
                    // Dim all nodes except hovered and connected
                    const allNodes = nodes.getIds();
                    const updates = allNodes.map(id => ({
                        id,
                        opacity: (id === nodeId || connectedNodes.includes(id)) ? 1 : 0.2
                    }));
                    nodes.update(updates);
                });
                
                this.graphInstance.on('blurNode', () => {
                    // Reset all nodes to full opacity
                    const allNodes = nodes.getIds();
                    const updates = allNodes.map(id => ({ id, opacity: 1 }));
                    nodes.update(updates);
                });
                
                // Add legend to container
                this.addGraphLegend(container, accentPrimary, borderColor, textSecondary);
                
            } catch (error) {
                console.error('Failed to initialize graph:', error);
                this.graphLoaded = true; // Stop loading indicator
            }
        },
        
        // Add legend to graph container
        addGraphLegend(container, wikiColor, mdColor, textColor) {
            // Remove existing legend if any
            const existingLegend = container.querySelector('.graph-legend');
            if (existingLegend) existingLegend.remove();
            
            const legend = document.createElement('div');
            legend.className = 'graph-legend';
            legend.innerHTML = `
                <div class="graph-legend-item">
                    <span class="graph-legend-dot" style="background: ${wikiColor};"></span>
                    <span style="color: ${textColor};">Wikilinks</span>
                </div>
                <div class="graph-legend-item">
                    <span class="graph-legend-dot" style="background: ${mdColor};"></span>
                    <span style="color: ${textColor};">${this.t('graph.markdown_links')}</span>
                </div>
                <div style="margin-top: 8px; font-size: 10px; color: ${textColor}; opacity: 0.7;">
                    ${this.t('graph.click_hint')}
                </div>
            `;
            container.appendChild(legend);
        },
        
        // Refresh graph when theme changes
        refreshGraph() {
            if (this.viewMode === 'graph' && this.graphInstance) {
                this.initGraph();
            }
        }
    }
}

