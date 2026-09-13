# Phase 1: Restructure and Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganise `web_ui/src` into feature folders and make the browser's back and forward buttons work, with no other user-visible change.

**Architecture:** A pure URL-to-state module (`app/routes.js`) with no browser dependency, wrapped by a thin history binding (`app/router.js`) and consumed through one hook (`shared/hooks/useRoute.js`). The three page components move into `features/`, shared machinery into `shared/`, and `HighFashionV2.js` comes apart into eight files that compose back into `HighFashionPage`.

**Tech Stack:** React 18, Create React App (`react-scripts` 5), plain CSS with custom properties, Jest (bundled with react-scripts — no new dependencies).

## Global Constraints

- **No new npm dependencies.** Not for routing, not for testing. Jest runs pure-JS tests out of the box; this was verified.
- **`archive.css` must be injected before every feature stylesheet.** `.ar-*` primitives and feature classes collide at equal specificity; last one loaded wins. This broke production once. `src/index.js` must import `./shared/styles/archive.css` BEFORE `import App`.
- **Behaviour must not change in this phase** except that back/forward work. Any visual difference is a bug.
- **`removeFavourite(seasonUrl, collectionUrl, lookNumber)` is positional.** Reordering those three arguments silently deletes the wrong favourite. Do not touch that call site in this phase.
- **Commit after every task.** Never use `--no-verify`.
- **Run from `web_ui/`** unless a step says otherwise.
- Node 20.19.6, npm 11.7.0. `node_modules` is already installed.

## File Structure

| Path | Responsibility |
|---|---|
| `src/app/routes.js` | Pure: parse a URL into a route object, build a URL from one. No browser APIs. |
| `src/app/router.js` | Binds `routes.js` to `history.pushState` and `popstate`. Single subscriber list. |
| `src/app/App.js` | Auth gate; renders the page the current route names. |
| `src/shared/hooks/useRoute.js` | React binding for `router.js`. |
| `src/shared/api/client.js` | `BASE_URL`, fetch wrapper, 401 handling, SSE reader. |
| `src/shared/api/archive.js` | High Fashion endpoints. |
| `src/shared/api/brands.js` | My Brands endpoints (was `ArchiveAPI`). |
| `src/shared/api/saves.js` | Favourites and recents. |
| `src/shared/lib/designerSearch.js` | Moved unchanged. |
| `src/shared/ui/TopBar.js` | Moved unchanged. |
| `src/shared/styles/archive.css` | Moved unchanged. |
| `src/features/high-fashion/HighFashionPage.js` | Composition and the state that spans children. |
| `src/features/high-fashion/Filters.js` | Search box and facets. |
| `src/features/high-fashion/ShowList.js` | The collections list and its paging. |
| `src/features/high-fashion/Viewer.js` | Single and grid image modes. |
| `src/features/high-fashion/ThumbStrip.js` | The thumbnail strip and its centring. |
| `src/features/high-fashion/StatusBar.js` | The bottom readout. |
| `src/features/high-fashion/VideoPanel.js` | The YouTube panel and its controls. |
| `src/features/brands/BrandsPage.js` | Was `MyBrandsPanel`. |
| `src/features/brands/ProductDetailPanel.js` | Moved unchanged. |
| `src/features/library/LibraryPage.js` | Was `FavouritesPanel`. |
| `src/features/auth/*` | Moved unchanged. |
| `scripts/check-css-order.js` | Fails the build if `archive.css` loses the cascade. |

---

### Task 1: The CSS cascade guard

This runs first because every later task can break the cascade and nothing else
will notice. It is a real regression: the My Brands sort dropdown once expanded
to the full toolbar and the search field collapsed to about 26 pixels, because
`import App` preceded `import './styles/archive.css'`.

**Files:**
- Create: `web_ui/scripts/check-css-order.js`
- Modify: `web_ui/package.json` (scripts block)

**Interfaces:**
- Consumes: nothing.
- Produces: `npm run check:css` — exits 0 when `.ar-btn` appears before `.fav-remove` in the built CSS bundle, exits 1 with a diagnostic otherwise. Every later task runs it.

- [ ] **Step 1: Write the guard script**

Create `web_ui/scripts/check-css-order.js`:

```javascript
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
```

- [ ] **Step 2: Add the npm script**

In `web_ui/package.json`, the `scripts` block becomes:

```json
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test",
    "check:css": "node scripts/check-css-order.js"
  },
```

- [ ] **Step 3: Build and verify the guard passes on the current tree**

```bash
cd web_ui && npm run build && npm run check:css
```

Expected: two `check:css — ok:` lines, exit 0.

- [ ] **Step 4: Prove the guard actually catches the regression**

Temporarily break the order in `src/index.js` by moving the stylesheet import below `import App`:

```bash
cd web_ui
cp src/index.js /tmp/index.js.bak
cat > src/index.js <<'EOF'
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/archive.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<React.StrictMode><App /></React.StrictMode>);
EOF
npm run build >/dev/null 2>&1 && npm run check:css; echo "exit=$?"
cp /tmp/index.js.bak src/index.js
```

Expected: `archive.css lost the cascade.` and `exit=1`.

If it exits 0, the guard is useless — stop and fix it before continuing.

- [ ] **Step 5: Restore and confirm green**

```bash
cd web_ui && npm run build && npm run check:css; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 6: Commit**

```bash
git add web_ui/scripts/check-css-order.js web_ui/package.json
git commit -m "build(web): fail the build when archive.css loses the cascade

The .ar-* primitives and the feature classes tie on specificity, so the
import order in index.js decides which wins. That order is one uncommented
line, and deleting it once shipped a sort dropdown the width of the toolbar
and a 26px search field. A byte-offset check in the built bundle turns that
back into a build failure.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `app/routes.js` — pure URL to state

**Files:**
- Create: `web_ui/src/app/routes.js`
- Test: `web_ui/src/app/routes.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parseRoute(pathname: string, search: string) -> Route`
  - `buildRoute(route: Route) -> string` (a path with query string, e.g. `/hf/gucci-fw-2024/3/12?year=2024`)
  - `slugify(...parts: string[]) -> string`
  - `Route` is `{ page, collectionId, imageNumber, brandId, category, albumId, token, filters }` where `page` is one of `'high-fashion' | 'brands' | 'library' | 'album' | 'shared'`. Missing values are `null`; `filters` is always an object.
  - `FILTER_KEYS` — the exact filter names carried in the query string.

- [ ] **Step 1: Write the failing tests**

Create `web_ui/src/app/routes.test.js`:

```javascript
import { parseRoute, buildRoute, slugify, FILTER_KEYS } from './routes';

describe('slugify', () => {
  test('lowercases and hyphenates', () => {
    expect(slugify('Alexander McQueen')).toBe('alexander-mcqueen');
  });

  test('drops punctuation rather than encoding it', () => {
    expect(slugify("Alessandro Dell' Acqua")).toBe('alessandro-dell-acqua');
  });

  test('joins parts and collapses runs of separators', () => {
    expect(slugify('Comme des Garçons', 'Fall / Winter', 2000, 'Women'))
      .toBe('comme-des-garcons-fall-winter-2000-women');
  });

  test('survives empty and nullish parts', () => {
    expect(slugify('Gucci', '', null, undefined, 2024)).toBe('gucci-2024');
  });

  test('never returns an empty string', () => {
    expect(slugify('', null)).toBe('show');
  });
});

describe('parseRoute', () => {
  test('bare root is high fashion with nothing open', () => {
    expect(parseRoute('/', '')).toEqual({
      page: 'high-fashion',
      collectionId: null,
      imageNumber: null,
      brandId: null,
      category: null,
      albumId: null,
      token: null,
      filters: {},
    });
  });

  test('reads the collection id from the segment after the slug', () => {
    const r = parseRoute('/hf/alexander-mcqueen-fw-2000-women/3', '');
    expect(r.page).toBe('high-fashion');
    expect(r.collectionId).toBe('3');
    expect(r.imageNumber).toBe(null);
  });

  test('reads the image number', () => {
    const r = parseRoute('/hf/gucci-fw-2024/1234/12', '');
    expect(r.collectionId).toBe('1234');
    expect(r.imageNumber).toBe(12);
  });

  // The slug is decoration. A stale or hand-edited one must still open the
  // right show, which is the entire reason the id is a separate segment.
  test('ignores the slug entirely', () => {
    const a = parseRoute('/hf/gucci-fw-2024/1234/12', '');
    const b = parseRoute('/hf/total-nonsense/1234/12', '');
    expect(a).toEqual(b);
  });

  test('a non-numeric collection id is rejected, not passed through', () => {
    const r = parseRoute('/hf/gucci/not-an-id', '');
    expect(r.collectionId).toBe(null);
  });

  test('a non-numeric image number is rejected', () => {
    const r = parseRoute('/hf/gucci/1234/abc', '');
    expect(r.collectionId).toBe('1234');
    expect(r.imageNumber).toBe(null);
  });

  test('brands with and without a category', () => {
    expect(parseRoute('/brands', '').page).toBe('brands');
    expect(parseRoute('/brands/acne', '').brandId).toBe('acne');
    const r = parseRoute('/brands/acne/knitwear', '');
    expect(r.brandId).toBe('acne');
    expect(r.category).toBe('knitwear');
  });

  test('a category with slashes survives encoding', () => {
    const r = parseRoute('/brands/acne/' + encodeURIComponent('men/knitwear'), '');
    expect(r.category).toBe('men/knitwear');
  });

  test('library and one album', () => {
    expect(parseRoute('/library', '').page).toBe('library');
    const r = parseRoute('/library/albums/7', '');
    expect(r.page).toBe('album');
    expect(r.albumId).toBe('7');
  });

  test('a share token', () => {
    const r = parseRoute('/s/AbC123', '');
    expect(r.page).toBe('shared');
    expect(r.token).toBe('AbC123');
  });

  test('an unknown path falls back to high fashion', () => {
    expect(parseRoute('/nonsense/deep/path', '').page).toBe('high-fashion');
  });

  test('filters come out of the query string', () => {
    const r = parseRoute('/', '?year=2024&season=Fall+%2F+Winter&city=Paris');
    expect(r.filters).toEqual({
      year: '2024',
      season: 'Fall / Winter',
      city: 'Paris',
    });
  });

  // Auth params share the query string with filters and must not leak in.
  test('non-filter query params are dropped', () => {
    const r = parseRoute('/', '?year=2024&token=secret&verified=1&junk=x');
    expect(r.filters).toEqual({ year: '2024' });
  });

  test('empty filter values are dropped', () => {
    expect(parseRoute('/', '?year=&season=Resort').filters).toEqual({ season: 'Resort' });
  });
});

describe('buildRoute', () => {
  test('high fashion with nothing open is the root', () => {
    expect(buildRoute({ page: 'high-fashion' })).toBe('/');
  });

  test('a show, with a slug supplied by the caller', () => {
    expect(buildRoute({
      page: 'high-fashion',
      slug: 'gucci-fw-2024',
      collectionId: '1234',
    })).toBe('/hf/gucci-fw-2024/1234');
  });

  test('a show at an image', () => {
    expect(buildRoute({
      page: 'high-fashion',
      slug: 'gucci-fw-2024',
      collectionId: '1234',
      imageNumber: 12,
    })).toBe('/hf/gucci-fw-2024/1234/12');
  });

  test('a missing slug gets a placeholder rather than an empty segment', () => {
    expect(buildRoute({ page: 'high-fashion', collectionId: '1234' }))
      .toBe('/hf/show/1234');
  });

  test('brands', () => {
    expect(buildRoute({ page: 'brands' })).toBe('/brands');
    expect(buildRoute({ page: 'brands', brandId: 'acne' })).toBe('/brands/acne');
    expect(buildRoute({ page: 'brands', brandId: 'acne', category: 'men/knitwear' }))
      .toBe('/brands/acne/men%2Fknitwear');
  });

  test('library and album', () => {
    expect(buildRoute({ page: 'library' })).toBe('/library');
    expect(buildRoute({ page: 'album', albumId: '7' })).toBe('/library/albums/7');
  });

  test('share', () => {
    expect(buildRoute({ page: 'shared', token: 'AbC123' })).toBe('/s/AbC123');
  });

  test('filters become a sorted query string', () => {
    const url = buildRoute({
      page: 'high-fashion',
      filters: { year: '2024', city: 'Paris' },
    });
    expect(url).toBe('/?city=Paris&year=2024');
  });

  test('empty filter values are omitted', () => {
    expect(buildRoute({ page: 'high-fashion', filters: { year: '', city: 'Paris' } }))
      .toBe('/?city=Paris');
  });

  test('unknown filter keys are omitted', () => {
    expect(buildRoute({ page: 'high-fashion', filters: { year: '2024', evil: 'x' } }))
      .toBe('/?year=2024');
  });
});

describe('round trip', () => {
  test.each([
    '/',
    '/?city=Paris&year=2024',
    '/hf/gucci-fw-2024/1234',
    '/hf/gucci-fw-2024/1234/12',
    '/brands',
    '/brands/acne',
    '/library',
    '/library/albums/7',
    '/s/AbC123',
  ])('%s survives parse then build', (url) => {
    const [pathname, search] = url.split('?');
    const route = parseRoute(pathname, search ? `?${search}` : '');
    // The slug is not recoverable from a parse (it is decoration), so feed
    // back the one the URL carried.
    const slug = pathname.startsWith('/hf/') ? pathname.split('/')[2] : undefined;
    expect(buildRoute({ ...route, slug })).toBe(url);
  });
});

describe('FILTER_KEYS', () => {
  // These must match the filter state in HighFashionPage exactly. A key
  // missing here is a filter that silently will not survive a reload.
  test('covers every filter the archive has', () => {
    expect([...FILTER_KEYS].sort()).toEqual([
      'category', 'city', 'gender', 'letter', 'season', 'shootType', 'year',
    ]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web_ui && CI=true npx react-scripts test --watchAll=false --testPathPattern="routes" 2>&1 | tail -20
```

Expected: FAIL — `Cannot find module './routes'`.

- [ ] **Step 3: Write the implementation**

Create `web_ui/src/app/routes.js`:

```javascript
// URL to state, and back. No browser APIs in this file — everything here is a
// pure function of two strings, which is why it can be tested without a DOM.
//
// The shape of a show URL is /hf/<slug>/<collectionId>[/<imageNumber>].
// The slug is decoration built from the designer and season so the link reads
// like something; it is never parsed. The collection id is firstVIEW's own id
// and is the only authoritative part, which means a renamed designer or a
// hand-edited slug still opens the right show.

// The filters that ride in the query string. Anything not named here is
// dropped on the way in and refused on the way out — the query string is
// shared with auth parameters (token, verified, error) that must never be
// mistaken for archive state.
export const FILTER_KEYS = new Set([
  'gender', 'year', 'season', 'category', 'shootType', 'city', 'letter',
]);

const EMPTY = {
  page: 'high-fashion',
  collectionId: null,
  imageNumber: null,
  brandId: null,
  category: null,
  albumId: null,
  token: null,
  filters: {},
};

// Latin-1 accents folded rather than percent-encoded, so "Comme des Garçons"
// reads as text in the address bar instead of as %C3%A7.
const fold = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');

export function slugify(...parts) {
  const slug = parts
    .filter((p) => p !== null && p !== undefined && String(p).length > 0)
    .map((p) => fold(String(p)).toLowerCase())
    .join('-')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  // An empty segment would make /hf//1234, which parses as a different shape.
  return slug || 'show';
}

const readFilters = (search) => {
  const out = {};
  const params = new URLSearchParams(search || '');
  for (const [key, value] of params.entries()) {
    if (FILTER_KEYS.has(key) && value !== '') out[key] = value;
  }
  return out;
};

// A collection id is firstVIEW's, which is a bare integer. Anything else is
// somebody's guess at a URL and is treated as "no show open" rather than
// handed to the API.
const asCollectionId = (raw) => (/^\d+$/.test(raw || '') ? raw : null);
const asImageNumber = (raw) => (/^\d+$/.test(raw || '') ? parseInt(raw, 10) : null);

export function parseRoute(pathname, search) {
  const filters = readFilters(search);
  const segments = (pathname || '/').split('/').filter(Boolean).map(decodeURIComponent);

  if (segments.length === 0) return { ...EMPTY, filters };

  const [head, ...rest] = segments;

  if (head === 'hf') {
    // rest = [slug, collectionId, imageNumber?]
    const collectionId = asCollectionId(rest[1]);
    return {
      ...EMPTY,
      filters,
      collectionId,
      imageNumber: collectionId ? asImageNumber(rest[2]) : null,
    };
  }

  if (head === 'brands') {
    return {
      ...EMPTY,
      filters,
      page: 'brands',
      brandId: rest[0] || null,
      category: rest[1] || null,
    };
  }

  if (head === 'library') {
    if (rest[0] === 'albums' && rest[1]) {
      return { ...EMPTY, filters, page: 'album', albumId: rest[1] };
    }
    return { ...EMPTY, filters, page: 'library' };
  }

  if (head === 's' && rest[0]) {
    return { ...EMPTY, filters, page: 'shared', token: rest[0] };
  }

  // Anything unrecognised opens the archive rather than a 404 screen. There is
  // nothing behind a bad URL worth a page of its own.
  return { ...EMPTY, filters };
}

const query = (filters) => {
  const params = new URLSearchParams();
  // Sorted so the same state always produces the same string — otherwise
  // pushState records a "change" every time a filter object is rebuilt.
  for (const key of Object.keys(filters || {}).sort()) {
    if (FILTER_KEYS.has(key) && filters[key]) params.set(key, filters[key]);
  }
  const s = params.toString();
  return s ? `?${s}` : '';
};

export function buildRoute(route) {
  const r = route || {};
  const q = query(r.filters);

  if (r.page === 'brands') {
    const parts = ['/brands'];
    if (r.brandId) parts.push(encodeURIComponent(r.brandId));
    if (r.brandId && r.category) parts.push(encodeURIComponent(r.category));
    return parts.join('/') + q;
  }

  if (r.page === 'album' && r.albumId) {
    return `/library/albums/${encodeURIComponent(r.albumId)}${q}`;
  }

  if (r.page === 'library') return `/library${q}`;

  if (r.page === 'shared' && r.token) {
    return `/s/${encodeURIComponent(r.token)}${q}`;
  }

  if (r.collectionId) {
    const slug = r.slug || 'show';
    const tail = r.imageNumber ? `/${r.imageNumber}` : '';
    return `/hf/${slug}/${r.collectionId}${tail}${q}`;
  }

  return `/${q}`;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd web_ui && CI=true npx react-scripts test --watchAll=false --testPathPattern="routes" 2>&1 | tail -20
```

Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add web_ui/src/app/routes.js web_ui/src/app/routes.test.js
git commit -m "feat(web): the URL, as a pure function

parseRoute and buildRoute know nothing about the browser, which is what
makes them testable without a DOM and what keeps the history binding in the
next commit down to about forty lines.

The collection id is a separate segment from the readable slug because
firstVIEW's id is a bare integer and cannot be recovered from a designer
name. A stale slug still opens the right show.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `app/router.js` and `useRoute`

**Files:**
- Create: `web_ui/src/app/router.js`
- Create: `web_ui/src/shared/hooks/useRoute.js`
- Test: `web_ui/src/app/router.test.js`

**Interfaces:**
- Consumes: `parseRoute`, `buildRoute` from `app/routes.js`.
- Produces:
  - `getRoute() -> Route` — the route the address bar currently describes.
  - `navigate(route, { replace = false } = {})` — writes the URL and notifies subscribers. A no-op when the built URL equals the current one, so repeated renders do not stack history entries.
  - `subscribe(fn) -> unsubscribe` — `fn(route)` on every `popstate` and every `navigate`.
  - `useRoute() -> [route, navigate]` — the React binding.

- [ ] **Step 1: Write the failing tests**

Create `web_ui/src/app/router.test.js`. Jest's default environment in CRA is
`jsdom`, so `window.history` exists and `pushState` works.

```javascript
import { getRoute, navigate, subscribe } from './router';

const at = (url) => window.history.replaceState({}, '', url);

beforeEach(() => at('/'));

describe('getRoute', () => {
  test('reads the current address', () => {
    at('/hf/gucci-fw-2024/1234/12');
    const r = getRoute();
    expect(r.page).toBe('high-fashion');
    expect(r.collectionId).toBe('1234');
    expect(r.imageNumber).toBe(12);
  });

  test('reads filters out of the query string', () => {
    at('/?year=2024&city=Paris');
    expect(getRoute().filters).toEqual({ year: '2024', city: 'Paris' });
  });
});

describe('navigate', () => {
  test('writes the address bar', () => {
    navigate({ page: 'brands', brandId: 'acne' });
    expect(window.location.pathname).toBe('/brands/acne');
  });

  test('pushes a history entry by default', () => {
    const before = window.history.length;
    navigate({ page: 'library' });
    expect(window.history.length).toBeGreaterThan(before);
  });

  test('replace: true does not push', () => {
    navigate({ page: 'library' });
    const before = window.history.length;
    navigate({ page: 'brands' }, { replace: true });
    expect(window.history.length).toBe(before);
    expect(window.location.pathname).toBe('/brands');
  });

  // Without this guard an effect that navigates on every render fills the
  // history stack and the back button stops working.
  test('navigating to the current URL is a no-op', () => {
    navigate({ page: 'brands', brandId: 'acne' });
    const before = window.history.length;
    navigate({ page: 'brands', brandId: 'acne' });
    navigate({ page: 'brands', brandId: 'acne' });
    expect(window.history.length).toBe(before);
  });

  test('notifies subscribers with the new route', () => {
    const seen = [];
    const off = subscribe((r) => seen.push(r));
    navigate({ page: 'library' });
    off();
    expect(seen).toHaveLength(1);
    expect(seen[0].page).toBe('library');
  });

  test('a no-op navigation does not notify', () => {
    navigate({ page: 'library' });
    const seen = [];
    const off = subscribe((r) => seen.push(r));
    navigate({ page: 'library' });
    off();
    expect(seen).toHaveLength(0);
  });
});

describe('subscribe', () => {
  test('fires on popstate', () => {
    const seen = [];
    const off = subscribe((r) => seen.push(r));
    at('/brands/acne');
    window.dispatchEvent(new PopStateEvent('popstate'));
    off();
    expect(seen).toHaveLength(1);
    expect(seen[0].brandId).toBe('acne');
  });

  test('unsubscribe stops delivery', () => {
    const seen = [];
    subscribe((r) => seen.push(r))();
    navigate({ page: 'library' });
    expect(seen).toHaveLength(0);
  });

  test('one subscriber throwing does not stop the others', () => {
    const seen = [];
    const offA = subscribe(() => { throw new Error('boom'); });
    const offB = subscribe((r) => seen.push(r));
    navigate({ page: 'library' });
    offA(); offB();
    expect(seen).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web_ui && CI=true npx react-scripts test --watchAll=false --testPathPattern="router" 2>&1 | tail -20
```

Expected: FAIL — `Cannot find module './router'`.

- [ ] **Step 3: Write `router.js`**

Create `web_ui/src/app/router.js`:

```javascript
// The only file in the app that touches window.history.
//
// There is no router dependency here on purpose: the whole surface is three
// functions, and a library would bring a component tree, a context, and its
// own opinions about where state lives — none of which this app needs.
import { parseRoute, buildRoute } from './routes';

const subscribers = new Set();

export function getRoute() {
  return parseRoute(window.location.pathname, window.location.search);
}

const notify = () => {
  const route = getRoute();
  for (const fn of subscribers) {
    try {
      fn(route);
    } catch (error) {
      // One bad subscriber must not strand the rest of the app on the wrong
      // URL — the address bar has already changed by this point.
      console.error('Route subscriber failed:', error);
    }
  }
};

export function navigate(route, { replace = false } = {}) {
  const url = buildRoute(route);
  const current = window.location.pathname + window.location.search;

  // An effect that navigates on every render would otherwise push an entry
  // per render and bury the user's actual history.
  if (url === current) return;

  if (replace) window.history.replaceState({}, '', url);
  else window.history.pushState({}, '', url);

  notify();
}

export function subscribe(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

// Back and forward. Registered once, at module load, for the life of the page.
window.addEventListener('popstate', notify);
```

- [ ] **Step 4: Write `useRoute.js`**

Create `web_ui/src/shared/hooks/useRoute.js`:

```javascript
import { useEffect, useState, useCallback } from 'react';
import { getRoute, navigate, subscribe } from '../../app/router';

// The React end of the router. Returns the current route and the same
// navigate every render, so it is safe in a dependency array.
export function useRoute() {
  const [route, setRoute] = useState(getRoute);

  useEffect(() => subscribe(setRoute), []);

  const go = useCallback((next, options) => navigate(next, options), []);

  return [route, go];
}

export default useRoute;
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd web_ui && CI=true npx react-scripts test --watchAll=false --testPathPattern="router" 2>&1 | tail -20
```

Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add web_ui/src/app/router.js web_ui/src/app/router.test.js web_ui/src/shared/hooks/useRoute.js
git commit -m "feat(web): bind the URL to history, and nothing else to it

Three functions and a Set of subscribers. No router dependency: the library
would bring a component tree and a context for a job this size, and every
piece of state it would hold already lives in the pages.

navigate refuses to push when the URL has not changed, because an effect
that navigates on render would otherwise bury the user's history one entry
per render and make Back do nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Split `services/api.js` into `shared/api/`

`services/api.js` is 559 lines holding two unrelated classes: `FashionArchiveAPI`
(auth, the high-fashion archive, favourites, recents) and `ArchiveAPI` (My
Brands). They share only `BASE_URL` and the 401 handler.

This is a move, not a rewrite. Method bodies are copied verbatim. The only
edits are the `class` wrappers, the imports, and `this.` becoming a module
reference where a method called a sibling.

**Files:**
- Create: `web_ui/src/shared/api/client.js`, `archive.js`, `brands.js`, `saves.js`, `index.js`
- Delete: `web_ui/src/services/api.js`
- Modify: every importer — `src/App.js`, `src/components/HighFashionV2.js`, `src/components/MyBrandsPanel.js`, `src/components/FavouritesPanel.js`, `src/components/ProductDetailPanel.js`, `src/auth/AuthPanel.js` (confirm the list with the grep in Step 1)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `shared/api/index.js` re-exports `FashionArchiveAPI` and `ArchiveAPI` under their existing names, so every call site changes its import path and nothing else.

- [ ] **Step 1: Find every importer**

```bash
cd web_ui && grep -rn "services/api" src --include="*.js"
```

Write the list down. Every one of these files changes in Step 4.

- [ ] **Step 2: Create the four modules**

Split `src/services/api.js` at these boundaries, copying bodies verbatim:

| New file | Takes from `api.js` |
|---|---|
| `shared/api/client.js` | `BASE_URL`, `onUnauthorized`, `checkAuth`, `authRequest`, `callPython`, `consumeSSE`, `getImageUrl`, and the auth methods (`getMe`, `login`, `register`, `logout`, `resendVerification`, `requestPasswordReset`, `resetPassword`) |
| `shared/api/archive.js` | `getSeasons`, `downloadVideo`, `streamCatalog`, `getIndexStatus`, `browseCatalog`, `searchShows`, `getDesigners`, `streamDesignerCollections`, `streamCollectionImages`, and the `_indexReady` / `_designerIndex` caches |
| `shared/api/saves.js` | `getRecents`, `getFavourites`, `addFavourite`, `removeFavourite`, `getFavouriteStats` |
| `shared/api/brands.js` | the whole `ArchiveAPI` class |

Keep them as classes with static methods — that is what every call site expects
and changing the shape is a second change riding on a move.

`client.js` holds the state the others need:

```javascript
// The shared half of the API: the base URL, the session-expiry hook, and the
// three request shapes every endpoint is built from.
//
// Every request sends credentials: 'include' so the browser attaches the
// session cookie. The cookie is HttpOnly, which means this file cannot read it
// and neither can anything else on the page — that is the point.
export class ApiClient {
  static BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8081';

  static onUnauthorized = null;

  static checkAuth(response) { /* verbatim from api.js */ }
  static async authRequest(path, body) { /* verbatim */ }
  static async callPython(endpoint, data = {}, opts = {}) { /* verbatim */ }
  static async consumeSSE(endpoint, body, onEvent, signal) { /* verbatim */ }
  static getImageUrl(imagePath) { /* verbatim */ }

  static async getMe() { /* verbatim */ }
  static login(email, password) { return this.authRequest('login', { email, password }); }
  static register(email, password, displayName) { /* verbatim */ }
  static logout() { return this.authRequest('logout', {}); }
  static resendVerification(email) { return this.authRequest('resend-verification', { email }); }
  static requestPasswordReset(email) { return this.authRequest('request-reset', { email }); }
  static resetPassword(token, password) { return this.authRequest('reset', { token, password }); }
}

export default ApiClient;
```

`archive.js`, `saves.js` and `brands.js` each start:

```javascript
import ApiClient from './client';
```

and call `ApiClient.callPython(...)` where the original called `this.callPython(...)`.

Note for `brands.js`: the original `ArchiveAPI.BASE_URL` is a getter delegating
to `FashionArchiveAPI.BASE_URL`. It becomes:

```javascript
  static get BASE_URL() {
    return ApiClient.BASE_URL;
  }
```

and `FashionArchiveAPI.checkAuth(response)` becomes `ApiClient.checkAuth(response)`.

- [ ] **Step 3: Write the compatibility surface**

Create `web_ui/src/shared/api/index.js`:

```javascript
// One import for call sites that want the old names.
//
// FashionArchiveAPI was a single class holding auth, the archive and
// favourites. It is three modules now; this composes them back into the name
// the pages already use, so splitting the file did not mean touching every
// call in the app on the same commit.
import ApiClient from './client';
import ArchiveEndpoints from './archive';
import SavesEndpoints from './saves';

export class FashionArchiveAPI {}

// Static inheritance by copy: every own property of the three modules lands on
// the facade, so FashionArchiveAPI.getSeasons and .addFavourite keep working.
for (const source of [ApiClient, ArchiveEndpoints, SavesEndpoints]) {
  for (const key of Object.getOwnPropertyNames(source)) {
    if (['length', 'name', 'prototype'].includes(key)) continue;
    Object.defineProperty(
      FashionArchiveAPI, key, Object.getOwnPropertyDescriptor(source, key)
    );
  }
}

// onUnauthorized is assigned by App.js on the facade, but the request helpers
// read it from ApiClient. Keep the two ends pointed at the same slot.
Object.defineProperty(FashionArchiveAPI, 'onUnauthorized', {
  get() { return ApiClient.onUnauthorized; },
  set(fn) { ApiClient.onUnauthorized = fn; },
  configurable: true,
});

export { default as ArchiveAPI } from './brands';
export { ApiClient };
export default FashionArchiveAPI;
```

- [ ] **Step 4: Repoint every importer**

For each file from Step 1, change the import path only:

```javascript
// was
import { FashionArchiveAPI } from '../services/api';
// becomes
import { FashionArchiveAPI } from '../shared/api';
```

Adjust `../` depth per file. `src/App.js` uses `./shared/api`.

- [ ] **Step 5: Delete the old file and confirm nothing references it**

```bash
cd web_ui && rm src/services/api.js && rmdir src/services 2>/dev/null
grep -rn "services/api" src --include="*.js"; echo "exit=$?"
```

Expected: no output, `exit=1` (grep found nothing).

- [ ] **Step 6: Build and check the cascade**

```bash
cd web_ui && npm run build && npm run check:css
```

Expected: build succeeds with no warnings about missing modules; `check:css` exits 0.

- [ ] **Step 7: Verify the facade actually resolves the methods**

This catches a mis-split — a method that landed in no module, or a `this.`
that still points at the old class.

```bash
cd web_ui && cat > /tmp/api-probe.test.js <<'EOF'
import { FashionArchiveAPI, ArchiveAPI } from '../../src/shared/api';

test('every method the pages call still resolves', () => {
  for (const name of [
    'getMe', 'login', 'register', 'logout', 'resendVerification',
    'requestPasswordReset', 'resetPassword', 'callPython', 'consumeSSE',
    'getImageUrl', 'getSeasons', 'downloadVideo', 'streamCatalog',
    'getIndexStatus', 'browseCatalog', 'searchShows', 'getDesigners',
    'streamDesignerCollections', 'streamCollectionImages', 'getRecents',
    'getFavourites', 'addFavourite', 'removeFavourite', 'getFavouriteStats',
  ]) {
    expect(typeof FashionArchiveAPI[name]).toBe('function');
  }
  for (const name of [
    'getBrands', 'getHierarchy', 'getCounts', 'getProducts',
    'searchProducts', 'health',
  ]) {
    expect(typeof ArchiveAPI[name]).toBe('function');
  }
});

test('onUnauthorized set on the facade reaches the client', () => {
  const fn = () => {};
  FashionArchiveAPI.onUnauthorized = fn;
  // eslint-disable-next-line global-require
  expect(require('../../src/shared/api/client').default.onUnauthorized).toBe(fn);
  FashionArchiveAPI.onUnauthorized = null;
});
EOF
mkdir -p src/shared/api/__tests__ && cp /tmp/api-probe.test.js src/shared/api/__tests__/facade.test.js
CI=true npx react-scripts test --watchAll=false --testPathPattern="facade" 2>&1 | tail -20
```

Expected: PASS. Keep this test — it is the only thing standing between a
mis-split and a runtime `undefined is not a function` on a page nobody opened.

- [ ] **Step 8: Commit**

```bash
git add -A web_ui/src
git commit -m "refactor(web): api.js was two unrelated services in one file

FashionArchiveAPI held auth, the archive and favourites; ArchiveAPI held My
Brands. They shared a base URL and a 401 handler and nothing else. Four
modules now, with a facade re-exporting the old names so this commit is a
move rather than 200 edited call sites.

The facade test is not ceremony: a method that lands in no module fails at
runtime, on whichever page nobody happened to open.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Move the shared machinery

Pure file moves. No content changes except import paths and one added comment.

**Files:**
- Move: `src/components/TopBar.js`, `TopBar.css` → `src/shared/ui/`
- Move: `src/lib/designerSearch.js` → `src/shared/lib/`
- Move: `src/styles/archive.css` → `src/shared/styles/`
- Move: `src/auth/*` → `src/features/auth/`
- Modify: `src/index.js`, and every importer of the above

**Interfaces:**
- Consumes: nothing.
- Produces: the import paths every later task uses — `shared/ui/TopBar`, `shared/lib/designerSearch`, `shared/styles/archive.css`, `features/auth/AuthPanel`.

- [ ] **Step 1: Move the files with git so history follows**

```bash
cd web_ui/src
mkdir -p shared/ui shared/lib shared/styles features/auth
git mv components/TopBar.js components/TopBar.css shared/ui/
git mv lib/designerSearch.js shared/lib/
git mv styles/archive.css shared/styles/
git mv auth/AuthPanel.js auth/AuthShell.js features/auth/
ls auth 2>/dev/null && echo "auth/ still has files — move them too"
rmdir auth lib styles 2>/dev/null
git status --short
```

- [ ] **Step 2: Rewrite `src/index.js`**

The comment is load-bearing documentation. Do not drop it.

```javascript
import React from 'react';
import ReactDOM from 'react-dom/client';

// This import MUST stay above `import App`.
//
// App transitively imports every feature stylesheet. The .ar-* primitives in
// archive.css and the feature classes collide at equal specificity, so
// whichever is injected last wins every tie. With App first, .ar-select beat
// .product-sort-select and the My Brands sort dropdown grew to the width of
// the toolbar while the search field collapsed to about 26 pixels.
//
// `npm run check:css` asserts this against the built bundle.
import './shared/styles/archive.css';
import App from './app/App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Note: `App` moves to `src/app/App.js` in this task. Move it with
`git mv src/App.js src/app/App.js` and fix its own relative imports — they all
gain one `../`.

- [ ] **Step 3: Fix every import that pointed at a moved file**

```bash
cd web_ui && grep -rn "components/TopBar\|lib/designerSearch\|styles/archive\|from './auth/\|from '../auth/" src --include="*.js"
```

Repoint each hit. Depth changes:
- `src/app/App.js` → `../features/auth/AuthPanel`, `../shared/api`
- `src/features/*/**.js` → `../../shared/ui/TopBar`, `../../shared/lib/designerSearch`, `../../shared/api`
- `src/features/auth/AuthPanel.js` → `../../shared/api`

- [ ] **Step 4: Build and check**

```bash
cd web_ui && npm run build && npm run check:css
```

Expected: build succeeds, `check:css` exits 0. A `Module not found` here means
a path in Step 3 was missed.

- [ ] **Step 5: Run the whole test suite**

```bash
cd web_ui && CI=true npx react-scripts test --watchAll=false 2>&1 | tail -15
```

Expected: all suites pass.

- [ ] **Step 6: Commit**

```bash
git add -A web_ui/src
git commit -m "refactor(web): shared machinery into shared/, auth into features/

Moves only — git mv so the history follows, and the sole content change is
the comment in index.js explaining why the stylesheet import sits above the
App import. That ordering is the difference between a working sort dropdown
and one the width of the toolbar, and it had been holding with nothing
written down.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Extract the leaf components from HighFashionV2

Three presentational pieces with no state of their own. They come out first
because they cannot break anything else — each is JSX plus props.

All line numbers refer to `src/components/HighFashionV2.js` as it stands at the
start of this task. **Re-check them before cutting** — Task 5 changed imports at
the top of the file and may have shifted them by a line or two. The JSX
landmarks in the table are authoritative; the numbers are a starting point.

**Files:**
- Create: `src/features/high-fashion/StatusBar.js`, `ThumbStrip.js`, `VideoPanel.js`
- Modify: `src/components/HighFashionV2.js`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `<StatusBar indexReady total currentImageIndex imagesLength selectedCollection />`
  - `<ThumbStrip images currentImageIndex onSelect isFavourite stripRef activeThumbRef extractLookNumber />`
  - `<VideoPanel videoData videoState videoError videoHeight isPlaying currentTime duration playerContainerRef onResizeStart onTogglePlay onSeek />`

| Component | Cut from | Landmark |
|---|---|---|
| `StatusBar` | ~1634–1659 | `<div className="hf2-status-bar">` to its close |
| `ThumbStrip` | ~1563–1584 | `<div className="hf2-thumb-strip-container">` to its close |
| `VideoPanel` | ~1480–1532 | `<div className="hf2-video-side">` to its close |

- [ ] **Step 1: Create the three files**

Each file is the JSX moved **verbatim**, wrapped in a function whose parameters
are exactly the identifiers the JSX referenced. Do not rename anything and do
not restructure the markup — a renamed class here is a visual regression that
no test will catch.

Template — `src/features/high-fashion/StatusBar.js`:

```javascript
import React from 'react';

// The bottom readout. Presentational: every value is a prop, and it holds no
// state of its own.
function StatusBar({
  indexReady,
  total,
  currentImageIndex,
  imagesLength,
  selectedCollection,
}) {
  return (
    /* the JSX from hf2-status-bar, verbatim */
  );
}

export default StatusBar;
```

Build `ThumbStrip.js` and `VideoPanel.js` the same way, with the prop lists
from the Interfaces block above.

`ThumbStrip` needs the two refs (`thumbStripRef`, `activeThumbRef`) passed in
as props, because the centring effect stays in the parent for now. Pass them as
`stripRef` and `activeThumbRef` and attach them with `ref={stripRef}`.

- [ ] **Step 2: Replace the JSX in HighFashionV2 with the three elements**

```javascript
import StatusBar from '../features/high-fashion/StatusBar';
import ThumbStrip from '../features/high-fashion/ThumbStrip';
import VideoPanel from '../features/high-fashion/VideoPanel';
```

and at each cut site, the corresponding element with every prop wired.

- [ ] **Step 3: Build**

```bash
cd web_ui && npm run build && npm run check:css
```

Expected: clean build, no `defined but never used` warnings for identifiers
left behind by the cut. A warning here means a variable is now unused in the
parent and should be deleted, or a prop was forgotten.

- [ ] **Step 4: Look at it**

```bash
cd web_ui && REACT_APP_API_URL=http://localhost:8081 PORT=3100 npm start
```

Open `http://localhost:3100`, sign in, open any show. Confirm: the status bar
reads the same, the thumb strip scrolls and centres on the active thumb, and
the video panel opens and plays.

This is a visual task. The build passing means nothing about whether the strip
still centres.

- [ ] **Step 5: Commit**

```bash
git add -A web_ui/src
git commit -m "refactor(web): the three leaves out of HighFashionV2

Status bar, thumb strip and video panel are JSX and props with no state of
their own, so they come out first and cannot break what is left. Markup
moved verbatim — a renamed class here is a visual regression no test in this
project would catch.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Extract Filters, ShowList and Viewer; HighFashionPage composes

The stateful half. These three own the bulk of the file. The state stays in the
parent — this task moves markup and handlers, not ownership. Moving state is
phase 2's job and mixing the two is how a 1,662-line refactor goes wrong.

**Files:**
- Create: `src/features/high-fashion/Filters.js`, `ShowList.js`, `Viewer.js`
- Create: `src/features/high-fashion/HighFashionPage.js` (renamed from `HighFashionV2.js`)
- Create: `src/features/high-fashion/HighFashionPage.css` (renamed from `HighFashionV2.css`)
- Delete: `src/components/HighFashionV2.js`, `HighFashionV2.css`

**Interfaces:**
- Consumes: `StatusBar`, `ThumbStrip`, `VideoPanel` from Task 6.
- Produces:
  - `<Filters query suggestions activeSuggestion searchFocused recentDesigners designerMode filters serverFacets indexReady onQueryChange onSuggestionPick onFilterChange onClearFilters onExitDesigner />`
  - `<ShowList collections visibleCollections selectedCollection designerMode designerLoading loadingMore cursor listError collectionsLoading onSelect onScroll />`
  - `<Viewer images currentImageIndex viewMode imagesLoading selectedCollection isFavourite onToggleFavourite onSelectImage onSetViewMode />`
  - `HighFashionPage` — default export, props unchanged: `{ currentPage, onPageSwitch, currentUser, onLogout }`

| Component | Cut from | Landmark |
|---|---|---|
| `Filters` | ~1162–1362 | `<div className="hf2-search">` through the end of `hf2-filters` |
| `ShowList` | ~1364–1437 | `<div className="hf2-collections-area">` to its close |
| `Viewer` | ~1440–1560, ~1587–1632 | `hf2-main`'s single and grid containers, plus `hf2-controls` |

- [ ] **Step 1: Rename the file and its stylesheet**

```bash
cd web_ui/src
mkdir -p features/high-fashion
git mv components/HighFashionV2.js features/high-fashion/HighFashionPage.js
git mv components/HighFashionV2.css features/high-fashion/HighFashionPage.css
```

Change the function name `HighFashionV2` to `HighFashionPage`, its export, and
its stylesheet import to `'./HighFashionPage.css'`. Fix the now-shallower
imports of `StatusBar`/`ThumbStrip`/`VideoPanel` to `'./StatusBar'` etc., and
deepen the shared ones to `'../../shared/api'` and `'../../shared/lib/designerSearch'`.

**Do not rename any CSS class.** `hf2-*` stays. Renaming 200 classes and moving
eight files in one commit makes a visual regression impossible to bisect.

- [ ] **Step 2: Cut the three components**

Same discipline as Task 6: JSX verbatim, parameters are exactly the identifiers
the JSX referenced, nothing renamed.

`ShowList` note: the list renders `cleanDesignerName(col.designer)`. That helper
is defined at the top of `HighFashionPage.js` (around line 34). Move it to
`src/shared/lib/designerName.js` and import it from both files rather than
duplicating it.

`Viewer` note: it renders both the single and grid containers and the controls
row, because `viewMode` switches between them and the controls toggle it. It
receives `isFavourite` as a function prop and calls it per tile — do not try to
pass a precomputed set in this task.

- [ ] **Step 3: Reduce HighFashionPage to composition plus state**

What remains is the hooks, the effects, the handlers, and a render that is the
seven elements. It should be roughly 700–900 lines — still large, because all
the state is still here, which is correct for this phase.

- [ ] **Step 4: Repoint App.js**

```javascript
import HighFashionPage from '../features/high-fashion/HighFashionPage';
```

and the element becomes `<HighFashionPage {...pageProps} />`.

- [ ] **Step 5: Build and check**

```bash
cd web_ui && npm run build && npm run check:css
CI=true npx react-scripts test --watchAll=false 2>&1 | tail -10
```

Expected: clean build, `check:css` exit 0, all tests pass.

- [ ] **Step 6: Look at it — the full High Fashion page**

```bash
cd web_ui && REACT_APP_API_URL=http://localhost:8081 PORT=3100 npm start
```

Walk every one of these and confirm no change from before the task:
- the designer search box, typing and picking a suggestion
- each of the six facet dropdowns, and Clear
- the show list, scrolling to the bottom to trigger paging
- opening a show, arrow keys, `g` for grid, `F` for favourite
- the video button
- the sidebar collapse handle

- [ ] **Step 7: Commit**

```bash
git add -A web_ui/src
git commit -m "refactor(web): HighFashionV2 comes apart into seven files

1,662 lines holding thirty useState calls, and every feature in the current
plan lands inside it. Filters, the show list and the viewer are now their
own files; the page is composition plus the state that spans them.

State ownership deliberately did not move — that is the next phase. Moving
markup and moving state in one commit is how a refactor this size becomes
unbisectable. No CSS class was renamed for the same reason.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Move My Brands into `features/brands/`

**Files:**
- Move: `src/components/MyBrandsPanel.js` → `src/features/brands/BrandsPage.js`
- Move: `src/components/MyBrandsPanel.css` → `src/features/brands/BrandsPage.css`
- Move: `src/components/ProductDetailPanel.js`, `.css` → `src/features/brands/`
- Modify: `src/app/App.js`

**Interfaces:**
- Consumes: `shared/api`, `shared/ui/TopBar`.
- Produces: `BrandsPage` — default export, props unchanged: `{ currentPage, onPageSwitch, currentUser, onLogout }`.

- [ ] **Step 1: Move**

```bash
cd web_ui/src && mkdir -p features/brands
git mv components/MyBrandsPanel.js features/brands/BrandsPage.js
git mv components/MyBrandsPanel.css features/brands/BrandsPage.css
git mv components/ProductDetailPanel.js components/ProductDetailPanel.css features/brands/
```

- [ ] **Step 2: Rename the component and fix imports**

In `BrandsPage.js`: function `MyBrandsPanel` → `BrandsPage`, its export, and
the stylesheet import → `'./BrandsPage.css'`. Shared imports deepen to
`'../../shared/api'` and `'../../shared/ui/TopBar'`. `ProductDetailPanel`
becomes `'./ProductDetailPanel'`.

No CSS class renames.

- [ ] **Step 3: Repoint App.js and build**

```bash
cd web_ui && npm run build && npm run check:css
```

Expected: clean, exit 0. `check:css` matters here specifically — its second
pair (`.ar-select` / `.product-sort-select`) guards this page's toolbar.

- [ ] **Step 4: Look at it**

Open My Brands at **1440px and at 1100px**. Confirm the search field is wide
and the sort dropdown is roughly 150px on the right — the exact regression the
cascade guard exists for. Confirm the product grid, a product detail panel, and
the detail panel's drag-to-resize.

- [ ] **Step 5: Commit**

```bash
git add -A web_ui/src
git commit -m "refactor(web): My Brands into features/brands

Move and rename only. check:css guards this page's toolbar specifically —
the sort dropdown and the search field are the pair that broke last time.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Move Favourites into `features/library/`

**Files:**
- Move: `src/components/FavouritesPanel.js` → `src/features/library/LibraryPage.js`
- Move: `src/components/FavouritesPanel.css` → `src/features/library/LibraryPage.css`
- Modify: `src/app/App.js`, `src/shared/ui/TopBar.js`

**Interfaces:**
- Consumes: `shared/api`, `shared/ui/TopBar`.
- Produces: `LibraryPage` — default export, props unchanged.

- [ ] **Step 1: Move and rename**

```bash
cd web_ui/src && mkdir -p features/library
git mv components/FavouritesPanel.js features/library/LibraryPage.js
git mv components/FavouritesPanel.css features/library/LibraryPage.css
ls components 2>/dev/null; rmdir components 2>/dev/null
```

Function `FavouritesPanel` → `LibraryPage`, export, stylesheet import, and the
shared imports deepened to `'../../shared/...'`.

- [ ] **Step 2: Leave the page's identity alone**

The nav label stays "Favourites" and the page key stays `'favourites'` in this
task. Renaming the user-facing concept to "Library" is phase 3's job, along with
the content that justifies the name. Renaming it now means a nav item that
promises albums and saved views and delivers a flat list of looks.

- [ ] **Step 3: Guard the favourite identity**

Confirm this call is byte-identical to what it was:

```bash
cd web_ui && grep -n -A4 "removeFavourite(" src/features/library/LibraryPage.js
```

Expected, in this order:

```javascript
FashionArchiveAPI.removeFavourite(
  favourite.season.url,
  favourite.collection.url,
  favourite.look.number
);
```

`removeFavourite(seasonUrl, collectionUrl, lookNumber)` is positional. Two of
those three are URLs, so swapping them throws no error — it deletes a different
favourite, or none, silently.

- [ ] **Step 4: Build, test, look**

```bash
cd web_ui && npm run build && npm run check:css
CI=true npx react-scripts test --watchAll=false 2>&1 | tail -10
```

Then open Favourites: the sidebar, the GRID/SINGLE toggle, the thumb strip, the
Remove button (small, reddens on hover), and the "Recently viewed" strip.
Remove one favourite and confirm the one that disappears is the one you clicked.

- [ ] **Step 5: Commit**

```bash
git add -A web_ui/src
git commit -m "refactor(web): Favourites into features/library

The folder is named for what it becomes; the page, the nav label and the
page key still say Favourites, because a nav item promising albums and
saved views should not arrive before they do.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Wire the router into the app

The payoff. After this, back and forward work.

**Files:**
- Modify: `src/app/App.js`, `src/features/high-fashion/HighFashionPage.js`
- Test: `src/app/App.route.test.js`

**Interfaces:**
- Consumes: `useRoute` from Task 3, `slugify`/`buildRoute` from Task 2, the three page components from Tasks 7–9.
- Produces: nothing later tasks depend on. Phase 2 reads `route.filters`.

- [ ] **Step 1: Replace `currentPage` state with the route**

In `src/app/App.js`:

```javascript
import { useRoute } from '../shared/hooks/useRoute';

// ... inside App()
const [route, go] = useRoute();

// The page is derived from the URL now. 'album' and 'shared' are routes that
// phases 4 and 5 fill in; until then they render the library and the archive,
// which is where an unfinished link should land rather than a blank screen.
const currentPage =
  route.page === 'brands' ? 'my-brands'
  : route.page === 'library' || route.page === 'album' ? 'favourites'
  : 'high-fashion';

const handlePageSwitch = (page) => {
  go({
    page: page === 'my-brands' ? 'brands'
      : page === 'favourites' ? 'library'
      : 'high-fashion',
  });
};
```

Delete `const [currentPage, setCurrentPage] = useState('high-fashion');`.

- [ ] **Step 2: Narrow the query-string scrub**

The existing scrub removes the whole query string, which would now delete the
filters on every load. In `src/app/App.js`, replace:

```javascript
    if (params.toString()) {
      window.history.replaceState({}, '', window.location.pathname);
    }
```

with:

```javascript
    // Strip only the auth parameters. A reset token must not sit in history
    // where it can be copied out of the address bar — but the filters live in
    // this query string now, and wiping the lot would drop them on every load.
    const AUTH_PARAMS = ['token', 'verified', 'error'];
    if (AUTH_PARAMS.some((k) => params.has(k))) {
      AUTH_PARAMS.forEach((k) => params.delete(k));
      const rest = params.toString();
      window.history.replaceState(
        {}, '', window.location.pathname + (rest ? `?${rest}` : '')
      );
    }
```

- [ ] **Step 3: Deep-link a show in HighFashionPage**

Two directions, and they must not fight each other.

**URL to state** — when `route.collectionId` names a show that is not open,
open it:

```javascript
const [route, go] = useRoute();

// Opening a show named by the URL. Runs on first load and on Back/Forward.
// Guarded on the id differing from what is already open, so this effect does
// not re-enter when selecting a show writes the URL below.
useEffect(() => {
  const wanted = route.collectionId;
  if (!wanted) return;
  if (selectedCollection && String(selectedCollection.collection_id) === wanted) return;

  let cancelled = false;
  FashionArchiveAPI.browseCatalog({}, { limit: 1, collectionId: wanted })
    .then((res) => {
      const col = (res?.rows || res?.collections || [])[0];
      if (!cancelled && col) handleCollectionSelect(col, { fromUrl: true });
    })
    .catch((error) => console.error('Could not open the show in the URL:', error));
  return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [route.collectionId]);
```

**`browseCatalog` has no by-id lookup today** — verified: `browse_catalog` in
`backend/api/high_fashion_routes.py:696` accepts only
`gender, year, season, category, shootType, city, designer, letter`. Add one,
in the same task, because it is two lines:

1. In `backend/high_fashion/show_index.py`, add `collection_id` to
   `_FILTER_COLUMNS` (it maps filter keys to columns and drives `_where` at
   line 179, so no other change is needed there).
2. In `backend/api/high_fashion_routes.py:696`, add `'collectionId'` to the
   tuple of accepted filter keys and map it to `collection_id`:

```python
    filters = {k: data.get(k) for k in
               ('gender', 'year', 'season', 'category', 'shootType', 'city',
                'designer', 'letter')}
    filters = {k: v for k, v in filters.items() if v not in (None, '')}
    # A deep link carries the show's id and nothing else. This is the only
    # way back from a URL to a collection row.
    if data.get('collectionId'):
        filters['collection_id'] = str(data['collectionId'])
```

3. In `shared/api/archive.js`, `browseCatalog` already spreads its options into
   the body, so pass `collectionId` through:

```javascript
  static async browseCatalog(filters, { text, limit = 200, offset = 0, facets = false, collectionId } = {}) {
    return ApiClient.callPython('/api/browse', {
      ...filters, text, limit, offset, facets, collectionId,
    });
  }
```

Verify with the backend running:

```bash
curl -s -X POST http://localhost:8081/api/browse \
  -H 'Content-Type: application/json' -b /tmp/cookies.txt \
  -d '{"collectionId":"3","limit":1}' | head -c 300
```

Expected: one collection whose `collection_id` is `"3"`. An empty
`collections` array means the filter was dropped rather than applied.

**State to URL** — when the user opens a show or moves between images:

```javascript
// The address bar follows the viewer. replace: true for image moves so that
// arrowing through forty looks leaves one history entry, not forty — Back
// should return to the show list, not walk backwards through the lookbook.
useEffect(() => {
  if (!selectedCollection) return;
  const n = images.length ? currentImageIndex + 1 : null;
  go({
    page: 'high-fashion',
    slug: slugify(selectedCollection.designer, selectedCollection.subtitle),
    collectionId: String(selectedCollection.collection_id),
    imageNumber: n,
    filters,
  }, { replace: true });
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [selectedCollection, currentImageIndex, images.length, filters]);
```

Selecting a show from the list pushes (so Back leaves the show); image moves
replace. Achieve that by calling `go({...}, { replace: false })` once inside
`handleCollectionSelect` — but not when it was called with `{ fromUrl: true }`,
which would push an entry for a navigation the user already made.

- [ ] **Step 4: Put the filters in the query string**

`filters` is already in the effect above. Also seed it from the URL on mount:

Import `getRoute` alongside the hook:

```javascript
import { getRoute } from '../../app/router';
```

```javascript
// The URL wins over the default filter set on first load, so a shared or
// bookmarked filtered view opens filtered.
const [filters, setFilters] = useState(() => ({
  gender: 'Women', year: '', season: '', category: '',
  shootType: '', city: '', letter: '',
  ...getRoute().filters,
}));
```

- [ ] **Step 5: Write the route-to-page test**

Create `src/app/App.route.test.js`. This tests the mapping, not React —
rendering `App` would need a backend.

```javascript
import { parseRoute } from './routes';

// The mapping in App.js from a parsed route to the page key the three page
// components and TopBar use. Kept in step with App.js by hand; if the page
// keys change, this test is where it shows up.
const pageKeyFor = (route) =>
  route.page === 'brands' ? 'my-brands'
  : route.page === 'library' || route.page === 'album' ? 'favourites'
  : 'high-fashion';

test.each([
  ['/', 'high-fashion'],
  ['/hf/gucci/1234', 'high-fashion'],
  ['/hf/gucci/1234/12', 'high-fashion'],
  ['/brands', 'my-brands'],
  ['/brands/acne/knitwear', 'my-brands'],
  ['/library', 'favourites'],
  ['/library/albums/7', 'favourites'],
  ['/nonsense', 'high-fashion'],
])('%s renders the %s page', (path, expected) => {
  expect(pageKeyFor(parseRoute(path, ''))).toBe(expected);
});

// A share link has no page of its own yet. It must land somewhere real
// rather than on a blank screen.
test('an unfinished share route still renders a page', () => {
  expect(pageKeyFor(parseRoute('/s/AbC123', ''))).toBe('high-fashion');
});
```

- [ ] **Step 6: Build and test**

```bash
cd web_ui && npm run build && npm run check:css
CI=true npx react-scripts test --watchAll=false 2>&1 | tail -12
```

Expected: clean build, exit 0, all suites pass.

- [ ] **Step 7: Look at it — this is the acceptance test for the whole phase**

```bash
cd web_ui && REACT_APP_API_URL=http://localhost:8081 PORT=3100 npm start
```

Walk all of these:

1. Click Collections → Favourites → My Brands. Press Back twice. You land on
   Favourites, then Collections.
2. Open a show. The address bar reads `/hf/<something>/<id>/1`.
3. Arrow right ten times. The number in the URL tracks. Press Back **once** —
   you leave the show, not the tenth image.
4. Copy the URL, open it in a new tab. The same show opens at the same image.
5. Set a year and a city filter. The query string shows both. Reload. The
   filters are still set.
6. Hand-edit the slug in the URL to nonsense and reload. The same show opens.
7. Visit `/hf/gucci/999999999` (an id that does not exist). The page loads the
   archive and does not hang or white-screen.
8. Open `http://localhost:3100/?verified=1`. The banner shows and `verified` is
   gone from the address bar.

Any failure here is a phase-1 bug — fix it before phase 2.

- [ ] **Step 8: Commit**

```bash
git add -A web_ui/src
git commit -m "feat(web): back and forward

The URL is the source of truth for which page is open, which show, which
image and which filters. currentPage state is gone.

Image moves replace rather than push, so arrowing through forty looks leaves
one history entry — Back returns to the show list, which is what Back means
here. Selecting a show pushes.

The auth-parameter scrub is narrowed to token/verified/error: it used to
wipe the whole query string, which now holds the filters.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Deliberate deviation from the spec

The spec's phase-1 row says "shared hooks scaffolded". Only `useRoute` is
created here. `usePersistentState`, `useSaves`, `useRecents` and
`useCollectionImages` arrive in the phase that uses them — empty hook files
with no callers are placeholders, and a placeholder that lands in a commit is
indistinguishable from a hook someone forgot to finish.

Task 10 also adds a small backend change (a by-id filter on `/api/browse`),
which the spec put nowhere. Without it a deep link cannot be resolved at all.

## Phase 1 exit criteria

All of these, before phase 2 starts:

- [ ] `npm run build` clean
- [ ] `npm run check:css` exit 0
- [ ] `CI=true npx react-scripts test --watchAll=false` — all suites pass
- [ ] `src/components/` and `src/services/` no longer exist
- [ ] `grep -rn "HighFashionV2\|MyBrandsPanel\|FavouritesPanel" web_ui/src` returns nothing
- [ ] The eight browser checks in Task 10 Step 7 all pass
- [ ] My Brands at 1440px and 1100px looks exactly as it did before the phase
