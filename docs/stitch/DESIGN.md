---
name: Mint Financial Assistant
colors:
  surface: '#fbf8ff'
  surface-dim: '#d7d8f1'
  surface-bright: '#fbf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f2ff'
  surface-container: '#ececff'
  surface-container-high: '#e5e6ff'
  surface-container-highest: '#dfe1fa'
  on-surface: '#171a2c'
  on-surface-variant: '#3c4a43'
  inverse-surface: '#2c2f42'
  inverse-on-surface: '#f0efff'
  outline: '#6b7b72'
  outline-variant: '#bacac1'
  surface-tint: '#006c4f'
  primary: '#006c4f'
  on-primary: '#ffffff'
  primary-container: '#00d09c'
  on-primary-container: '#00533c'
  inverse-primary: '#2fe0aa'
  secondary: '#006c4f'
  on-secondary: '#ffffff'
  secondary-container: '#6ef7c6'
  on-secondary-container: '#007153'
  tertiary: '#006c50'
  on-tertiary: '#ffffff'
  tertiary-container: '#3ccea0'
  on-tertiary-container: '#00533d'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#59fdc5'
  primary-fixed-dim: '#2fe0aa'
  on-primary-fixed: '#002116'
  on-primary-fixed-variant: '#00513b'
  secondary-fixed: '#71fac8'
  secondary-fixed-dim: '#50ddad'
  on-secondary-fixed: '#002116'
  on-secondary-fixed-variant: '#00513b'
  tertiary-fixed: '#71fac9'
  tertiary-fixed-dim: '#50ddae'
  on-tertiary-fixed: '#002116'
  on-tertiary-fixed-variant: '#00513c'
  background: '#fbf8ff'
  on-background: '#171a2c'
  surface-variant: '#dfe1fa'
  pure-white: '#FFFFFF'
  soft-mint-tint: '#E0F8EE'
  border-divider: '#F0F0F2'
  text-muted-60: rgba(68, 71, 91, 0.60)
  text-muted-40: rgba(68, 71, 91, 0.40)
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-xl-mobile:
    fontFamily: Inter
    fontSize: 26px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.005em
  title-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: 0em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 1.5rem
  margin-desktop: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style

This design system embodies a calm, precise, and transparent regulatory-grade fintech experience. Tailored for mutual fund investors seeking clear answers and structured guidance, the interface prioritizes clarity, low cognitive load, and instant comprehension.

### Style Archetype: Precision Corporate Minimalism
The visual language operates on an uncompromising light-first environment defined by pristine white canvases, structured hairline dividers, and controlled mint accents. It eliminates visual noise, eschewing decorative gradients, heavy skeuomorphism, dark surfaces, and playful non-functional flair. Every element is engineered to deliver facts, metrics, and educational answers with total regulatory sobriety and quiet confidence.

## Colors

The palette is strictly bounded to high-trust emerald-mint greens, pure whites, and neutral graphite slate.

- **Primary (`#00D09C`)**: The core brand anchor. Used for primary call-to-actions, active indicators, and high-priority states.
- **Secondary (`#00B386`)**: Deep Mint used for hover states on primary interactive elements and high-contrast badges.
- **Tertiary (`#04B488`)**: Accent Mint for precise emphasis within informational structures.
- **Neutral (`#44475B`)**: The primary text, icon, and structural element color. Delivers optimal legibility without the harsh contrast of pure black.
- **Soft Mint Tint (`#E0F8EE`)**: The sole tinted surface token, used for query response backgrounds, selected chip fills, and subtle contextual callouts.
- **Border / Divider (`#F0F0F2`)**: Hairline boundary token maintaining structural grid integrity.
- **Text Tiers**: Muted secondary text relies strictly on `rgba(68, 71, 91, 0.60)` for captions/descriptions and `rgba(68, 71, 91, 0.40)` for disclaimers/placeholders. No arbitrary color shifts or external hues are permitted.

## Typography

The typography utilizes **Inter** (with standard geometric sans fallbacks) to deliver objective legibility across dense financial disclosures, NAV tables, and FAQ accordions.

- **Weight Hierarchy**: Constrained strictly to weights `400` (Regular for narrative, FAQ answers, and explanatory copy), `500` (Medium for interactive labels, badges, and table headers), and `600` (Semi-bold for categorical headlines, query prompts, and key values).
- **Proportional Metrics**: Line heights adhere strictly to the base-4/base-8 vertical rhythm (16px, 20px, 24px, 28px, 32px, 40px) to prevent baseline misalignments in complex question-and-answer layouts.

## Layout & Spacing

The layout is structured around an uncompromising **8px spatial grid** (with a secondary 4px unit for micro-alignments).

### Grid System & Responsive Framework
- **Desktop (1024px and above)**: Centered 12-column layout capped at a maximum width of `1160px`. Gutters are fixed at 24px (`gutter-desktop`), outer margin at 32px (`margin-desktop`).
- **Tablet (768px - 1023px)**: 8-column layout with 16px gutters (`gutter`) and 24px margins (`margin-tablet`).
- **Mobile (Below 768px)**: 4-column layout with 16px gutters (`gutter`) and 16px margins (`margin`).

### Spacing Tokens
- `space-xs` (4px): Micro-spacing between paired inline elements, icon-to-text gaps.
- `space-sm` (8px): Base rhythm unit, input internal vertical padding, badge margins.
- `space-md` (16px): Standard gap between list rows, input fields, and related FAQ blocks.
- `space-lg` (24px): Card interior padding, section item separation.
- `space-xl` (32px): Primary section stack margins and vertical content boundaries.

## Elevation & Depth

Depth in this system is achieved via flat architectural layering and subtle containment, rather than pronounced three-dimensional elevation.

### Boundary & Outline Model
Surfaces do not float aggressively. Cards, dialogs, and panels sit on pure `#FFFFFF` backdrops defined by crisp `1px solid #F0F0F2` borders.

### Shadow System
Shadows are ultra-soft and used solely to lift active interactive states and dropdown panels:
- **Default Card Shadow**: `0 2px 8px rgba(68, 71, 91, 0.04)` paired with `1px solid #F0F0F2`.
- **Card Hover / Elevation**: `0 4px 12px rgba(68, 71, 91, 0.08)` paired with `1px solid #F0F0F2`.
- **Overlay / Modal Depth**: `0 8px 24px rgba(68, 71, 91, 0.08)`.

Blur radii are tightly contained, and colors use only the muted neutral base (`#44475B`) at single-digit opacities.

## Shapes

The geometric framework is deliberate and strictly standardized:

- **Cards & Content Containers**: Fixed radius of `16px` (`rounded-lg`). Creates balanced, approachable modules for multi-step FAQ threads, mutual fund prospectuses, and tax calculators.
- **Buttons & Interactive Inputs**: Fixed radius of `10px` (`rounded`). Distinct from the card containers to immediately signpost tactile affordance.
- **Chips & Filter Pills**: Fully rounded pill shapes (`9999px`) for quick-tap suggestion questions and categorical mutual fund types (e.g., "Equity", "Debt", "ELSS").
- **Dividers & Strokes**: Standardized 1px border weight. Line icons exclusively utilize a crisp `1.5px` stroke weight with round caps and joins.

## Components

### Buttons
- **Primary Button**: Background `#00D09C`, text `#FFFFFF`, border `none`, border-radius `10px`, typography `label-md`. Hover state transitions to Deep Mint `#00B386`. Active state scales subtly or deepens.
- **Secondary Button**: Background `#FFFFFF`, text `#44475B`, border `1px solid #F0F0F2`, border-radius `10px`. Hover state: background `#E0F8EE`, border-color `#00D09C`, text `#00B386`.
- **Ghost Button**: Background `transparent`, text `#44475B`, border `none`. Hover state: text `#00D09C`.

### FAQ Accordion & Assistant Cards
- **Card Shell**: Background `#FFFFFF`, border `1px solid #F0F0F2`, border-radius `16px`, padding `space-lg` (24px), shadow `0 2px 8px rgba(68, 71, 91, 0.04)`.
- **Accordion Item**: Separated by `1px solid #F0F0F2` horizontal rules. Collapsed state displays question in `title-md` (`#44475B`) with a trailing 1.5px line chevron. Expanded state applies `#E0F8EE` to the left accent bar or subtle internal pill, revealing the answer in `body-md` (`rgba(68, 71, 91, 0.60)`).

### Chips & Suggestion Pills
- **Unselected Chip**: Background `#FFFFFF`, border `1px solid #F0F0F2`, text `rgba(68, 71, 91, 0.60)`, typography `label-sm`, border-radius `9999px`, padding `6px 14px`.
- **Selected / Active Chip**: Background `#E0F8EE`, border `1px solid #00D09C`, text `#00B386`.

### Input Fields & Search Queries
- **Container**: Height `48px`, border-radius `10px`, background `#FFFFFF`, border `1px solid #F0F0F2`, padding `0 16px`.
- **Typography**: Text `#44475B`, placeholder `rgba(68, 71, 91, 0.40)` in `body-md`.
- **Focus State**: Border `1px solid #00D09C`, subtle box-shadow `0 0 0 2px rgba(0, 208, 156, 0.12)`.
- **Leading/Trailing Icons**: 1.5px stroke line icons colored `#44475B`.

### Checkboxes & Radio Controls
- **Control Box**: 18px x 18px dimensions, border-radius `4px` (checkbox) or `50%` (radio), border `1.5px solid #F0F0F2`.
- **Checked State**: Background `#00D09C`, border-color `#00D09C`, inner checkmark or pip `#FFFFFF`.

### Financial Metric Callouts
- **Structure**: Surface `#FFFFFF`, border `1px solid #F0F0F2`, border-radius `12px`, padding `16px`. Label displayed in `label-sm` (`rgba(68, 71, 91, 0.60)`), metric value in `headline-md` (`#44475B`), with benchmark or positive change indicators rendered using `#00B386`.