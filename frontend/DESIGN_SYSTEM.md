# JobTomatik Visual System

## Brand idea

JobTomatik combines professional career tools with visible automation. The visual language uses a deep navy workspace, precise blue interactions, white information hierarchy, and restrained gold signals for achievement and system intelligence.

## Core palette

| Token | Value | Use |
| --- | --- | --- |
| Background | `#081220` | Main application canvas |
| Background deep | `#050B14` | Page depth and gradients |
| Surface | `#111A2E` | Navigation, cards, menus |
| Surface raised | `#17243A` | Inputs, secondary panels, selected areas |
| Surface soft | `#1A2A44` | Hover and pressed surfaces |
| Border | `#263A59` | Default separators and card outlines |
| Border strong | `#36537D` | Focused and elevated borders |
| Primary blue | `#2F6BFF` | Main calls to action and active navigation |
| Light blue | `#6AA7FF` | Highlights, icons, focus rings |
| Foreground | `#F8FAFC` | Primary text and symbols |
| Foreground soft | `#DCE4EF` | Secondary text |
| Muted | `#A8B3C7` | Metadata and captions |
| Gold | `#F2C14E` | Achievement, premium automation, interview and warning moments |
| Success | `#32C985` | Offers, completion, approved states |
| Danger | `#FF6574` | Errors, rejection, destructive actions |

## Typography

- Primary family: Inter
- Fallback family: Poppins
- Display and key numbers: 800
- Headings: 700
- Labels and buttons: 600
- Body: 400
- Numeric dashboards use tabular figures

## Shape and depth

- Inputs and buttons: 10px radius
- Cards and dialogs: 14px radius
- Branded panels and authentication surfaces: 20px radius
- Statuses and chips: pill radius
- Shadows remain cool, dark, and subtle. Blue glow is reserved for active automation and primary actions.

## Icon system

- White icons represent core navigation and neutral actions.
- Blue icons represent active tools, search, analytics, and automation.
- Gold icons represent achievement, intelligence, interviews, and high-value moments.
- Status icons use the same semantic colors as their text labels.
- The JobTomatik mark combines motion lines, a structured J, a tie, and a gold automation gear.

## Component rules

### Buttons

- Primary: blue vertical gradient, white label, blue focus ring
- Secondary: navy raised surface, soft white label, strong navy border
- Ghost: transparent surface with muted label, blue-tinted hover
- Destructive: restrained red tint, never a full bright red panel unless confirmation is critical

### Inputs and search

- Dark recessed field
- Soft navy border at rest
- Primary blue border and three-pixel blue focus halo
- Muted placeholders
- Error state uses danger border and short supporting text

### Cards and tables

- Cards use a raised navy gradient and one-pixel border
- Data rows use subtle blue hover feedback
- Tables maintain strong column alignment and tabular numbers
- Dividers use the border token rather than white opacity lines

### Statuses

- New and discovered: blue
- Applied and shortlisted: primary blue
- Interview and assessment: gold
- Offer and hired: green
- Rejected and failed: red
- Withdrawn and archived: neutral navy

### Categories

- Design and product: primary blue
- Engineering, development, and data: light blue
- Marketing: gold
- Sales and finance: green
- Operations and support: neutral

## Accessibility

- Keyboard focus is always visible
- Main text and actionable controls maintain strong contrast on navy surfaces
- Color never carries status alone; labels remain visible
- Touch targets use a minimum height of 42px
- Mobile navigation respects safe-area insets
