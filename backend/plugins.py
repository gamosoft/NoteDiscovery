"""
Simple plugin system for NoteDiscovery
Plugins can hook into events like note save, delete, etc.
"""

import os
import json
import importlib.util
from pathlib import Path
from typing import List, Dict, Callable


class Plugin:
    """Base plugin class"""
    
    def __init__(self):
        self.name = "Base Plugin"
        self.version = "1.0.0"
        self.enabled = False
    
    def on_note_save(self, note_path: str, content: str) -> str | None:
        """
        Called when a note is being saved.
        Can optionally transform content before writing to disk (e.g., encrypt).
        
        Args:
            note_path: Path to the note being saved
            content: Content to be saved
            
        Returns:
            Transformed content, or None to keep original
        """
        return None
    
    def on_note_delete(self, note_path: str):
        """Called when a note is deleted"""
        pass
    
    def on_search(self, query: str, results: List[Dict]):
        """Called after a search is performed"""
        pass
    
    def on_note_create(self, note_path: str, initial_content: str) -> str:
        """
        Called when a new note is created (before first save).
        Can modify and return the initial content.
        
        Args:
            note_path: Path to the new note
            initial_content: The initial content for the note
            
        Returns:
            Modified content (or return initial_content unchanged)
        """
        return initial_content
    
    def on_note_load(self, note_path: str, content: str) -> str | None:
        """
        Called when a note is loaded from disk.
        Can optionally transform content before displaying (e.g., decrypt).
        
        Args:
            note_path: Path to the loaded note
            content: Content loaded from disk
            
        Returns:
            Transformed content, or None to keep original
        """
        return None
    
    def on_app_startup(self):
        """
        Called when the application starts up.
        Useful for initialization, sync, health checks, etc.
        """
        pass

    def on_app_shutdown(self):
        """
        Called when the application is shutting down.
        Plugins can use this to stop background threads, close external connections,
        flush cached state to disk, or perform any other cleanup required before
        the process exits.
        """
        pass


class PluginManager:
    """Manages loading and execution of plugins"""
    
    def __init__(self, plugins_dir: str):
        self.plugins_dir = Path(plugins_dir)
        self.plugins: Dict[str, Plugin] = {}
        self.config_file = self.plugins_dir / "plugin_config.json"
        self.load_plugins()
        self._apply_saved_state()
        # Save config to create/update the file with current states
        if self.plugins:  # Only save if there are plugins loaded
            self._save_config()
    
    def load_plugins(self):
        """Load all plugins from the plugins directory"""
        if not self.plugins_dir.exists():
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            self._create_example_plugin()
            return
        
        for plugin_file in self.plugins_dir.glob("*.py"):
            if plugin_file.stem.startswith("_"):
                continue
            
            try:
                spec = importlib.util.spec_from_file_location(
                    plugin_file.stem, plugin_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Look for Plugin class in module
                    if hasattr(module, 'Plugin'):
                        plugin = module.Plugin()
                        self.plugins[plugin_file.stem] = plugin
            except Exception as e:
                print(f"Failed to load plugin {plugin_file.stem}: {e}")
    
    def _create_example_plugin(self):
        """Create an example plugin to show developers how to build plugins"""
        example_plugin = '''"""
Example Plugin for NoteDiscovery
This plugin demonstrates how to create custom plugins.
"""

class Plugin:
    def __init__(self):
        self.name = "Example Plugin"
        self.version = "1.0.0"
        self.enabled = True
    
    def on_note_save(self, note_path: str, content: str):
        """This runs every time a note is saved"""
        print(f"✓ Plugin: Note saved - {note_path}")
        
        # Example: Automatically add tags to notes
        # if '#todo' in content:
        #     print("  → Found TODO tag!")
    
    def on_note_delete(self, note_path: str):
        """This runs when a note is deleted"""
        print(f"✗ Plugin: Note deleted - {note_path}")
    
    def on_search(self, query: str, results: list):
        """This runs after a search is performed"""
        print(f"🔍 Plugin: Search performed for '{query}' ({len(results)} results)")
'''
        example_path = self.plugins_dir / "example_plugin.py"
        with open(example_path, 'w', encoding='utf-8') as f:
            f.write(example_plugin)
    
    def list_plugins(self) -> List[Dict]:
        """Get a list of all loaded plugins"""
        return [
            {
                "id": plugin_id,
                "name": plugin.name,
                "version": plugin.version,
                "enabled": plugin.enabled
            }
            for plugin_id, plugin in self.plugins.items()
        ]
    
    def _load_config(self) -> Dict[str, bool]:
        """Load plugin configuration from JSON file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load plugin config: {e}")
        return {}
    
    def _save_config(self):
        """Save current plugin states to JSON file"""
        try:
            config = {
                plugin_id: plugin.enabled
                for plugin_id, plugin in self.plugins.items()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Failed to save plugin config: {e}")

    def save_config(self):
        """
        Public wrapper to persist plugin enabled/disabled states to disk.
        This is safe to call during shutdown; errors will be caught and logged
        so that shutdown proceeds without crashing the whole process.
        """
        try:
            self._save_config()
        except Exception as e:
            print(f"Failed to persist plugin config during shutdown: {e}")
    
    def _apply_saved_state(self):
        """Apply saved plugin states after loading plugins"""
        saved_config = self._load_config()
        for plugin_id, enabled in saved_config.items():
            if plugin_id in self.plugins:
                self.plugins[plugin_id].enabled = enabled
                print(f"Plugin '{plugin_id}': {'enabled' if enabled else 'disabled'} (from config)")
    
    def enable_plugin(self, plugin_id: str):
        """Enable a plugin and persist the state"""
        if plugin_id in self.plugins:
            self.plugins[plugin_id].enabled = True
            self._save_config()
    
    def disable_plugin(self, plugin_id: str):
        """Disable a plugin and persist the state"""
        if plugin_id in self.plugins:
            self.plugins[plugin_id].enabled = False
            self._save_config()
    
    def run_hook(self, hook_name: str, **kwargs):
        """
        Run a hook on all enabled plugins.
        
        For hooks that can transform content (on_note_save, on_note_load):
        - Pass 'content' in kwargs
        - Returns the transformed content after all plugins process it
        
        For void hooks (on_note_delete, on_search, on_app_startup):
        - Just executes the hooks
        - Returns None
        
        Args:
            hook_name: Name of the hook to run
            **kwargs: Arguments to pass to the hook
            
        Returns:
            Transformed content if 'content' in kwargs, otherwise None
        """
        result = kwargs.get('content')
        
        for plugin in self.plugins.values():
            if plugin.enabled and hasattr(plugin, hook_name):
                try:
                    method = getattr(plugin, hook_name)
                    
                    # For hooks that can transform content
                    if 'content' in kwargs:
                        transformed = method(**{**kwargs, 'content': result})
                        if transformed is not None:
                            result = transformed
                    else:
                        # For void hooks (no return value)
                        method(**kwargs)
                        
                except Exception as e:
                    print(f"Plugin {plugin.name} error in {hook_name}: {e}")
        
        return result if 'content' in kwargs else None
    
    def run_hook_with_return(self, hook_name: str, **kwargs):
        """
        Run a hook that can modify and return a value (e.g., on_note_create).
        Each plugin processes the value from the previous plugin.
        
        The hook method should accept all kwargs and return the modified value.
        For on_note_create: expects (note_path, initial_content) and returns modified content.
        
        Args:
            hook_name: Name of the hook to run
            **kwargs: Arguments to pass to the hook (including the value to modify)
            
        Returns:
            Modified value after all plugins have processed it
        """
        for plugin in self.plugins.values():
            if plugin.enabled and hasattr(plugin, hook_name):
                try:
                    method = getattr(plugin, hook_name)
                    result = method(**kwargs)
                    # Update the modifiable value for the next plugin
                    if 'initial_content' in kwargs and result is not None:
                        kwargs['initial_content'] = result
                except Exception as e:
                    print(f"Plugin {plugin.name} error in {hook_name}: {e}")
        
        # Return the final modified value
        return kwargs.get('initial_content', '')
    

