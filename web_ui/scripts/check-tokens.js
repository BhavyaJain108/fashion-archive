#!/usr/bin/env node
// The design language is only a language if the stylesheets speak it.
//
// archive.css defines every colour, font size, tracking, weight and duration
// the UI is allowed to use, and its header spells out the rules. This script
// is what stops a feature stylesheet from quietly drifting back to literals —
// the way HighFashionPage.css did, to 144 of them, before the tokens existed.
//
// It reads every .css under src/ and fails on:
//   - a hex or rgb() colour anywhere but the :root block of archive.css
//   - a font-size in px (use --ar-fs-*)
//   - a letter-spacing in em (use --ar-track-*)
//   - a duration in a transition (use --ar-fast / --ar-base / --ar-slow)
//   - a font-weight other than 400, 600, 700
//   - a border-radius other than 0
//   - any box-shadow
//   - an odd pixel value in padding / gap / margin (1px is the one exception:
//     a hairline gap between two segments)
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'src');
const ROOT_FILE = path.join(SRC, 'shared', 'styles', 'archive.css');

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, out);
    else if (entry.name.endsWith('.css')) out.push(p);
  }
  return out;
}

// Strip comments so a rule quoted in prose doesn't trip the check.
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '));

const CHECKS = [
  ['hex colour', /#[0-9a-f]{3,8}\b/i],
  ['rgb colour', /rgba?\(/],
  ['px font-size', /font-size:\s*[0-9.]+px/],
  ['raw letter-spacing', /letter-spacing:\s*[0-9.]+em/],
  ['raw duration', /transition:[^;]*\b[0-9.]+m?s\b/],
  ['off-scale weight', /font-weight:\s*(?!400\b|600\b|700\b)[0-9]+/],
  ["radius", /border-radius:(?!\s*0\s*;)/],
  ['shadow', /box-shadow:/],
];
const SPACE = /(?:padding|gap|margin)[a-z-]*:\s*([^;]+)/g;

const failures = [];
for (const file of walk(SRC)) {
  let text = stripComments(fs.readFileSync(file, 'utf8'));
  if (file === ROOT_FILE) {
    // The :root block is where the literals are supposed to live.
    text = text.replace(/:root\s*\{[\s\S]*?\n\}/, (m) => m.replace(/[^\n]/g, ' '));
  }
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    for (const [name, re] of CHECKS) {
      if (re.test(line)) failures.push(`${path.relative(SRC, file)}:${i + 1}  ${name}:  ${line.trim()}`);
    }
    let m;
    SPACE.lastIndex = 0;
    while ((m = SPACE.exec(line))) {
      for (const px of m[1].match(/\b\d+px\b/g) || []) {
        const n = parseInt(px, 10);
        if (n !== 1 && n % 2 === 1) failures.push(`${path.relative(SRC, file)}:${i + 1}  odd spacing (${px}):  ${line.trim()}`);
      }
    }
  });
}

if (failures.length) {
  console.error(`check:tokens — ${failures.length} literal(s) outside the design language:\n`);
  for (const f of failures) console.error('  ' + f);
  console.error('\nUse the tokens in src/shared/styles/archive.css, or add one there.');
  process.exit(1);
}
console.log('check:tokens — every stylesheet speaks the token set.');
