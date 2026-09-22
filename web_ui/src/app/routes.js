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
  slug: null,
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

// A stale bookmark or a bot probe can carry a stray "%" that isn't valid
// percent-encoding (e.g. "50%"). decodeURIComponent throws on that, and an
// unrecognised path is supposed to open the archive rather than crash the
// app, so a segment that fails to decode is kept raw instead of throwing.
const safeDecode = (segment) => {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
};

// Image numbers are 1-based (the page builds them as currentImageIndex +
// 1), so 0 never denotes a real image; a URL containing it is malformed
// the same way a non-numeric value is, and is rejected here at the parse
// end so buildRoute's truthiness check on imageNumber stays correct.
const asImageNumber = (raw) => {
  if (!/^\d+$/.test(raw || '')) return null;
  const n = parseInt(raw, 10);
  return n === 0 ? null : n;
};

export function parseRoute(pathname, search) {
  const filters = readFilters(search);
  const segments = (pathname || '/').split('/').filter(Boolean).map(safeDecode);

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
      slug: rest[0] || null,
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

  // The design language, rendered. Needs no session: it shows tokens and
  // primitives, nothing from the archive.
  if (head === 'styleguide') {
    return { ...EMPTY, filters, page: 'styleguide' };
  }

  // The machine room. Not linked from anywhere in the app: the server refuses it
  // to anyone who is not the owner, so the URL is the whole entry point.
  //
  //   /dev                         the overview
  //   /dev/costs                   what it costs
  //   /dev/brands/<domain>         one brand, field by field
  //   /dev/brands/<domain>/products  its catalogue
  //
  // The brand rides in `brandId` and the sub-view in `category`, the same two
  // slots My Brands uses, so no page needs a route shape of its own.
  if (head === 'dev') {
    if (rest[0] === 'costs') return { ...EMPTY, filters, page: 'dev', category: 'costs' };
    if (rest[0] === 'brands' && rest[1]) {
      return {
        ...EMPTY,
        filters,
        page: 'dev',
        brandId: rest[1],
        category: rest[2] === 'products' ? 'products' : null,
      };
    }
    return { ...EMPTY, filters, page: 'dev' };
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

  if (r.page === 'styleguide') return '/styleguide';
  if (r.page === 'dev') {
    if (r.brandId) {
      const tail = r.category === 'products' ? '/products' : '';
      return `/dev/brands/${encodeURIComponent(r.brandId)}${tail}`;
    }
    return r.category === 'costs' ? '/dev/costs' : '/dev';
  }

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
