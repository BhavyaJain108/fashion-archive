#!/usr/bin/env node
// Exports the design tokens in archive.css as W3C Design Tokens JSON
// (design/tokens.json), the format Figma's variable import and Tokens
// Studio read. The CSS is the source of truth; this file is derived from it,
// so a designer in Figma and a developer in CSS see the same names and
// values. `--check` exits 1 if design/tokens.json is stale — the build runs
// it, so the JSON cannot fall behind.
//
//   npm run tokens:export          rewrite design/tokens.json
//   node scripts/export-tokens.js --check
const fs = require('fs');
const path = require('path');

const CSS = path.join(__dirname, '..', 'src', 'shared', 'styles', 'archive.css');
const OUT = path.join(__dirname, '..', 'design', 'tokens.json');

const css = fs.readFileSync(CSS, 'utf8');
const root = css.match(/:root\s*\{([\s\S]*?)\n\}/);
if (!root) throw new Error('export-tokens: no :root block in archive.css');

// One token per line: `--ar-name: value;  /* description */`
const raw = [];
for (const line of root[1].split('\n')) {
  const m = line.match(/^\s*--ar-([a-z0-9-]+):\s*([^;]+);\s*(?:\/\*\s*(.*?)\s*\*\/)?/);
  if (m) raw.push({ name: m[1], value: m[2].trim(), description: m[3] || '' });
}

const ms = (s) => (s.endsWith('ms') ? s : `${Math.round(parseFloat(s) * 1000)}ms`);
const token = ($type, $value, $description) =>
  $description ? { $type, $value, $description } : { $type, $value };

const out = {
  $description: 'Fashion Archive design tokens. Generated from web_ui/src/shared/styles/archive.css by scripts/export-tokens.js — edit the CSS, not this file.',
  color: {}, font: { family: {}, size: {}, tracking: {}, lineHeight: {}, weight: {} },
  space: {}, size: {}, motion: {},
};

for (const t of raw) {
  const { name, value, description } = t;
  if (name === 'font') out.font.family.mono = token('fontFamily', value.split(',').map((f) => f.trim().replace(/^'|'$/g, '')), description);
  else if (name.startsWith('fs-')) out.font.size[name.slice(3)] = token('dimension', value, description);
  else if (name.startsWith('track-')) out.font.tracking[name.slice(6)] = token('dimension', value, description);
  else if (name.startsWith('lh-')) out.font.lineHeight[name.slice(3)] = token(/px$/.test(value) ? 'dimension' : 'number', /px$/.test(value) ? value : Number(value), description);
  else if (['fast', 'base', 'slow'].includes(name)) out.motion[name] = token('duration', ms(value), description);
  else if (['sidebar-w', 'topbar-h', 'statusbar-h', 'hairline', 'marker'].includes(name)) out.size[name] = token('dimension', value, description);
  else out.color[name] = token('color', value, description);
}

// The spacing scale and weights are rules in the CSS header, not variables
// (spacing is written as plain even pixels — see rule 7 and 8 there).
for (const n of [1, 2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 48]) {
  out.space[String(n)] = token('dimension', `${n}px`, n === 1 ? 'hairline gap only' : undefined);
}
out.font.weight = {
  text: token('fontWeight', 400, 'everything readable'),
  emphasis: token('fontWeight', 600, 'emphasis inside content'),
  selected: token('fontWeight', 700, 'the selected row or chip'),
};

const json = JSON.stringify(out, null, 2) + '\n';
if (process.argv.includes('--check')) {
  const current = fs.existsSync(OUT) ? fs.readFileSync(OUT, 'utf8') : '';
  if (current !== json) {
    console.error('export-tokens — design/tokens.json is stale. Run `npm run tokens:export` and commit it.');
    process.exit(1);
  }
  console.log('export-tokens — design/tokens.json matches archive.css.');
} else {
  fs.writeFileSync(OUT, json);
  const count = Object.values(out).filter((v) => typeof v === 'object').reduce((n, g) => n + JSON.stringify(g).split('"$value"').length - 1, 0);
  console.log(`export-tokens — wrote ${count} tokens to design/tokens.json`);
}
