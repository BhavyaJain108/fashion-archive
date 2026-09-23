#!/usr/bin/env node
// Asserts that the shared primitives were injected before the feature
// stylesheets that override them.
//
// The .ar-* primitives and the feature classes collide at equal specificity,
// so whichever is written later into the bundle wins every tie. Nothing but
// import order holds that — `import './shared/styles/archive.css'` above
// `import App` in src/index.js for the archive primitives, and the order of
// the imports inside a feature's own module for the rest — and both are the
// kind of line a tidy-up moves. This turns a silent visual regression into a
// failed build.
const fs = require('fs');
const path = require('path');

const cssDir = path.join(__dirname, '..', 'build', 'static', 'css');

if (!fs.existsSync(cssDir)) {
  console.error('check:css — no build/static/css. Run `npm run build` first.');
  process.exit(1);
}

const bundles = fs.readdirSync(cssDir).filter((f) => f.endsWith('.css'));
if (bundles.length === 0) {
  console.error('check:css — no .css file in build/static/css.');
  process.exit(1);
}

// Pairs of [primitive, feature class] that must not swap. The primitive is
// expected FIRST so the feature class wins the tie, which is the whole point:
// a page's own styling overrides the shared default.
const PAIRS = [
  ['.ar-btn', '.fav-remove'],
  ['.ar-input', '.shop-search'],
  // The star: SaveStar.css's primitive against the archive list's own rule
  // for it. `.ar-star.on` and `.hf2-collection-item .hf2-row-star` are both
  // (0,2,0) and both set `color`, so which of the two files is written later
  // decides what a star on a row looks like — the same tie as the pairs
  // above.
  //
  // Spelled as the descendant selector because that is the only form
  // HighFashionPage.css ever writes: `.hf2-row-star` alone has no rule
  // anywhere, and asking for one is how this check reports a class that was
  // renamed. The pair is (primitive, the feature rule that must win it),
  // which is what the two above are too.
  ['.ar-star', '.hf2-collection-item .hf2-row-star'],
];

// Find where a class's OWN rule starts, not where the name first appears.
//
// A plain indexOf is not good enough, and the .ar-btn pair proved it: the
// first `.ar-btn` in a broken bundle is `.fav-view-toggle .ar-btn`, a
// LibraryPage.css rule that sits ahead of LibraryPage.css's own .fav-remove.
// That made the pair compare one feature sheet against itself, so it printed
// ok with the cascade deliberately broken.
//
// After CRA's minification a rule the class owns begins right after `}` (end
// of the previous rule), `,` (another selector in the same rule), `{` (the
// opening of an @media block) or at byte 0. A descendant selector like
// `.fav-view-toggle .ar-btn` is preceded by a space and never matches. The
// trailing guard keeps `.ar-btn` from matching inside `.ar-btn-danger` while
// still allowing `.ar-btn{`, `.ar-btn:hover` and `.ar-btn.active`.
function ruleStart(css, cls) {
  const re = new RegExp(
    `(?:^|[}{;,])${cls.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w-])`,
    'g'
  );
  const m = re.exec(css);
  if (!m) return -1;
  // The match may include the preceding delimiter; point at the class itself.
  return m.index + (m[0].startsWith(cls) ? 0 : 1);
}

let failed = false;

for (const bundle of bundles) {
  const css = fs.readFileSync(path.join(cssDir, bundle), 'utf8');
  for (const [primitive, feature] of PAIRS) {
    const a = ruleStart(css, primitive);
    const b = ruleStart(css, feature);
    if (a === -1 || b === -1) {
      console.error(
        `check:css — ${bundle}: could not find a rule for ${a === -1 ? primitive : feature}. ` +
        'If the class was renamed or is only ever used as a descendant selector, ' +
        'update PAIRS in scripts/check-css-order.js.'
      );
      failed = true;
      continue;
    }
    if (a > b) {
      console.error(
        `check:css — ${bundle}: ${primitive} (byte ${a}) comes AFTER ` +
        `${feature} (byte ${b}). The primitive lost the cascade.\n` +
        '  Fix: whichever stylesheet defines the primitive must be imported\n' +
        '  first — `./shared/styles/archive.css` above `App` in src/index.js\n' +
        "  for the .ar-* primitives, or the component's import above the\n" +
        "  feature's own stylesheet inside the feature module."
      );
      failed = true;
    } else {
      console.log(`check:css — ok: ${primitive} ${a} < ${feature} ${b}`);
    }
  }
}

process.exit(failed ? 1 : 0);
