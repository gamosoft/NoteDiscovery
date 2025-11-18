# Mermaid Diagrams

NoteDiscovery supports **Mermaid** diagrams directly in your markdown notes! Mermaid lets you create diagrams and visualizations using text-based definitions, making it easy to version control and collaborate.

## How to Use

Simply create a code block with the language set to `mermaid`:

````markdown
```mermaid
graph TD
    A[Start] --> B{Is it working?}
    B -->|Yes| C[Great!]
    B -->|No| D[Debug]
    D --> B
```
````

## Basic Examples

### Flowchart

````markdown
```mermaid
graph LR
    A[Square Rect] --> B((Circle))
    A --> C(Round Rect)
    B --> D{Rhombus}
    C --> D
```
````

**Preview:**

```mermaid
graph LR
    A[Square Rect] --> B((Circle))
    A --> C(Round Rect)
    B --> D{Rhombus}
    C --> D
```

---

### Sequence Diagram

````markdown
```mermaid
sequenceDiagram
    Alice->>John: Hello John, how are you?
    John-->>Alice: Great!
    Alice-)John: See you later!
```
````

**Preview:**

```mermaid
sequenceDiagram
    Alice->>John: Hello John, how are you?
    John-->>Alice: Great!
    Alice-)John: See you later!
```

---

### Class Diagram

````markdown
```mermaid
classDiagram
    Animal <|-- Duck
    Animal <|-- Fish
    Animal : +int age
    Animal : +String gender
    Animal: +isMammal()
    class Duck{
        +String beakColor
        +swim()
        +quack()
    }
    class Fish{
        -int sizeInFeet
        -canEat()
    }
```
````

**Preview:**

```mermaid
classDiagram
    Animal <|-- Duck
    Animal <|-- Fish
    Animal : +int age
    Animal : +String gender
    Animal: +isMammal()
    class Duck{
        +String beakColor
        +swim()
        +quack()
    }
    class Fish{
        -int sizeInFeet
        -canEat()
    }
```

---

### State Diagram

````markdown
```mermaid
stateDiagram-v2
    [*] --> Still
    Still --> [*]
    Still --> Moving
    Moving --> Still
    Moving --> Crash
    Crash --> [*]
```
````

**Preview:**

```mermaid
stateDiagram-v2
    [*] --> Still
    Still --> [*]
    Still --> Moving
    Moving --> Still
    Moving --> Crash
    Crash --> [*]
```

---

### Gantt Chart

````markdown
```mermaid
gantt
    title Project Timeline
    dateFormat  YYYY-MM-DD
    section Planning
    Research           :a1, 2024-01-01, 30d
    Design             :after a1, 20d
    section Development
    Backend            :2024-02-01, 40d
    Frontend           :2024-02-15, 35d
    section Testing
    Integration Tests  :2024-03-20, 15d
```
````

**Preview:**

```mermaid
gantt
    title Project Timeline
    dateFormat  YYYY-MM-DD
    section Planning
    Research           :a1, 2024-01-01, 30d
    Design             :after a1, 20d
    section Development
    Backend            :2024-02-01, 40d
    Frontend           :2024-02-15, 35d
    section Testing
    Integration Tests  :2024-03-20, 15d
```

---

### Entity Relationship Diagram

````markdown
```mermaid
erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ LINE-ITEM : contains
    CUSTOMER }|..|{ DELIVERY-ADDRESS : uses
    
    CUSTOMER {
        string name
        string email
        string phone
    }
    ORDER {
        int orderNumber
        date orderDate
        string status
    }
```
````

**Preview:**

```mermaid
erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ LINE-ITEM : contains
    CUSTOMER }|..|{ DELIVERY-ADDRESS : uses
    
    CUSTOMER {
        string name
        string email
        string phone
    }
    ORDER {
        int orderNumber
        date orderDate
        string status
    }
```

---

### Pie Chart

````markdown
```mermaid
pie title Pet Preferences
    "Dogs" : 45
    "Cats" : 30
    "Birds" : 15
    "Fish" : 10
```
````

**Preview:**

```mermaid
pie title Pet Preferences
    "Dogs" : 45
    "Cats" : 30
    "Birds" : 15
    "Fish" : 10
```

---

### Git Graph

````markdown
```mermaid
gitGraph
    commit
    commit
    branch develop
    checkout develop
    commit
    commit
    checkout main
    merge develop
    commit
```
````

**Preview:**

```mermaid
gitGraph
    commit
    commit
    branch develop
    checkout develop
    commit
    commit
    checkout main
    merge develop
    commit
```

---

### User Journey

````markdown
```mermaid
journey
    title My Working Day
    section Go to work
      Make tea: 5: Me
      Go upstairs: 3: Me
      Do work: 1: Me, Cat
    section Go home
      Go downstairs: 5: Me
      Sit down: 5: Me
```
````

**Preview:**

```mermaid
journey
    title My Working Day
    section Go to work
      Make tea: 5: Me
      Go upstairs: 3: Me
      Do work: 1: Me, Cat
    section Go home
      Go downstairs: 5: Me
      Sit down: 5: Me
```

---

### Mindmap

````markdown
```mermaid
mindmap
  root((NoteDiscovery))
    Features
      Markdown
      Themes
      Search
      Folders
    Integrations
      MathJax
      Mermaid
      Syntax Highlighting
    Benefits
      Fast
      Simple
      Offline-first
```
````

**Preview:**

```mermaid
mindmap
  root((NoteDiscovery))
    Features
      Markdown
      Themes
      Search
      Folders
    Integrations
      MathJax
      Mermaid
      Syntax Highlighting
    Benefits
      Fast
      Simple
      Offline-first
```

---

## Theme Support

Mermaid diagrams automatically adapt to your current NoteDiscovery theme:
- **Light themes** use the default Mermaid color scheme
- **Dark themes** use dark-optimized colors with proper contrast
- Theme changes automatically re-render all diagrams

## Tips

1. **Keep it simple**: Start with basic diagrams and add complexity as needed
2. **Use comments**: Add `%%` for comments in your Mermaid code
3. **Test syntax**: If a diagram doesn't render, check the Mermaid [documentation](https://mermaid.js.org/)
4. **Export**: Diagrams are included when you export notes to HTML

## More Information

For the complete Mermaid syntax and more diagram types, visit the official documentation:
- [Mermaid Documentation](https://mermaid.js.org/)
- [Live Editor](https://mermaid.live/) - Test your diagrams online

---

**Pro Tip**: Combine Mermaid diagrams with LaTeX math expressions and code blocks for comprehensive technical documentation! 📊

