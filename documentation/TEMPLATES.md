# 📋 Note Templates

Create notes from reusable templates with dynamic placeholder replacement.

## Overview

Templates allow you to quickly create notes with predefined structures and content. Perfect for recurring note types like meeting notes, daily journals, project plans, and more.

## How to Use Templates

### 1. Create Template Files

Templates are stored in the `data/_templates/` folder as markdown files. You will need to create such folder if it doesn't exist:

```
data/
└── _templates/
    ├── meeting-notes.md
    ├── daily-journal.md
    └── project-plan.md
```

### 2. Access Templates

Click the **"New"** button (or **+** on any folder) and select **"New from Template"**:

1. Choose a template from the dropdown
2. Enter a name for your new note
3. Click "Create Note"

The template will be copied with all placeholders replaced automatically!

### 3. Use Placeholders

Templates support dynamic placeholders that are replaced when you create a note:

| Placeholder | Description | Example |
|------------|-------------|---------|
| `{{date}}` | Current date | `2025-11-26` |
| `{{time}}` | Current time | `14:30:45` |
| `{{datetime}}` | Current date and time | `2025-11-26 14:30:45` |
| `{{timestamp}}` | Unix timestamp | `1732632645` |
| `{{title}}` | Note name (without .md) | `Weekly Meeting` |
| `{{folder}}` | Parent folder name | `Projects` |

### Example Template

```markdown
---
tags: [meeting]
date: {{date}}
---

# Meeting Notes - {{title}}

**Date:** {{datetime}}  
**Participants:** 
- 

## Agenda
- 

## Discussion


## Action Items
- [ ] 

## Next Steps


```

When you create a note called "Team Sync" from this template, it becomes:

```markdown
---
tags: [meeting]
date: 2025-11-26
---

# Meeting Notes - Team Sync

**Date:** 2025-11-26 14:30:45  
**Participants:** 
- 

## Agenda
- 

## Discussion


## Action Items
- [ ] 

## Next Steps


```

## Example Templates

We provide three example templates in `documentation/templates/` that you can copy to your `data/_templates/` folder:

1. **meeting-notes.md** - Structured meeting notes with agenda, discussion, and action items
2. **daily-journal.md** - Daily journal with morning goals and evening reflection
3. **project-plan.md** - Project planning template with objectives, timeline, and status tracking

### Using Example Templates

**Option 1: Copy Manually**
```bash
cp documentation/templates/*.md data/_templates/
```

**Option 2: Create Your Own**
1. Create a `.md` file in `data/_templates/`
2. Add content and placeholders
3. Save and it's ready to use!

## Tips

- ✅ Templates can include YAML frontmatter for tags and metadata
- ✅ Use descriptive template names (they appear in the dropdown)
- ✅ Templates work in any folder - the context is preserved
- ✅ You can edit templates anytime - changes apply to new notes only
- ✅ Combine templates with tags for powerful organization

---

**See also:**
- [Tags Documentation](TAGS.md) - Learn about organizing with tags
- [Features Overview](FEATURES.md) - All application features

