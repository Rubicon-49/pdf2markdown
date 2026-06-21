# Styling — how the dark theme works

This document explains `style.css` for anyone unfamiliar with how Gradio theming works or why the CSS is structured the way it is.

---

## Two layers of styling

The app's visual appearance is controlled at two levels:

**Layer 1 — the Gradio theme object** (`THEME` in `gradio_app.py`)

Sets global defaults that Gradio applies uniformly: background colour, font family, border colour, accent colour, button colour. This is the clean, supported way to style Gradio.

```python
THEME = gradio.themes.Base(
    font=[gradio.themes.GoogleFont("DM Mono"), "monospace"],
).set(
    body_background_fill="#0d0d0d",
    button_primary_background_fill="#c8f05a",
    ...
)
```

**Layer 2 — `style.css`** (injected via `css=CUSTOM_CSS` in `demo.launch()`)

Handles everything the theme system cannot reach: component-specific overrides, the engine grid layout, checkbox toggle styling, textarea heights, the grid overlay background pattern, and the equation header classes.

---

## Why `!important` is used throughout

Gradio's built-in styles use high-specificity selectors and load after your custom CSS in the browser. Without `!important`, Gradio's defaults win. This is a known limitation of Gradio's CSS architecture — the `!important` flags are deliberate, not sloppy.

---

## CSS variables

All colours and type sizes are defined as CSS custom properties at `:root` level so they can be reused consistently throughout the file:

```css
:root {
    --bg:       #0d0d0d;   /* page background */
    --surface:  #141414;   /* card/panel backgrounds */
    --surface2: #1c1c1c;   /* input field backgrounds */
    --border:   #2a2a2a;   /* primary borders */
    --border2:  #333;      /* secondary borders */
    --accent:   #c8f05a;   /* lime green — primary interactive colour */
    --text:     #e8e8e8;   /* primary text */
    --muted:    #555;      /* subtle labels */
    --muted2:   #888;      /* slightly less subtle labels */
    --error:    #ff6b6b;   /* error states */
    --radius:   10px;      /* default border radius */
}
```

**Type scale** — four sizes covering the full range from captions to stat numbers:
```css
--text-label:   11px;   /* uppercase section labels */
--text-body:    13px;   /* checkbox labels, info text */
--text-button:  14px;   /* Convert button */
--text-display: 20px;   /* stat card numbers */
```

**Font stacks:**
```css
--font-ui:   'DM Mono', -apple-system, ...;   /* body font — DM Mono first */
--font-mono: 'DM Mono', 'SF Mono', 'Menlo';   /* code/log/preview areas */
```

Both stacks start with DM Mono, making the entire UI monospace. The fallbacks exist for cases where Google Fonts fails to load. Syne (the display font used for the Convert button and header PDF/.md text) is referenced directly rather than through a variable because it is used in only two places.

---

## The grid overlay

A subtle dot-grid is rendered behind the entire UI using a CSS pseudo-element on `.gradio-container`:

```css
.gradio-container::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(var(--border) 1px, transparent 1px),
        linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 40px 40px;
    opacity: 0.11;
    pointer-events: none;
    z-index: 0;
}
```

`pointer-events: none` ensures it never intercepts clicks. `z-index: 0` keeps it behind all content. `opacity: 0.11` makes it barely visible — it adds texture without competing with the content.

---

## The engine grid

The backend radio buttons are transformed from a default horizontal pill-strip into a 2×2 card grid. This requires overriding Gradio's radio wrapper structure:

```css
/* Make the fieldset container a 2-column grid */
.engine-grid .wrap,
.engine-grid fieldset > div {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 8px !important;
}

/* Style each option as a card with a left-border accent */
.engine-grid input[type="radio"] + span {
    display: flex !important;
    border-left: 3px solid #282828 !important;
    ...
}

/* Selected state: lime left border, dark green background */
.engine-grid input[type="radio"]:checked + span {
    border-left-color: var(--accent) !important;
    background: #141a08 !important;
    color: var(--accent) !important;
}
```

The `input[type="radio"] + span` selector targets the visible label element that sits immediately after the hidden radio input in Gradio's HTML structure. The actual `<input>` is hidden (`display: none !important`) so the label acts as the entire interactive surface.

---

## Toggle switches (checkboxes)

Gradio renders checkboxes as standard `<input type="checkbox">` elements. The CSS replaces them visually with iOS-style toggle switches using `appearance: none` and a `::after` pseudo-element:

```css
input[type="checkbox"] {
    appearance: none;
    width: 36px; height: 20px;
    background: var(--border2);
    border-radius: 20px;
}

input[type="checkbox"]::after {
    content: '';
    position: absolute;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: var(--muted2);
    /* slides right when checked via transform: translateX(16px) */
}

input[type="checkbox"]:checked {
    background: rgba(200, 240, 90, 0.25);
}

input[type="checkbox"]:checked::after {
    transform: translateX(16px);
    background: var(--accent);
}
```

The checkbox itself becomes the track, and the `::after` pseudo-element becomes the thumb.

---

## Options groups

The three groups of settings (hardware, processing, output) are visually separated with top borders:

```css
#options-hardware,
#options-processing,
#options-output {
    border-top: 1px solid var(--border) !important;
    padding: 10px 0 4px !important;
}
```

GPU (`#options-hardware`) gets slightly brighter label text than the others to signal it is the most impactful setting. Processing and output options are intentionally muted.

---

## The equation header

The header (`PDF (doc) ──[docling]──→ .md (clean)`) uses dedicated CSS classes rather than inline styles so it can be modified without touching `gradio_app.py`:

| Class | Element | Key property |
|---|---|---|
| `.eq-main` | "PDF" and ".md" text | Syne 700, 28px, `#c8c8c8` |
| `.eq-phase` | "(doc)" and "(clean)" | DM Mono 400, 11px, subscript |
| `.eq-op` | "+" operator | DM Mono 400, 18px, muted |
| `.eq-catalyst` | engine name above arrow | DM Mono 500, 10px, lime, uppercase |
| `.eq-arrow` | arrow SVG container | flex column, centered |

The SVG arrow is rendered inline in `_build_header_html()` rather than as a CSS border or text character, ensuring it renders identically across all browsers and fonts.

---

## `!important` exceptions

A handful of selectors do not need `!important` because they target elements Gradio does not style itself:

- `.eq-main`, `.eq-phase`, `.eq-catalyst`, `.eq-op`, `.eq-arrow-block` — custom classes on raw HTML
- `@keyframes pulse-border` — animation definition
- `::-webkit-scrollbar` rules — not overridden by Gradio

Everything else uses `!important`.

---

## Responsive behaviour

A single breakpoint at 640px stacks the two-column layout into a single column and allows the header to wrap:

```css
@media (max-width: 640px) {
    .gr-row { flex-direction: column !important; }
    #app-header { flex-wrap: wrap; }
}
```
