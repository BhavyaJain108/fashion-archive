import React, { useState } from 'react';
import './StyleguidePage.css';

// The design language, rendered. Every token in archive.css and every .ar-*
// primitive, in every state, with its name beside it. This is the page to
// look at after any change to a stylesheet, and the page to point at when
// asking "what does a button look like here".
//
// Values are read from the live stylesheet, not retyped: if a token changes,
// this page changes with it.

const COLOURS = [
  ['--ar-bg', 'page ground'],
  ['--ar-bg-sub', 'sidebars, strips, toolbars'],
  ['--ar-bg-sunk', 'wells: image placeholders, pressed hover'],
  ['--ar-line', 'hairline rules'],
  ['--ar-line-soft', 'rules inside a grouped block'],
  ['--ar-ink', 'selected / active'],
  ['--ar-ink-2', 'body'],
  ['--ar-ink-3', 'labels, counts, idle controls, placeholders — 4.5:1'],
  ['--ar-ink-4', 'disabled text, glyph-only controls, input borders — 3:1, never a word'],
  ['--ar-danger', 'destructive confirmation only'],
  ['--ar-wash', 'hover'],
  ['--ar-wash-strong', 'selected row'],
  ['--ar-scrim', 'behind a focused panel'],
  ['--ar-shield', 'over a loading video'],
];

const TYPE = [
  ['--ar-fs-micro', 'counts, timestamps, meta', 'AMIRI · 2024 · 42 LOOKS', 'label'],
  ['--ar-fs-label', 'section headers, facet labels', 'DESIGNERS', 'label'],
  ['--ar-fs-ui', 'buttons, inputs, chips, status', 'OPEN COLLECTION', 'ui'],
  ['--ar-fs-body', 'list rows, notes, readable text', 'Comme des Garçons', 'content'],
  ['--ar-fs-heading', 'the name at the top of a panel', 'Spring / Summer 2025', 'content'],
  ['--ar-fs-title', 'the one big thing on a page', 'Archive', 'content'],
];

const TRACK = [
  ['--ar-track-tight', 'a name that needs air', 'Maison Margiela'],
  ['--ar-track-ui', 'buttons, chips, inputs', 'SAVE TO ALBUM'],
  ['--ar-track-label', 'section headers, placeholders', 'RECENTLY SEEN'],
  ['--ar-track-wide', 'the wordmark', 'ARCHIVE'],
];

const LH = [
  ['--ar-lh-none', 'a glyph or a single-line control'],
  ['--ar-lh-ui', 'rows, labels, anything 9–12px'],
  ['--ar-lh-body', 'paragraphs, notes, the heading size'],
];

const GLYPHS = [
  ['→ ←', 'open / next, back / previous'],
  ['…', 'loading, or more available'],
  ['☆ ★', 'not saved / saved'],
  ['▾ ▴ ▸', 'expand, collapse, disclosure'],
  ['▶', 'play'],
  ['✕', 'close, clear'],
];

const SPACE = [2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 48];

const SIZES = [
  ['--ar-sidebar-w', 'sidebar width'],
  ['--ar-topbar-h', 'top bar height'],
  ['--ar-statusbar-h', 'status bar height'],
  ['--ar-hairline', 'every rule'],
  ['--ar-marker', 'left bar on a selected row'],
];

const MOTION = [
  ['--ar-fast', 'colour, hover'],
  ['--ar-base', 'borders, opacity'],
  ['--ar-slow', 'a panel sliding or resizing'],
];

const RULES = [
  'Black means selected or active. Nothing else is black.',
  'Colour means destructive. One hue, one control: confirming a delete.',
  'Uppercase + tracking is chrome. Content is sentence case, untracked.',
  'Hairlines separate. Nothing casts a shadow.',
  'Hover is a wash, not a colour.',
  'No radius. Ever.',
  'Sizes come off the scales. A feature stylesheet never writes a literal.',
  'Weight: 400 text, 600 emphasis, 700 selected.',
  'Motion is functional. Nothing bounces.',
  'Readable text meets WCAG AA. No word is ever ink-4. Keyboard focus is a 1px black outline.',
];

function tokenValue(name) {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function Section({ title, children }) {
  return (
    <section className="sg-section">
      <div className="ar-section-header">{title}</div>
      {children}
    </section>
  );
}

function Row({ name, note, children }) {
  return (
    <div className="sg-row">
      <div className="sg-cell">{children}</div>
      <code className="sg-name">{name}</code>
      <span className="sg-value">{tokenValue(name)}</span>
      <span className="sg-note">{note}</span>
    </div>
  );
}

export default function StyleguidePage() {
  const [seg, setSeg] = useState('single');
  const [chip, setChip] = useState('women');
  const [row, setRow] = useState(1);

  return (
    <div className="ar-page sg">
      <div className="sg-scroll ar-scroll">
        <header className="sg-head">
          <span className="sg-wordmark">ARCHIVE</span>
          <span className="sg-sub">DESIGN LANGUAGE</span>
          <span className="sg-sub sg-right">docs/design-language.md · design/tokens.json</span>
        </header>

        <Section title="Rules">
          <ol className="sg-rules">
            {RULES.map((r) => <li key={r}>{r}</li>)}
          </ol>
        </Section>

        <Section title="Colour">
          {COLOURS.map(([name, note]) => (
            <Row key={name} name={name} note={note}>
              <span className="sg-swatch" style={{ background: `var(${name})` }} />
            </Row>
          ))}
        </Section>

        <Section title="Type">
          {TYPE.map(([name, note, sample, kind]) => (
            <Row key={name} name={name} note={note}>
              <span className={`sg-type sg-type-${kind}`} style={{ fontSize: `var(${name})` }}>{sample}</span>
            </Row>
          ))}
        </Section>

        <Section title="Tracking">
          {TRACK.map(([name, note, sample]) => (
            <Row key={name} name={name} note={note}>
              <span className="sg-type sg-type-ui" style={{ letterSpacing: `var(${name})` }}>{sample}</span>
            </Row>
          ))}
        </Section>

        <Section title="Line height">
          {LH.map(([name, note]) => (
            <Row key={name} name={name} note={note}>
              <span className="sg-lh" style={{ lineHeight: `var(${name})` }}>Rick Owens<br />Spring 2025</span>
            </Row>
          ))}
        </Section>

        <Section title="Space">
          <div className="sg-note sg-lead">Padding, gap and margin are even pixels off this scale. 1px is allowed for a hairline gap. No odd numbers.</div>
          {SPACE.map((n) => (
            <div className="sg-row" key={n}>
              <div className="sg-cell"><span className="sg-bar" style={{ width: n }} /></div>
              <code className="sg-name">{n}px</code>
            </div>
          ))}
        </Section>

        <Section title="Size">
          {SIZES.map(([name, note]) => <Row key={name} name={name} note={note} />)}
        </Section>

        <Section title="Motion">
          {MOTION.map(([name, note]) => (
            <Row key={name} name={name} note={note}>
              <span className="sg-pulse" style={{ transitionDuration: `var(${name})` }} />
            </Row>
          ))}
          <div className="sg-note sg-lead">Hover a square to see its duration.</div>
        </Section>

        <Section title="Layout">
          <div className="sg-frame">
            <div className="sg-frame-top">ARCHIVE <span>COLLECTIONS · LIBRARY · MY BRANDS</span><i>topbar-h</i></div>
            <div className="sg-frame-mid">
              <div className="sg-frame-side">sidebar-w<br />bg-sub</div>
              <div className="sg-frame-main">content · bg</div>
            </div>
            <div className="sg-frame-status">status · where you are<i>statusbar-h</i></div>
          </div>
          <code className="sg-name">.ar-page &gt; .ar-content &gt; .ar-sidebar + main; .ar-status-bar — desktop only, body never scrolls</code>
        </Section>

        <Section title="Glyphs">
          <div className="sg-note sg-lead">There is no icon set. Controls are words; these characters are the whole glyph vocabulary.</div>
          {GLYPHS.map(([g, note]) => (
            <div className="sg-row" key={g}>
              <div className="sg-cell"><span className="sg-glyph">{g}</span></div>
              <code className="sg-name">{g}</code>
              <span className="sg-value" />
              <span className="sg-note">{note}</span>
            </div>
          ))}
        </Section>

        <Section title="Focus">
          <div className="sg-demo sg-inline">
            <button className="ar-btn">Tab to me</button>
            <input className="ar-input sg-narrow" placeholder="Then here" />
            <button className="ar-star" aria-label="Save">☆</button>
          </div>
          <code className="sg-name">:focus-visible — 1px ink outline, inset, on everything; mouse focus shows nothing</code>
        </Section>

        <Section title="Section header">
          <div className="sg-demo sg-demo-sidebar">
            <div className="ar-section-header">Designers <span className="count">1,204</span></div>
          </div>
          <code className="sg-name">.ar-section-header  .count</code>
        </Section>

        <Section title="List rows">
          <div className="sg-demo sg-demo-sidebar">
            {['Acne Studios', 'Comme des Garçons', 'Maison Margiela'].map((name, i) => (
              <div key={name} className={`ar-list-item ${row === i ? 'selected' : ''}`} onClick={() => setRow(i)}>{name}</div>
            ))}
          </div>
          <code className="sg-name">.ar-list-item  .selected  (click to select; hover for the wash)</code>
        </Section>

        <Section title="Chips">
          <div className="sg-demo sg-demo-sidebar sg-chips">
            {['women', 'men', 'couture'].map((c) => (
              <button key={c} className={`ar-chip ${chip === c ? 'selected' : ''}`} onClick={() => setChip(c)}>{c}</button>
            ))}
          </div>
          <code className="sg-name">.ar-chip  .selected  — modes that stack in a sidebar</code>
        </Section>

        <Section title="Segmented">
          <div className="sg-demo">
            <div className="ar-segmented">
              {['single', 'grid'].map((m) => (
                <button key={m} className={`ar-segment ${seg === m ? 'selected' : ''}`} onClick={() => setSeg(m)}>{m}</button>
              ))}
            </div>
          </div>
          <code className="sg-name">.ar-segmented &gt; .ar-segment  .selected  — one of N views, side by side</code>
        </Section>

        <Section title="Buttons">
          <div className="sg-demo sg-inline">
            <button className="ar-btn">Idle</button>
            <button className="ar-btn active">Active</button>
            <button className="ar-btn" disabled>Disabled</button>
            <button className="ar-btn ar-btn-danger">Remove from library</button>
          </div>
          <div className="sg-demo sg-demo-sidebar">
            <button className="ar-btn ar-btn-block">Block</button>
          </div>
          <code className="sg-name">.ar-btn  .active  :disabled  .ar-btn-danger  .ar-btn-block</code>
        </Section>

        <Section title="Fields">
          <div className="sg-demo sg-demo-sidebar sg-stack">
            <input className="ar-input" placeholder="Search designers" />
            <input className="ar-input" defaultValue="Rick Owens" />
            <select className="ar-select" defaultValue="year">
              <option value="year">Year</option>
              <option value="season">Season</option>
            </select>
          </div>
          <code className="sg-name">.ar-input  ::placeholder  :focus  .ar-select</code>
        </Section>

        <Section title="Star">
          <div className="sg-demo sg-inline">
            <button className="ar-star" aria-label="Save">☆</button>
            <button className="ar-star on" aria-label="Saved">★</button>
            <button className="ar-star sm" aria-label="Save">☆</button>
            <button className="ar-star sm on" aria-label="Saved">★</button>
          </div>
          <code className="sg-name">.ar-star  .on  .sm  — saving is starring; there is no other save control</code>
        </Section>

        <Section title="Status bar">
          <div className="sg-demo">
            <div className="ar-status-bar">
              <span><span className="active">Acne Studios</span> · Spring 2025 · 12 / 48</span>
              <span>LOADED</span>
            </div>
          </div>
          <code className="sg-name">.ar-status-bar  .active</code>
        </Section>

        <Section title="Empty and loading">
          <div className="sg-demo sg-inline sg-tall">
            <div className="ar-empty"><span className="headline">Nothing saved yet</span><span>Star a look to keep it.</span></div>
            <div className="ar-loading"><span className="headline">Loading archive</span></div>
          </div>
          <code className="sg-name">.ar-empty  .ar-loading  .headline</code>
        </Section>

        <Section title="Component map">
          <div className="sg-note sg-lead">Each page owns a stylesheet and a prefix. Anything used on two pages becomes .ar-* and lands on this page.</div>
          {[
            ['hf2-', 'High Fashion', 'designer nav · collections · search · facets · recents drawer · viewer · grid · video · status'],
            ['lib- fav-', 'Library', 'kinds · albums · saved looks · saved shows'],
            ['alb-', 'Album', 'grid tiles · freeform canvas · layout toggle · filter'],
            ['brand- product- detail-', 'My Brands', 'brand nav · product tiles · detail panel · carousel'],
            ['shv-', 'Shared view', 'public album or look'],
            ['topbar- alp- share-', 'Shared UI', 'top bar · album picker · share button'],
          ].map(([prefix, page, parts]) => (
            <div className="sg-row" key={prefix}>
              <div className="sg-cell"><span className="sg-type">{page}</span></div>
              <code className="sg-name">{prefix}</code>
              <span className="sg-value" />
              <span className="sg-note">{parts}</span>
            </div>
          ))}
        </Section>

        <Section title="Scrollbar">
          <div className="sg-demo sg-demo-sidebar">
            <div className="ar-scroll sg-scrollbox">
              {Array.from({ length: 20 }, (_, i) => <div key={i} className="ar-list-item">Row {i + 1}</div>)}
            </div>
          </div>
          <code className="sg-name">.ar-scroll  — 6px thumb, no track, square</code>
        </Section>
      </div>
    </div>
  );
}
