#!/usr/bin/env node
// Asserts that archive.css was injected before the feature stylesheets.
//
// The .ar-* primitives and the feature classes collide at equal specificity,
// so whichever is written later into the bundle wins every tie. The import
// order in src/index.js is the only thing holding that, and it is the kind of
// line a tidy-up deletes. This turns a silent visual regression into a failed
// build.
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
  ['.ar-select', '.product-sort-select'],
];

let failed = false;

for (const bundle of bundles) {
  const css = fs.readFileSync(path.join(cssDir, bundle), 'utf8');
  for (const [primitive, feature] of PAIRS) {
    const a = css.indexOf(primitive);
    const b = css.indexOf(feature);
    if (a === -1 || b === -1) {
      console.error(
        `check:css — ${bundle}: could not find ${a === -1 ? primitive : feature}. ` +
        'If the class was renamed, update PAIRS in scripts/check-css-order.js.'
      );
      failed = true;
      continue;
    }
    if (a > b) {
      console.error(
        `check:css — ${bundle}: ${primitive} (byte ${a}) comes AFTER ` +
        `${feature} (byte ${b}). archive.css lost the cascade.\n` +
        '  Fix: in src/index.js, import the archive stylesheet BEFORE App.'
      );
      failed = true;
    } else {
      console.log(`check:css — ok: ${primitive} ${a} < ${feature} ${b}`);
    }
  }
}

process.exit(failed ? 1 : 0);
