# 🎨 Themes & Customization

## Built-in Themes

NoteDiscovery comes with **8 beautiful themes** out of the box:

- 🌞 **Light** - Clean, professional, easy on the eyes
- 🌙 **Dark** - Modern dark mode for night owls
- 🧛 **Dracula** - Popular purple-tinted dark theme
- ❄️ **Nord** - Cool, Arctic-inspired color palette
- 🎨 **Monokai** - Vibrant, high-contrast theme inspired by the classic code editor theme
- 💚 **Vue High Contrast** - Dark theme with distinctive greenish tint and Vue.js aesthetics
- 🌊 **Cobalt2** - Deep ocean blue with vibrant yellow highlights, inspired by Wes Bos
- 🔷 **VS Blue** - Classic Visual Studio 2015 light blue professional theme

Switch themes anytime from the sidebar dropdown. Your preference is saved automatically!

## Create Custom Themes

### Step-by-Step Guide

#### 1. Create a CSS file in the themes directory

The file name will become the theme ID (use lowercase with hyphens):

```bash
cd notediscovery/themes
touch my-awesome-theme.css
```

#### 2. Define the theme CSS variables

**⚠️ IMPORTANT**: The `data-theme` attribute **MUST match** your filename (without `.css`).

If your file is named `my-awesome-theme.css`, use `data-theme="my-awesome-theme"`:

```css
/* My Awesome Theme - A beautiful custom theme */
/* Description of your theme */

:root[data-theme="my-awesome-theme"] {
    /* Background colors */
    --bg-primary: #ffffff;       /* Main background */
    --bg-secondary: #f6f6f6;     /* Sidebar/secondary areas */
    --bg-tertiary: #eeeeee;      /* Tertiary backgrounds */
    --bg-hover: #e5e5e5;         /* Hover state */
    --bg-active: #d4d4d4;        /* Active/pressed state */
    
    /* Text colors */
    --text-primary: #1a1a1a;     /* Main text */
    --text-secondary: #4a4a4a;   /* Secondary text */
    --text-tertiary: #6b6b6b;    /* Muted/tertiary text */
    
    /* Border colors */
    --border-primary: #d1d5db;   /* Main borders */
    --border-secondary: #e5e7eb; /* Subtle borders */
    
    /* Accent colors */
    --accent-primary: #3b82f6;   /* Links, buttons, highlights */
    --accent-hover: #2563eb;     /* Accent hover state */
    --accent-light: rgba(59, 130, 246, 0.1); /* Accent background */
    
    /* Status colors */
    --success: #10b981;          /* Success messages */
    --error: #ef4444;            /* Error messages */
    --warning: #f59e0b;          /* Warning messages */
    
    /* Shadows */
    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.15);
}
```

#### 3. (Optional) Add a custom emoji icon

Edit `backend/themes.py` and add your theme to the `theme_icons` dictionary:

```python
theme_icons = {
    # ... existing themes ...
    "my-awesome-theme": "🚀"  # Your custom emoji
}
```

If you skip this step, your theme will use 🎨 as the default icon.

#### 4. Restart the application

```bash
# If using Docker:
docker-compose restart

# If running locally:
# Stop the server (Ctrl+C) and run again:
python -m notediscovery.backend.main
```

Your new theme will appear in the dropdown as **"🚀 My Awesome Theme"**!

---

## Theme Development Tips

### ✅ Required Variables
All these CSS variables **must** be defined for your theme to work properly:
- Background: `bg-primary`, `bg-secondary`, `bg-tertiary`, `bg-hover`, `bg-active`
- Text: `text-primary`, `text-secondary`, `text-tertiary`
- Borders: `border-primary`, `border-secondary`
- Accent: `accent-primary`, `accent-hover`, `accent-light`
- Status: `success`, `error`, `warning`
- Shadows: `shadow-sm`, `shadow-md`, `shadow-lg`

### 📋 Quick Start
1. Copy an existing theme file (e.g., `dracula.css`)
2. Rename it to your theme name
3. Update the `data-theme` attribute to match
4. Modify the colors
5. Restart the app

### 🔍 Testing
- Use browser DevTools to experiment with colors live
- Test with both light and dark system preferences
- Check contrast ratios for accessibility (use [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/))
- View different content types: code blocks, tables, links, etc.

---

🎨 **Tip:** Use browser DevTools to experiment with colors in real-time before creating your theme!

