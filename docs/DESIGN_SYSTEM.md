# Spatiality Design System (v0.1)

> Warm, dusk-toned UI for a 3D-twin product. Single source of truth for all
> visual decisions across `web/`. Live reference: [`/design-system`](../web/app/design-system/page.tsx).
> Tokens live in [`web/tailwind.config.mjs`](../web/tailwind.config.mjs); component
> CSS in [`web/app/styles/landing.css`](../web/app/styles/landing.css).

## Principles

1. **Warm, not cute.** Sunset palette, but surfaces stay deep and chrome stays
   minimal. No pastel illustrations, no gradients across whole sections.
2. **Show the data.** Frame counts, durations, span names, file paths are
   first-class. Monospace is the voice of the product.
3. **Editorial moments.** One serif headline per surface. The rest is sans.
   Italic in serif means accent — never bold serif.
4. **3D is the hero.** Real geometry over decoration. SVG is fine for product
   chrome, but anything that should feel "twin" lives in Three.js.
5. **Modules > pages.** Every UI region maps to a swappable component.
   Filenames mirror module names from `plans/modules/`.
6. **Don't fight the existing app.** Class names, ink scale, accent ramp and
   stage labels match `web/app/components/`. Refactor in place; don't fork.

## Color tokens

### Ink (surfaces, text, borders — warm plum → cream)

| Token         | Hex       | Use                |
| ------------- | --------- | ------------------ |
| `ink/950`     | `#1a0e14` | page bg            |
| `ink/900`     | `#261520` | cards              |
| `ink/800`     | `#36202c` | borders            |
| `ink/700`     | `#4d2f3a` | dividers           |
| `ink/600`     | `#6d4651` | dot defaults       |
| `ink/500`     | `#94656a` | captions / mono    |
| `ink/400`     | `#c08a83` | sub-text           |
| `ink/300`     | `#e6b9a3` | body               |
| `ink/200`     | `#f4dcc6` |                    |
| `ink/100`     | `#fdeede` | headings, primary fg |

### Accent (sunset ramp — coral → apricot → gold)

| Token         | Hex       | Use                                |
| ------------- | --------- | ---------------------------------- |
| `accent/500`  | `#ff6b4a` | coral · primary action             |
| `accent/400`  | `#ff9d6f` | apricot · highlights, halos        |
| `accent/300`  | `#ffd29c` | gold · serif italics, eyebrow text |

### Single-purpose hues

| Token            | Hex       | Use                          |
| ---------------- | --------- | ---------------------------- |
| `hue-magenta`    | `#ff5d8f` | horizon glow                 |
| `hue-amber`      | `#ffb347` | low sun, warn-level          |
| `hue-violet`     | `#8b5fa8` | high sky                     |
| `emerald`        | `#4ec9b0` | "ok" status only             |

### Signature gradients

- **Brand mark:** `linear-gradient(135deg, #ff6b4a 0%, #ffb347 50%, #ffd29c 100%)`
- **Hero horizon:** layered radials (coral / magenta / amber) over `ink/950`
- **Card surface:** `linear-gradient(180deg, #36202c, #1a0e14)`

## Typography

Three families. **Inter** is the workhorse. **Fraunces** appears exactly once
per surface as the editorial moment. **ui-monospace** is the data voice.

| Role            | Family          | Weight / size / line-height       | Notes                       |
| --------------- | --------------- | --------------------------------- | --------------------------- |
| Display serif   | Fraunces        | 300 · 96 / 0.98 · -2.5% tracking  | italic = `accent/300`       |
| Section title   | Fraunces        | 300 · 36–56 / 1.02                | `lp-section-title`          |
| UI title        | Inter           | 600 · 15 / 1.2                    | `lp-card-title`             |
| Body            | Inter           | 400 · 14.5 / 1.55 · `ink/300`     | `lp-section-sub`            |
| Caption / mono  | ui-monospace    | 11 · 0.04em · `ink/500`           | `lp-mono lp-muted`          |
| Eyebrow         | ui-monospace    | 10 · 0.18em · UPPERCASE           | `lp-eyebrow`                |

## Space & radius

8-pt grid. Cards pad `16/18px`. Sections pad `100px` top & bottom.

| Step  | Value | Step | Value |
| ----- | ----- | ---- | ----- |
| 2xs   | 4px   | xl   | 32px  |
| xs    | 8px   | 2xl  | 48px  |
| sm    | 12px  | 3xl  | 64px  |
| md    | 16px  |      |       |
| lg    | 24px  |      |       |

| Radius | Value  | Use                       |
| ------ | ------ | ------------------------- |
| xs     | 4px    | tags, mode chips          |
| sm     | 6px    | file chips                |
| md     | 10px   | buttons, code blocks      |
| lg     | 14px   | cards, panels             |
| xl     | 22px   | hero cards                |
| full   | 999px  | pills, navs               |

## Elevation

No traditional drop-shadows. Elevation = **border tone + backdrop blur + warm bloom**.

- **Flat surface:** `ink/900` + 1px `ink/800` border
- **Floating chrome:** `rgba(38,21,32,0.55)` + `backdrop-filter: blur(10px)` + 1px `ink/700`
- **Accent bloom:** `box-shadow: 0 0 24px rgba(255,107,74,0.35), inset 0 0 0 1px rgba(255,157,111,0.4)` (brand mark, focused state)

## Motion

| Name           | Value                              | Used for                            |
| -------------- | ---------------------------------- | ----------------------------------- |
| `motion-fast`  | `120ms ease`                       | hover, color, button press          |
| `motion-base`  | `200ms cubic-bezier(.2,.8,.2,1)`   | slide-in, panel open, list reveal   |
| `motion-slow`  | `2200ms ease-in-out`               | pulses, halos, ambient loops        |

## Component class API (`.lp-*`)

These are the production class names. Keep them verbatim when porting from
the design.

| Class                                  | Component / use                                        |
| -------------------------------------- | ------------------------------------------------------ |
| `.lp-btn` + `--primary` / `--ghost` + `--lg` / `--sm` | Buttons (3 variants × 3 sizes)                         |
| `.lp-status-pill` (+ `--ok`)           | Status pill with dot. States: idle/running/ok/warn/err |
| `.lp-eyebrow`                          | Mono uppercase pill marker over a section title       |
| `.lp-mode-chip` (+ `--on`)             | Small uppercase mode selector (orbit / pan / isolate) |
| `.lp-card` + `.lp-card-head` / `-title` | Card primitive (1px ink/800 border, 14px radius)       |
| `.lp-header`, `.lp-nav`, `.lp-brand`   | Top nav (3-region grid: brand · pill nav · CTA)        |
| `.lp-stack-rail`                       | "Powered by" rail in hero                              |
| `.lp-hero`, `.lp-hero-stats`, `.lp-stat` | Hero surface + 4-cell stats grid                     |
| `.lp-stage-list` / `.lp-stage-row`     | Pipeline stage list (grid `16 / 1fr / auto`)           |
| `.lp-log-panel` / `.lp-log-row` / `.lp-log-level--{info,ok,warn,err}` | Logfire tail surface (4 cols: time / level / span / meta) |
| `.lp-bubble--user` / `.lp-bubble--agent` | Chat bubbles                                         |
| `.lp-pin`, `.lp-pin-core`, `.lp-pin-halo`, `.lp-pin-label` | 3D-anchored annotation pin (halo loop 2.2s) |
| `.lp-module-card`                      | 9-module architecture grid card                        |
| `.lp-app-header` + `.lp-app-brand` / `.lp-app-brand-mark` / `.lp-app-brand-title` / `.lp-app-brand-id` / `.lp-app-header-tools` / `.lp-app-header-meta` | In-viewer header chrome (distinct from `.lp-header`). Serif scene title + mono scene_id. |
| `.lp-side` + `.lp-side-section` (+ `--grow`) + `.lp-side-section-head` / `.lp-side-section-title` / `.lp-side-section-accent` / `.lp-side-section-id` | Side panel shell (pipeline / objects / evidence / chat) with editorial section heads. |
| `.lp-stage-row--btn`, `.lp-stage-dot--running` / `--failed`, `.lp-stage-trace` | Clickable variant of `.lp-stage-row` for in-app pipeline. |
| `.lp-hero-stats--side` + `.lp-stat-compact` | Side-panel variant of the hero stats grid (3-up, snug). |
| `.lp-objects-list` + `.lp-objects-row` (+ `--selected` / `--isolated`) + `.lp-objects-dot` / `.lp-objects-label` / `.lp-objects-conf` / `.lp-objects-iso` (+ `--on`) | Selectable annotation list rows. |
| `.lp-chat-shell` + `.lp-chat-feed`     | Composed chat surface (list + input as one object).    |
| `.lp-bubble-serif`, `.lp-bubble-pending`, `.lp-bubble-frames` / `.lp-bubble-frame` + agent `::before` ornament | Editorial moment + frame evidence inside `.lp-bubble--agent`. |
| `.lp-chat-input--shell` + `.lp-chat-input--field` + `.lp-chat-input--send` (+ `--send-glyph`) | Refined chat composer + coral send pill. |
| `.lp-banner` (+ `--ok` / `--warn` / `--err`) + `.lp-banner-dot` / `.lp-banner-body` / `.lp-banner-title` / `.lp-banner-detail` | Floating banners over the splat canvas. |
| `.lp-anno-pill` (+ `--selected` / `--dim`) + `.lp-anno-pill-dot` / `.lp-anno-pill-id` / `.lp-anno-pill-conf` | 3D-anchored annotation billboards (mixed-case body, mono id-tag). |
| `.lp-where-btn`                        | "Where am I?" coral pill (replaces ad-hoc shadow).     |
| `.lp-evidence-grid` + `.lp-evidence-tile` + `.lp-evidence-tile-img` / `.lp-evidence-tile-mask` | "What the model saw" tile grid with CSS mask overlay. |
| `.lp-status-pill--warn` / `--err` + `.lp-status-dot--warn` / `--err` / `--idle` | Extra status modifiers. |
| `.lp-mono`, `.lp-muted`, `.lp-serif`, `.lp-serif-accent` | Inline type modifiers                |

## Voice & copy

| Do                                     | Don't                                |
| -------------------------------------- | ------------------------------------ |
| "Walk through your room."              | "Experience next-gen 3D scanning."   |
| "~90s end-to-end · iPhone Safari"      | "Lightning-fast cloud reconstruction." |
| "manifest.json is the source of truth." | "Powered by our proprietary engine."  |
| Lowercase mono captions for telemetry. | Title-Case Marketing Headers.        |
| Numbers are tabular-nums, always.      | Decorative variable-width digits.    |

## Layout

- Page max-width: `1200px` · gutter `28px`
- Section vertical padding: `100px`
- Two-column section bodies: `1.05fr / 1fr` (slightly wider left)
- Mobile breakpoints: 980px (collapse nav, stack viewer), 880px (modules → 2 col),
  720px (log panel meta hidden), 560px (modules → 1 col, secondary CTA hidden)

## Where this lives in the codebase

```
web/
├─ tailwind.config.mjs        ← ink/accent/serif tokens
├─ app/
│  ├─ layout.tsx               ← imports landing.css, loads Inter+Fraunces
│  ├─ globals.css              ← scrollbar, pin-glow
│  ├─ styles/
│  │  ├─ landing.css           ← .lp-* component CSS
│  │  └─ design-system.css     ← .ds-* doc surface CSS
│  ├─ design-system/page.tsx   ← /design-system route
│  └─ components/landing/      ← LandingHeader, Hero, Pipeline, Viewer, Modules, Footer, MeshHero
```

## Rules for future changes

- **Don't introduce new accent colors** outside the coral → apricot → gold ramp
  + the four single-purpose hues. Add tokens to `tailwind.config.mjs` and
  `landing.css` together so `.lp-*` classes and Tailwind utilities stay in
  sync.
- **Don't fork class names.** When a new component matches an existing
  primitive (card, pill, eyebrow), reuse the `.lp-*` class. Add modifiers
  with `--variant` suffix.
- **Don't load fonts via CDN.** Use `next/font/google` (already wired in
  `layout.tsx`). The CSS variables `--font-inter` and `--font-fraunces` are
  passed through to Tailwind's `font-sans` / `font-serif`.
- **Refactor in place; don't fork.** When repainting an existing component,
  update its Tailwind classes to use the same `ink/accent` keys; don't
  introduce a parallel "v2" component.
