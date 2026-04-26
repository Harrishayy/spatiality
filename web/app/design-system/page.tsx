import "../styles/design-system.css";

export const metadata = { title: "Spatiality — Design System" };

const BODY = String.raw`
<div class="ds-shell">
  <aside class="ds-side">
    <div class="ds-side-brand">
      <div class="lp-brand-mark"></div>
      <div>
        <div class="ds-side-title">Spatiality DS</div>
        <span class="ds-side-sub">v0.1 · render branch</span>
      </div>
    </div>
    <a class="ds-back" href="/">← Back to landing</a>

    <div class="ds-side-group">
      <div class="ds-side-group-label">Foundation</div>
      <a class="ds-side-link" href="#principles"><span class="ds-side-link-id">00</span>Principles</a>
      <a class="ds-side-link" href="#color"><span class="ds-side-link-id">01</span>Color</a>
      <a class="ds-side-link" href="#type"><span class="ds-side-link-id">02</span>Typography</a>
      <a class="ds-side-link" href="#space"><span class="ds-side-link-id">03</span>Space &amp; radius</a>
      <a class="ds-side-link" href="#elev"><span class="ds-side-link-id">04</span>Elevation</a>
      <a class="ds-side-link" href="#motion"><span class="ds-side-link-id">05</span>Motion</a>
    </div>
    <div class="ds-side-group">
      <div class="ds-side-group-label">Components</div>
      <a class="ds-side-link" href="#buttons"><span class="ds-side-link-id">06</span>Buttons</a>
      <a class="ds-side-link" href="#pills"><span class="ds-side-link-id">07</span>Pills &amp; status</a>
      <a class="ds-side-link" href="#inputs"><span class="ds-side-link-id">08</span>Inputs</a>
      <a class="ds-side-link" href="#cards"><span class="ds-side-link-id">09</span>Cards</a>
      <a class="ds-side-link" href="#nav"><span class="ds-side-link-id">10</span>Navbar</a>
      <a class="ds-side-link" href="#stages"><span class="ds-side-link-id">11</span>Stage list</a>
      <a class="ds-side-link" href="#log"><span class="ds-side-link-id">12</span>Log panel</a>
      <a class="ds-side-link" href="#chat"><span class="ds-side-link-id">13</span>Chat bubbles</a>
      <a class="ds-side-link" href="#pins"><span class="ds-side-link-id">14</span>Annotation pins</a>
      <a class="ds-side-link" href="#app-surface"><span class="ds-side-link-id">14a</span>App surface</a>
    </div>
    <div class="ds-side-group">
      <div class="ds-side-group-label">Patterns</div>
      <a class="ds-side-link" href="#voice"><span class="ds-side-link-id">15</span>Voice &amp; copy</a>
      <a class="ds-side-link" href="#layout"><span class="ds-side-link-id">16</span>Layout</a>
      <a class="ds-side-link" href="#tokens"><span class="ds-side-link-id">17</span>Tokens (full)</a>
    </div>
  </aside>

  <main class="ds-main">
    <header class="ds-doc-head">
      <span class="ds-doc-eyebrow">Design system · v0.1</span>
      <h1 class="ds-doc-title"><span class="lp-serif">Spatiality</span> <em>at golden hour</em>.</h1>
      <p class="ds-doc-sub">A warm, dusk-toned system for a 3D-twin product. Built around a deep plum surface, a coral→apricot→gold accent ramp, and the same monospace-meets-editorial voice the existing app already uses. Hand this file to Claude Code as the source of truth — every token, component and rule below is implemented in <code>landing.css</code> and ready to lift into <code>web/app/styles/</code>.</p>
    </header>

    <!-- 00 PRINCIPLES -->
    <section id="principles" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">00</span><h2 class="ds-section-title">Principles</h2></div>
      <p class="ds-section-sub">Five rules that decide every micro-decision. When in doubt, re-read these.</p>
      <div class="ds-principles">
        <div class="ds-principle"><div class="ds-principle-num">01</div><div class="ds-principle-title">Warm, not cute</div><p class="ds-principle-body">Sunset palette, but the surfaces stay deep and the chrome stays minimal. No pastel illustrations, no gradients across whole sections.</p></div>
        <div class="ds-principle"><div class="ds-principle-num">02</div><div class="ds-principle-title">Show the data</div><p class="ds-principle-body">Frame counts, durations, span names, file paths are first-class. Monospace is the voice of the product.</p></div>
        <div class="ds-principle"><div class="ds-principle-num">03</div><div class="ds-principle-title">Editorial moments</div><p class="ds-principle-body">One serif headline per surface. The rest is sans. Italic in serif means accent — never bold serif.</p></div>
        <div class="ds-principle"><div class="ds-principle-num">04</div><div class="ds-principle-title">3D is the hero</div><p class="ds-principle-body">Real geometry over decoration. SVG is fine for product chrome, but anything that should feel "twin" lives in Three.js.</p></div>
        <div class="ds-principle"><div class="ds-principle-num">05</div><div class="ds-principle-title">Modules > pages</div><p class="ds-principle-body">Every UI region maps to a swappable component. No God-files. Filenames mirror module names from <code>plans/modules/</code>.</p></div>
        <div class="ds-principle"><div class="ds-principle-num">06</div><div class="ds-principle-title">Don't fight the existing app</div><p class="ds-principle-body">Class names, ink scale, accent ramp and stage labels match what's already in <code>web/app/components/</code>. Refactor in place; don't fork.</p></div>
      </div>
    </section>

    <!-- 01 COLOR -->
    <section id="color" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">01</span><h2 class="ds-section-title">Color</h2></div>
      <p class="ds-section-sub">Two ramps: <strong>ink</strong> (surfaces, text, borders — warm plum→cream) and <strong>accent</strong> (coral→apricot→gold). Plus four single-purpose hues for highlights and status.</p>

      <div class="ds-sub"><div class="ds-sub-title">ink · surfaces &amp; text (10 steps)</div>
      <div class="ds-swatch-grid">
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#1a0e14"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/950</div><span class="ds-swatch-token">--ink-950 · page bg</span><span class="ds-swatch-hex">#1a0e14</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#261520"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/900</div><span class="ds-swatch-token">--ink-900 · cards</span><span class="ds-swatch-hex">#261520</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#36202c"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/800</div><span class="ds-swatch-token">--ink-800 · borders</span><span class="ds-swatch-hex">#36202c</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#4d2f3a"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/700</div><span class="ds-swatch-token">--ink-700 · dividers</span><span class="ds-swatch-hex">#4d2f3a</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#6d4651"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/600</div><span class="ds-swatch-token">--ink-600</span><span class="ds-swatch-hex">#6d4651</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#94656a"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/500</div><span class="ds-swatch-token">--ink-500 · captions</span><span class="ds-swatch-hex">#94656a</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#c08a83"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/400</div><span class="ds-swatch-token">--ink-400 · sub-text</span><span class="ds-swatch-hex">#c08a83</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#e6b9a3"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/300</div><span class="ds-swatch-token">--ink-300 · body</span><span class="ds-swatch-hex">#e6b9a3</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#f4dcc6"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/200</div><span class="ds-swatch-token">--ink-200</span><span class="ds-swatch-hex">#f4dcc6</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#fdeede"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">ink/100</div><span class="ds-swatch-token">--ink-100 · headings</span><span class="ds-swatch-hex">#fdeede</span></div></div>
      </div></div>

      <div class="ds-sub"><div class="ds-sub-title">accent · sunset ramp (3 steps)</div>
      <div class="ds-swatch-grid" style="grid-template-columns:repeat(3,1fr)">
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#ff6b4a"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">accent/500 · coral</div><span class="ds-swatch-token">--accent-500 · primary action</span><span class="ds-swatch-hex">#ff6b4a</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#ff9d6f"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">accent/400 · apricot</div><span class="ds-swatch-token">--accent-400 · highlights</span><span class="ds-swatch-hex">#ff9d6f</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#ffd29c"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">accent/300 · gold</div><span class="ds-swatch-token">--accent-300 · serif italics, eyebrow</span><span class="ds-swatch-hex">#ffd29c</span></div></div>
      </div></div>

      <div class="ds-sub"><div class="ds-sub-title">single-purpose hues</div>
      <div class="ds-swatch-grid" style="grid-template-columns:repeat(4,1fr)">
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#ff5d8f"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">magenta</div><span class="ds-swatch-token">--hue-magenta · horizon glow</span><span class="ds-swatch-hex">#ff5d8f</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#ffb347"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">amber</div><span class="ds-swatch-token">--hue-amber · low sun, warn</span><span class="ds-swatch-hex">#ffb347</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#8b5fa8"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">violet</div><span class="ds-swatch-token">--hue-violet · high sky</span><span class="ds-swatch-hex">#8b5fa8</span></div></div>
        <div class="ds-swatch"><div class="ds-swatch-chip" style="background:#4ec9b0"></div><div class="ds-swatch-meta"><div class="ds-swatch-name">teal</div><span class="ds-swatch-token">--emerald · "ok" only</span><span class="ds-swatch-hex">#4ec9b0</span></div></div>
      </div></div>

      <div class="ds-sub"><div class="ds-sub-title">signature gradients</div>
      <div class="ds-grad-row">
        <div class="ds-grad"><div class="ds-grad-band" style="background:linear-gradient(135deg,#ff6b4a 0%,#ffb347 50%,#ffd29c 100%)"></div><div class="ds-grad-meta"><div class="ds-swatch-name">brand mark</div><span class="ds-swatch-token">coral → amber → gold · 135°</span></div></div>
        <div class="ds-grad"><div class="ds-grad-band" style="background:radial-gradient(ellipse at 50% 100%,#ff6b4a 0%,#ff5d8f 35%,transparent 70%),#1a0e14"></div><div class="ds-grad-meta"><div class="ds-swatch-name">hero horizon</div><span class="ds-swatch-token">layered radials over ink/950</span></div></div>
        <div class="ds-grad"><div class="ds-grad-band" style="background:linear-gradient(180deg,#36202c,#1a0e14)"></div><div class="ds-grad-meta"><div class="ds-swatch-name">card surface</div><span class="ds-swatch-token">ink/800 → ink/950</span></div></div>
      </div></div>
    </section>

    <!-- 02 TYPE -->
    <section id="type" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">02</span><h2 class="ds-section-title">Typography</h2></div>
      <p class="ds-section-sub">Three families. <strong>Inter</strong> is the workhorse. <strong>Fraunces</strong> shows up exactly once per surface as the editorial moment. <strong>ui-monospace</strong> is the data voice — durations, file paths, span names, captions.</p>

      <div class="ds-type-row"><div class="ds-type-meta"><strong>Display / serif</strong><br/>Fraunces · 300 · -2.5%<br/>96 / 0.98<br/><em>italic = accent/300</em></div><div class="ds-type-sample lp-serif" style="font-size:64px;line-height:1;">Walk through <em style="font-style:italic;color:var(--accent-300)">your room.</em></div></div>
      <div class="ds-type-row"><div class="ds-type-meta"><strong>Section title</strong><br/>Fraunces · 300<br/>40 / 1.02</div><div class="ds-type-sample lp-serif" style="font-size:36px;line-height:1.05;">From video to twin in ~90s.</div></div>
      <div class="ds-type-row"><div class="ds-type-meta"><strong>UI title</strong><br/>Inter · 600<br/>15 / 1.2</div><div class="ds-type-sample" style="font-size:15px;font-weight:600;">Reconstruction (VGGT)</div></div>
      <div class="ds-type-row"><div class="ds-type-meta"><strong>Body</strong><br/>Inter · 400<br/>14.5 / 1.55<br/>color: ink/300</div><div class="ds-type-sample" style="font-size:14.5px;color:var(--ink-300);max-width:520px;">Capture with Ray-Ban glasses. Reconstruct in seconds. Ask the room where you are — and what you're looking at.</div></div>
      <div class="ds-type-row"><div class="ds-type-meta"><strong>Caption / mono</strong><br/>ui-monospace · 11<br/>tracking 0.04em<br/>color: ink/500</div><div class="ds-type-sample lp-mono lp-muted" style="font-size:11px;">artifacts/scenes/living_room_03/ · 60.3s</div></div>
      <div class="ds-type-row"><div class="ds-type-meta"><strong>Eyebrow</strong><br/>ui-monospace · 10<br/>UPPERCASE · tracking 0.18em</div><div class="ds-type-sample lp-mono" style="font-size:10px;letter-spacing:0.2em;text-transform:uppercase;color:var(--accent-300);">01 · pipeline</div></div>
    </section>

    <!-- 03 SPACE -->
    <section id="space" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">03</span><h2 class="ds-section-title">Space &amp; radius</h2></div>
      <p class="ds-section-sub">8-pt grid. Pad cards <code>16/18px</code>, sections <code>100px</code> top &amp; bottom. Radii lean small for chrome (6–10) and large for surfaces (14–22).</p>

      <div class="ds-sub"><div class="ds-sub-title">spacing scale</div>
      <div class="ds-step-row">
        <div class="ds-step"><div class="ds-step-vis" style="width:4px;height:4px"></div><div class="ds-step-name">2xs</div><span class="ds-step-val">4px</span></div>
        <div class="ds-step"><div class="ds-step-vis" style="width:8px;height:8px"></div><div class="ds-step-name">xs</div><span class="ds-step-val">8px</span></div>
        <div class="ds-step"><div class="ds-step-vis" style="width:12px;height:12px"></div><div class="ds-step-name">sm</div><span class="ds-step-val">12px</span></div>
        <div class="ds-step"><div class="ds-step-vis" style="width:16px;height:16px"></div><div class="ds-step-name">md</div><span class="ds-step-val">16px</span></div>
        <div class="ds-step"><div class="ds-step-vis" style="width:24px;height:24px"></div><div class="ds-step-name">lg</div><span class="ds-step-val">24px</span></div>
        <div class="ds-step"><div class="ds-step-vis" style="width:32px;height:32px"></div><div class="ds-step-name">xl</div><span class="ds-step-val">32px</span></div>
        <div class="ds-step"><div class="ds-step-vis" style="width:48px;height:48px"></div><div class="ds-step-name">2xl</div><span class="ds-step-val">48px</span></div>
        <div class="ds-step"><div class="ds-step-vis" style="width:64px;height:64px"></div><div class="ds-step-name">3xl</div><span class="ds-step-val">64px</span></div>
      </div></div>

      <div class="ds-sub"><div class="ds-sub-title">border radius</div>
      <div class="ds-radius-row">
        <div class="ds-radius"><div class="ds-radius-vis" style="border-radius:4px"></div><div class="ds-step-name">xs · 4</div><span class="ds-step-val">tags, mode chips</span></div>
        <div class="ds-radius"><div class="ds-radius-vis" style="border-radius:6px"></div><div class="ds-step-name">sm · 6</div><span class="ds-step-val">file chips</span></div>
        <div class="ds-radius"><div class="ds-radius-vis" style="border-radius:10px"></div><div class="ds-step-name">md · 10</div><span class="ds-step-val">buttons, code blocks</span></div>
        <div class="ds-radius"><div class="ds-radius-vis" style="border-radius:14px"></div><div class="ds-step-name">lg · 14</div><span class="ds-step-val">cards, panels</span></div>
        <div class="ds-radius"><div class="ds-radius-vis" style="border-radius:22px"></div><div class="ds-step-name">xl · 22</div><span class="ds-step-val">hero cards</span></div>
        <div class="ds-radius"><div class="ds-radius-vis" style="border-radius:999px"></div><div class="ds-step-name">full</div><span class="ds-step-val">pills, navs</span></div>
      </div></div>
    </section>

    <!-- 04 ELEVATION -->
    <section id="elev" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">04</span><h2 class="ds-section-title">Elevation</h2></div>
      <p class="ds-section-sub">We don't use traditional drop-shadows. Elevation is communicated through <strong>border tone</strong>, <strong>backdrop-filter blur</strong>, and <strong>warm bloom</strong> from the accent.</p>
      <div class="ds-shadow-row">
        <div class="ds-shadow"><div class="ds-shadow-vis" style="background:var(--ink-900);border:1px solid var(--ink-800)"></div><div class="ds-step-name">flat / surface</div><span class="ds-step-val">ink/900 + 1px ink/800 border</span></div>
        <div class="ds-shadow"><div class="ds-shadow-vis" style="background:rgba(38,21,32,0.55);backdrop-filter:blur(10px);border:1px solid var(--ink-700)"></div><div class="ds-step-name">floating / chrome</div><span class="ds-step-val">blur(10) + ink/700 border</span></div>
        <div class="ds-shadow"><div class="ds-shadow-vis" style="background:var(--ink-900);box-shadow:0 0 24px rgba(255,107,74,0.35),inset 0 0 0 1px rgba(255,157,111,0.4)"></div><div class="ds-step-name">accent bloom</div><span class="ds-step-val">brand-mark / focused state</span></div>
      </div>
    </section>

    <!-- 05 MOTION -->
    <section id="motion" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">05</span><h2 class="ds-section-title">Motion</h2></div>
      <p class="ds-section-sub">Two timing functions, three durations, no exceptions.</p>
      <table class="ds-table">
        <thead><tr><th>name</th><th>value</th><th>used for</th></tr></thead>
        <tbody>
          <tr><td class="c-mono">--motion-fast</td><td class="c-mono">120ms ease</td><td class="c-muted">hover, color, button press</td></tr>
          <tr><td class="c-mono">--motion-base</td><td class="c-mono">200ms cubic-bezier(.2,.8,.2,1)</td><td class="c-muted">slide-in, panel open, list reveal</td></tr>
          <tr><td class="c-mono">--motion-slow</td><td class="c-mono">2200ms ease-in-out</td><td class="c-muted">pulses, halos, ambient loops</td></tr>
        </tbody>
      </table>
    </section>

    <!-- 06 BUTTONS -->
    <section id="buttons" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">06</span><h2 class="ds-section-title">Buttons</h2></div>
      <p class="ds-section-sub">Three variants × three sizes. Primary uses the cream surface (ink/100 on ink/950) for highest contrast — the accent ramp shows up on icons, hovers and special CTAs, not flat fills.</p>
      <div class="ds-example">
        <div class="ds-example-canvas">
          <button class="lp-btn lp-btn-primary lp-btn-lg">Upload video <span class="lp-btn-arrow">→</span></button>
          <button class="lp-btn lp-btn-primary">Upload video</button>
          <button class="lp-btn lp-btn-primary lp-btn-sm">Upload</button>
          <button class="lp-btn lp-btn-ghost lp-btn-lg">View demo scene</button>
          <button class="lp-btn lp-btn-ghost">View demo</button>
          <button class="lp-btn lp-btn-ghost lp-btn-sm">View</button>
        </div>
        <div class="ds-example-foot"><strong>&lt;Button variant="primary | ghost" size="sm | md | lg" /&gt;</strong><span>landing.css → .lp-btn</span></div>
      </div>
    </section>

    <!-- 07 PILLS -->
    <section id="pills" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">07</span><h2 class="ds-section-title">Pills &amp; status</h2></div>
      <p class="ds-section-sub">All states in the app are one of: <code>idle</code>, <code>running</code>, <code>ok</code>, <code>warn</code>, <code>err</code>. Each maps to a single dot+pill style.</p>
      <div class="ds-example">
        <div class="ds-example-canvas">
          <span class="lp-status-pill"><span class="lp-status-dot"></span>queued</span>
          <span class="lp-status-pill"><span class="lp-status-dot"></span>running · 12.4s</span>
          <span class="lp-status-pill lp-status-pill--ok"><span class="lp-status-dot lp-status-dot--ok"></span>ready · 60.3s</span>
          <span class="lp-eyebrow"><span class="lp-eyebrow-dot"></span>01 · pipeline</span>
          <span class="lp-mode-chip lp-mono">pan</span>
          <span class="lp-mode-chip lp-mode-chip--on lp-mono">orbit</span>
        </div>
        <div class="ds-example-foot"><strong>&lt;StatusPill state="ok" /&gt; · &lt;Eyebrow /&gt; · &lt;ModeChip active /&gt;</strong><span>.lp-status-pill / .lp-eyebrow / .lp-mode-chip</span></div>
      </div>
    </section>

    <!-- 08 INPUTS -->
    <section id="inputs" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">08</span><h2 class="ds-section-title">Inputs</h2></div>
      <div class="ds-example">
        <div class="ds-example-canvas ds-example-canvas--col">
          <div class="lp-chat-input" style="width:360px;border:1px solid var(--ink-800);border-radius:10px;">
            <span class="lp-mono lp-muted">›</span>
            <span class="lp-mono lp-muted">ask the room…</span>
            <button class="lp-mic" aria-label="voice"><svg viewBox="0 0 24 24" width="14" height="14"><rect x="9" y="3" width="6" height="12" rx="3" fill="currentColor"></rect><path d="M5 11a7 7 0 0 0 14 0" stroke="currentColor" stroke-width="1.5" fill="none"></path><line x1="12" y1="18" x2="12" y2="22" stroke="currentColor" stroke-width="1.5"></line></svg></button>
          </div>
        </div>
        <div class="ds-example-foot"><strong>&lt;ChatInput /&gt;</strong><span>.lp-chat-input</span></div>
      </div>
    </section>

    <!-- 09 CARDS -->
    <section id="cards" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">09</span><h2 class="ds-section-title">Cards</h2></div>
      <p class="ds-section-sub">One card primitive. Always: 1px ink/800 border, gradient ink/800→ink/950 surface, 14px radius, head + body + optional foot. Hover lift only on interactive cards.</p>
      <div class="ds-example">
        <div class="ds-example-canvas">
          <div class="lp-card" style="width:340px;">
            <div class="lp-card-head"><div class="lp-card-head-l"><h3 class="lp-card-title">Pipeline</h3><span class="lp-mono lp-muted">scene_03</span></div><span class="lp-status-pill lp-status-pill--ok"><span class="lp-status-dot lp-status-dot--ok"></span>ready</span></div>
            <div style="padding:18px;color:var(--ink-300);font-size:13px;line-height:1.55;">Card body. Use this primitive for every grouped surface — pipeline, log panel, viewer chrome, modules.</div>
          </div>
        </div>
        <div class="ds-example-foot"><strong>&lt;Card head={…} foot={…} /&gt;</strong><span>.lp-card / .lp-card-head / .lp-card-title</span></div>
      </div>
    </section>

    <!-- 10 NAVBAR -->
    <section id="nav" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">10</span><h2 class="ds-section-title">Navbar</h2></div>
      <p class="ds-section-sub">Three-region grid: brand left, segmented pill nav center, CTA cluster right. Mobile drops the nav and the secondary CTA — never the brand.</p>
      <div class="ds-example">
        <div class="ds-example-canvas" style="padding:0;display:block;">
          <div style="position:relative;">
            <header class="lp-header" style="position:relative;top:auto;">
              <div class="lp-header-l">
                <a class="lp-brand" href="#"><div class="lp-brand-mark"></div><span class="lp-brand-title">Spatiality</span></a>
                <span class="lp-brand-divider"></span>
                <span class="lp-mono lp-muted lp-brand-tag">glasses → 3D twin</span>
              </div>
              <nav class="lp-nav">
                <a href="#">Pipeline</a>
                <a href="#">Viewer</a>
                <a href="#">Agent</a>
                <a href="#">Docs</a>
                <span class="lp-nav-divider"></span>
                <a href="#" class="lp-nav-meta"><span class="lp-nav-meta-dot"></span>v0.4.2</a>
              </nav>
              <div class="lp-header-r">
                <a class="lp-btn lp-btn-ghost lp-btn-sm" href="#">Live demo</a>
                <a class="lp-btn lp-btn-primary lp-btn-sm" href="#">Upload video <span class="lp-btn-arrow">→</span></a>
              </div>
            </header>
          </div>
        </div>
        <div class="ds-example-foot"><strong>&lt;Header /&gt;</strong><span>web/app/components/landing/Header.tsx</span></div>
      </div>
    </section>

    <!-- 11 STAGES -->
    <section id="stages" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">11</span><h2 class="ds-section-title">Stage list</h2></div>
      <p class="ds-section-sub">Mirrors <code>web/app/components/PipelineProgress.tsx</code>. Same stage order, same labels, same mono duration column.</p>
      <div class="ds-example">
        <div class="ds-example-canvas">
          <ol class="lp-stage-list lp-card" style="width:100%;list-style:none;margin:0;padding:0;">
            <li class="lp-stage-row"><span class="lp-stage-dot lp-stage-dot--complete"></span><div class="lp-stage-meta"><div class="lp-stage-label">Capture</div><div class="lp-stage-sub lp-mono">frames + audio extracted</div></div><div class="lp-stage-numbers"><span class="lp-mono lp-muted">120 frames</span><span class="lp-mono lp-stage-dur">4.1s</span></div></li>
            <li class="lp-stage-row"><span class="lp-stage-dot lp-stage-dot--complete"></span><div class="lp-stage-meta"><div class="lp-stage-label">Reconstruction (VGGT)</div><div class="lp-stage-sub lp-mono">poses + dense surfels</div></div><div class="lp-stage-numbers"><span class="lp-mono lp-muted">120 / 240</span><span class="lp-mono lp-stage-dur">38.7s</span></div></li>
            <li class="lp-stage-row"><span class="lp-stage-dot lp-stage-dot--complete"></span><div class="lp-stage-meta"><div class="lp-stage-label">Segmentation</div><div class="lp-stage-sub lp-mono">SAM 3.1 + VLM labels</div></div><div class="lp-stage-numbers"><span class="lp-mono lp-muted">27 obj</span><span class="lp-mono lp-stage-dur">11.2s</span></div></li>
          </ol>
        </div>
        <div class="ds-example-foot"><strong>&lt;StageList stages={manifest.stages} /&gt;</strong><span>.lp-stage-row · grid 16 / 1fr / auto</span></div>
      </div>
    </section>

    <!-- 12 LOG -->
    <section id="log" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">12</span><h2 class="ds-section-title">Log panel</h2></div>
      <p class="ds-section-sub">The "tail -f" surface for Logfire spans. Four columns: <code>time · level · span · meta</code>. Levels: info / ok / warn / err.</p>
      <div class="ds-example">
        <div class="ds-example-canvas" style="padding:0;display:block;">
          <div class="lp-log-body" style="padding:14px 16px">
            <div class="lp-log-row"><span class="lp-mono lp-log-time">04.10</span><span class="lp-log-level lp-mono lp-log-level--ok">ok</span><span class="lp-mono lp-log-name">capture.done</span><span class="lp-mono lp-log-meta">duration=4.1s</span></div>
            <div class="lp-log-row"><span class="lp-mono lp-log-time">12.40</span><span class="lp-log-level lp-mono lp-log-level--info">info</span><span class="lp-mono lp-log-name">infer.poses.progress</span><span class="lp-mono lp-log-meta">frames=80/120 conf=0.91</span></div>
            <div class="lp-log-row"><span class="lp-mono lp-log-time">42.80</span><span class="lp-log-level lp-mono lp-log-level--warn">warn</span><span class="lp-mono lp-log-name">segment.sam31.iou</span><span class="lp-mono lp-log-meta">low conf masks=12</span></div>
            <div class="lp-log-row"><span class="lp-mono lp-log-time">60.31</span><span class="lp-log-level lp-mono lp-log-level--ok">ok</span><span class="lp-mono lp-log-name">manifest.write</span><span class="lp-mono lp-log-meta">status=ready</span></div>
          </div>
        </div>
        <div class="ds-example-foot"><strong>&lt;LogPanel spans={spans} /&gt;</strong><span>.lp-log-row · 50 / 44 / 200 / 1fr</span></div>
      </div>
    </section>

    <!-- 13 CHAT -->
    <section id="chat" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">13</span><h2 class="ds-section-title">Chat bubbles</h2></div>
      <div class="ds-example">
        <div class="ds-example-canvas ds-example-canvas--col" style="background:var(--ink-900);">
          <div class="lp-bubble lp-bubble--user" style="align-self:flex-end"><div class="lp-bubble-text">where am I right now?</div><div class="lp-bubble-meta lp-mono">cam · (1.20, 1.65, 2.40)</div></div>
          <div class="lp-bubble lp-bubble--agent"><div class="lp-bubble-text">You're in the centre of the living room, facing north. The grey couch is 1.2m to your left.</div><div class="lp-bubble-meta lp-mono">haiku-4-5 · 1.94s · 3 nearby</div></div>
        </div>
        <div class="ds-example-foot"><strong>&lt;Bubble role="user|agent" meta={…} /&gt;</strong><span>.lp-bubble--user · .lp-bubble--agent</span></div>
      </div>
    </section>

    <!-- 14 PINS -->
    <section id="pins" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">14</span><h2 class="ds-section-title">Annotation pins</h2></div>
      <p class="ds-section-sub">3D-anchored billboards over the splat viewer. Core dot + animated halo + uppercase mono label.</p>
      <div class="ds-example">
        <div class="ds-example-canvas" style="background:#1a0e14;height:140px;position:relative;">
          <div class="lp-pin" style="position:absolute;left:30%;top:50%"><span class="lp-pin-core"></span><span class="lp-pin-halo"></span><span class="lp-pin-label"><span class="lp-mono">couch</span><span class="lp-mono lp-muted">· conf 0.96</span></span></div>
          <div class="lp-pin" style="position:absolute;left:65%;top:50%"><span class="lp-pin-core"></span><span class="lp-pin-halo"></span><span class="lp-pin-label"><span class="lp-mono">coffee table</span><span class="lp-mono lp-muted">· conf 0.91</span></span></div>
        </div>
        <div class="ds-example-foot"><strong>&lt;AnnotationPin annotation={a} /&gt;</strong><span>.lp-pin · halo loop 2.2s</span></div>
      </div>
    </section>

    <!-- 14a APP SURFACE -->
    <section id="app-surface" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">14a</span><h2 class="ds-section-title">App surface (in-viewer)</h2></div>
      <p class="ds-section-sub">Primitives shared by the in-app viewer at <code>/scenes/[id]</code>: app header, side panel, refined chat shell, banners, anno pills, where-am-I.</p>

      <div class="ds-example">
        <div class="ds-example-canvas" style="padding:0;background:#1a0e14;">
          <header class="lp-app-header">
            <div class="lp-app-brand">
              <span class="lp-app-brand-mark"></span>
              <div class="lp-app-brand-meta">
                <span class="lp-app-brand-title">Glasses → 3D Twin</span>
                <span class="lp-app-brand-id">dec5d8d886e6e</span>
              </div>
            </div>
            <div></div>
            <div class="lp-app-header-meta">
              <span class="lp-status-pill lp-status-pill--ok"><span class="lp-status-dot lp-status-dot--ok"></span>gateway:eu · key:set · 184ms</span>
              <span class="lp-status-pill lp-status-pill--warn"><span class="lp-status-dot lp-status-dot--warn"></span>running</span>
            </div>
          </header>
        </div>
        <div class="ds-example-foot"><strong>.lp-app-header</strong><span>distinct from .lp-header (marketing)</span></div>
      </div>

      <div class="ds-example">
        <div class="ds-example-canvas" style="padding:18px;background:#1a0e14;">
          <div class="lp-banner lp-banner--ok" style="margin-right:8px;"><span class="lp-banner-dot"></span><div class="lp-banner-body"><span class="lp-banner-title">Manifest synced</span></div></div>
          <div class="lp-banner lp-banner--warn" style="margin-right:8px;"><span class="lp-banner-dot"></span><div class="lp-banner-body"><span>Segmentation in progress…</span></div></div>
          <div class="lp-banner lp-banner--err"><span class="lp-banner-dot"></span><div class="lp-banner-body"><span class="lp-banner-title">Segmentation failed</span><span class="lp-banner-detail">VLM gateway 504 · retry queued</span></div></div>
        </div>
        <div class="ds-example-foot"><strong>.lp-banner --ok / --warn / --err</strong><span>floating chrome over canvas</span></div>
      </div>

      <div class="ds-example">
        <div class="ds-example-canvas" style="padding:18px;background:#1a0e14;display:flex;flex-direction:column;gap:6px;">
          <div class="lp-objects-row"><span class="lp-objects-dot" style="background:#ff9d6f"></span><span class="lp-objects-label">beige curtain</span><span class="lp-objects-conf">86%</span><span class="lp-objects-iso">◉</span></div>
          <div class="lp-objects-row lp-objects-row--selected"><span class="lp-objects-dot" style="background:#8b5fa8"></span><span class="lp-objects-label">black office chair</span><span class="lp-objects-conf">92%</span><span class="lp-objects-iso lp-objects-iso--on">◉</span></div>
          <div class="lp-objects-row lp-objects-row--isolated"><span class="lp-objects-dot" style="background:#ffb347"></span><span class="lp-objects-label">white vertical trim molding</span><span class="lp-objects-conf">71%</span><span class="lp-objects-iso lp-objects-iso--on">◉</span></div>
        </div>
        <div class="ds-example-foot"><strong>.lp-objects-row</strong><span>--selected / --isolated modifiers</span></div>
      </div>

      <div class="ds-example">
        <div class="ds-example-canvas" style="padding:18px;background:#1a0e14;">
          <div class="lp-chat-shell" style="height:240px;">
            <div class="lp-chat-feed">
              <div class="lp-bubble lp-bubble--user">where's the closest plug?</div>
              <div class="lp-bubble lp-bubble--agent"><div class="lp-bubble-text"><span class="lp-bubble-serif">Behind you.</span>The black multi-outlet is mounted on the wall just past the office chair, about 1.4m from the camera.</div><div class="lp-bubble-meta">looked at 2 frames</div></div>
            </div>
            <div class="lp-chat-input--shell">
              <input class="lp-chat-input--field" placeholder="Ask about the scene…" />
              <button class="lp-chat-input--send"><span class="lp-chat-input--send-glyph">↵</span><span>Send</span></button>
            </div>
          </div>
        </div>
        <div class="ds-example-foot"><strong>.lp-chat-shell + .lp-bubble--agent::before + .lp-bubble-serif</strong><span>composed surface</span></div>
      </div>

      <div class="ds-example">
        <div class="ds-example-canvas" style="background:#1a0e14;height:140px;position:relative;">
          <div style="position:absolute;left:30%;top:40%;"><button class="lp-anno-pill"><span class="lp-anno-pill-dot" style="background:#ff9d6f"></span><span class="lp-anno-pill-id">#001</span><span>beige curtain</span><span class="lp-anno-pill-conf">86%</span></button></div>
          <div style="position:absolute;left:30%;top:75%;"><button class="lp-anno-pill lp-anno-pill--selected"><span class="lp-anno-pill-dot" style="background:#8b5fa8"></span><span class="lp-anno-pill-id">#003</span><span>black office chair</span><span class="lp-anno-pill-conf">92%</span></button></div>
          <div style="position:absolute;left:62%;top:55%;"><button class="lp-where-btn"><span class="lp-where"><span class="lp-where-pulse"></span></span><span>Where am I?</span></button></div>
        </div>
        <div class="ds-example-foot"><strong>.lp-anno-pill / .lp-where-btn</strong><span>3D-anchored billboards + locate CTA</span></div>
      </div>
    </section>

    <!-- 15 VOICE -->
    <section id="voice" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">15</span><h2 class="ds-section-title">Voice &amp; copy</h2></div>
      <table class="ds-table">
        <thead><tr><th>do</th><th>don't</th></tr></thead>
        <tbody>
          <tr><td>"Walk through your room."</td><td class="c-muted">"Experience next-gen 3D scanning."</td></tr>
          <tr><td>"~90s end-to-end · iPhone Safari"</td><td class="c-muted">"Lightning-fast cloud reconstruction."</td></tr>
          <tr><td>"manifest.json is the source of truth."</td><td class="c-muted">"Powered by our proprietary engine."</td></tr>
          <tr><td>Lowercase mono captions for telemetry.</td><td class="c-muted">Title-Case Marketing Headers.</td></tr>
          <tr><td>Numbers are tabular-nums, always.</td><td class="c-muted">Decorative variable-width digits.</td></tr>
        </tbody>
      </table>
    </section>

    <!-- 16 LAYOUT -->
    <section id="layout" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">16</span><h2 class="ds-section-title">Layout</h2></div>
      <p class="ds-section-sub">Page max-width <code>1200px</code>, gutter <code>28px</code>. Sections vertically pad <code>100px</code>. Two-column section bodies use <code>1.05fr / 1fr</code> (slightly wider left).</p>
      <pre class="ds-code"><span class="c-cmt">/* page shell */</span>
.lp-section {
  <span class="c-key">max-width</span>: <span class="c-num">1200px</span>;
  <span class="c-key">margin</span>: <span class="c-num">0</span> auto;
  <span class="c-key">padding</span>: <span class="c-num">100px</span> <span class="c-num">28px</span>;
}

<span class="c-cmt">/* section head */</span>
.lp-section-head {
  <span class="c-key">display</span>: <span class="c-str">flex</span>;
  <span class="c-key">flex-direction</span>: <span class="c-str">column</span>;
  <span class="c-key">align-items</span>: <span class="c-str">flex-start</span>;
  <span class="c-key">gap</span>: <span class="c-num">14px</span>;
  <span class="c-key">margin-bottom</span>: <span class="c-num">40px</span>;
  <span class="c-key">max-width</span>: <span class="c-num">780px</span>;
}</pre>
    </section>

    <!-- 17 TOKENS -->
    <section id="tokens" class="ds-section">
      <div class="ds-section-head"><span class="ds-section-id">17</span><h2 class="ds-section-title">Tokens (full)</h2></div>
      <p class="ds-section-sub">Drop into <code>web/app/styles/tokens.css</code>. The existing Tailwind config can keep the same key names — just point them at these CSS variables.</p>
      <pre class="ds-code"><span class="c-key">:root</span> {
  <span class="c-cmt">/* color · ink */</span>
  <span class="c-key">--ink-950</span>: <span class="c-str">#1a0e14</span>;
  <span class="c-key">--ink-900</span>: <span class="c-str">#261520</span>;
  <span class="c-key">--ink-800</span>: <span class="c-str">#36202c</span>;
  <span class="c-key">--ink-700</span>: <span class="c-str">#4d2f3a</span>;
  <span class="c-key">--ink-600</span>: <span class="c-str">#6d4651</span>;
  <span class="c-key">--ink-500</span>: <span class="c-str">#94656a</span>;
  <span class="c-key">--ink-400</span>: <span class="c-str">#c08a83</span>;
  <span class="c-key">--ink-300</span>: <span class="c-str">#e6b9a3</span>;
  <span class="c-key">--ink-200</span>: <span class="c-str">#f4dcc6</span>;
  <span class="c-key">--ink-100</span>: <span class="c-str">#fdeede</span>;

  <span class="c-cmt">/* color · accent */</span>
  <span class="c-key">--accent-500</span>: <span class="c-str">#ff6b4a</span>;
  <span class="c-key">--accent-400</span>: <span class="c-str">#ff9d6f</span>;
  <span class="c-key">--accent-300</span>: <span class="c-str">#ffd29c</span>;

  <span class="c-cmt">/* color · single-purpose */</span>
  <span class="c-key">--hue-magenta</span>: <span class="c-str">#ff5d8f</span>;
  <span class="c-key">--hue-amber</span>:   <span class="c-str">#ffb347</span>;
  <span class="c-key">--hue-violet</span>:  <span class="c-str">#8b5fa8</span>;
  <span class="c-key">--emerald</span>:     <span class="c-str">#4ec9b0</span>;

  <span class="c-cmt">/* type */</span>
  <span class="c-key">--font-sans</span>:  <span class="c-str">"Inter"</span>, ui-sans-serif, system-ui;
  <span class="c-key">--font-serif</span>: <span class="c-str">"Fraunces"</span>, serif;
  <span class="c-key">--font-mono</span>:  ui-monospace, SFMono-Regular, Menlo;

  <span class="c-cmt">/* radius */</span>
  <span class="c-key">--r-xs</span>: <span class="c-num">4px</span>;  <span class="c-key">--r-sm</span>: <span class="c-num">6px</span>;
  <span class="c-key">--r-md</span>: <span class="c-num">10px</span>; <span class="c-key">--r-lg</span>: <span class="c-num">14px</span>;
  <span class="c-key">--r-xl</span>: <span class="c-num">22px</span>; <span class="c-key">--r-full</span>: <span class="c-num">999px</span>;

  <span class="c-cmt">/* motion */</span>
  <span class="c-key">--motion-fast</span>: <span class="c-num">120ms</span> ease;
  <span class="c-key">--motion-base</span>: <span class="c-num">200ms</span> cubic-bezier(.2,.8,.2,1);
  <span class="c-key">--motion-slow</span>: <span class="c-num">2200ms</span> ease-in-out;
}</pre>
      <p class="ds-section-sub" style="margin-top:24px;">
        <strong>Handoff to Claude Code:</strong> point it at <code>landing/landing.css</code> + <code>landing/design-system.css</code> + this page. Every component class on the landing page (<code>.lp-*</code>) is the production API — port them verbatim into <code>web/app/components/*</code> as React components, keep the class names so existing scoped styles port cleanly.
      </p>
    </section>
  </main>
</div>
`;

export default function DesignSystemPage() {
  return <div dangerouslySetInnerHTML={{ __html: BODY }} />;
}
