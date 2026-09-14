import { parseRoute, buildRoute } from './routes';
import {
  SESSION_KEY, shouldRestore, rememberSession, restoreSession, clearSession,
} from './session';
import {
  initialUrlSync, deepLinkStarted, deepLinkSettled, urlWrite,
} from '../features/high-fashion/showUrl';

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ── When a stored session is allowed to win ───────────────────────────────

describe('shouldRestore', () => {
  test('a bare / is the only arrival blank enough to fill in', () => {
    expect(shouldRestore('/', '')).toBe(true);
    // window.location.search is '' with no query, but a URL typed with a
    // lone '?' carries nothing either.
    expect(shouldRestore('/', '?')).toBe(true);
    expect(shouldRestore('/', undefined)).toBe(true);
    expect(shouldRestore(undefined, '')).toBe(true);
  });

  test('a URL carrying filters is a destination, not a blank', () => {
    // Somebody's bookmark of "Paris, 2024". It names no show, but it is
    // still the view they chose, and last night's show must not land on
    // top of it.
    expect(shouldRestore('/', '?city=Paris&year=2024')).toBe(false);
    expect(shouldRestore('/', '?gender=Men')).toBe(false);
  });

  test('a URL naming anything at all is left alone', () => {
    expect(shouldRestore('/hf/gucci/1234', '')).toBe(false);
    expect(shouldRestore('/hf/gucci/1234/12', '')).toBe(false);
    expect(shouldRestore('/brands', '')).toBe(false);
    expect(shouldRestore('/library', '')).toBe(false);
    // Even an unrecognised path: it parses to the archive, but the reader
    // typed something, and overwriting it would hide that they mistyped.
    expect(shouldRestore('/nonsense', '')).toBe(false);
  });

  test('a query string that is not a filter still counts as a destination', () => {
    // Not this module's business to know which keys are filters. App.js
    // strips the auth parameters before this runs; anything still here is
    // something the reader arrived with.
    expect(shouldRestore('/', '?utm_source=mail')).toBe(false);
  });
});

// ── Round trip ────────────────────────────────────────────────────────────

describe('rememberSession and restoreSession', () => {
  test('nothing stored restores nothing', () => {
    expect(restoreSession()).toBeNull();
  });

  test('a show survives the round trip, look and all', () => {
    rememberSession({
      page: 'high-fashion',
      slug: 'yohji-yamamoto-fw-1999',
      collectionId: '1234',
      imageNumber: 12,
      filters: { city: 'Paris', year: '1999' },
    });
    const back = restoreSession();
    expect(back.collectionId).toBe('1234');
    expect(back.imageNumber).toBe(12);
    expect(back.slug).toBe('yohji-yamamoto-fw-1999');
    expect(back.filters).toEqual({ city: 'Paris', year: '1999' });
  });

  test('the other pages survive it too', () => {
    rememberSession({ page: 'brands', brandId: 'acne', category: 'knitwear' });
    expect(restoreSession()).toMatchObject({
      page: 'brands', brandId: 'acne', category: 'knitwear',
    });

    rememberSession({ page: 'album', albumId: '7' });
    expect(restoreSession()).toMatchObject({ page: 'album', albumId: '7' });
  });

  test('a filtered archive with no show survives it', () => {
    rememberSession({ page: 'high-fashion', filters: { gender: 'Men' } });
    const back = restoreSession();
    expect(back.collectionId).toBeNull();
    expect(back.filters).toEqual({ gender: 'Men' });
  });

  test('what is stored is a URL and nothing else', () => {
    // The guarantee that matters: a route is where you were, not what you
    // had loaded. A row handed in here is not what comes back out.
    rememberSession({
      page: 'high-fashion',
      slug: 'gucci',
      collectionId: '1234',
      filters: {},
      collection: { designer: 'Gucci', images: ['a.jpg', 'b.jpg'] },
    });
    expect(JSON.parse(window.localStorage.getItem(SESSION_KEY)))
      .toBe('/hf/gucci/1234');
    expect(restoreSession().collection).toBeUndefined();
  });

  test('it writes under the same fa: prefix as every other stored value', () => {
    rememberSession({ page: 'library' });
    expect(SESSION_KEY.startsWith('fa:')).toBe(true);
    expect(window.localStorage.getItem(SESSION_KEY)).toBe(JSON.stringify('/library'));
  });

  test('the last write is the one restored', () => {
    rememberSession({ page: 'high-fashion', slug: 'a', collectionId: '1' });
    rememberSession({ page: 'high-fashion', slug: 'b', collectionId: '2' });
    expect(restoreSession().collectionId).toBe('2');
  });
});

// ── What a half-written value from an old release does ────────────────────
//
// The tolerances here are usePersistentState's, for the same reason: this
// value was written by some earlier release of this app and is read by this
// one. None of these may throw — a white screen is a worse answer than the
// archive.

// ── Ending a session ──────────────────────────────────────────────────────
//
// This value is browsing history — the last show's slug and the filters
// that found it — and localStorage has no expiry, so without a clear it
// outlives the session that wrote it. On a shared browser that means the
// next person to open "/" lands in the previous user's last show.

describe('clearSession', () => {
  test('a stored route does not survive it', () => {
    rememberSession(parseRoute('/hf/yohji-yamamoto/1234/7', ''));
    expect(restoreSession()).not.toBeNull();

    clearSession();

    expect(window.localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(restoreSession()).toBeNull();
  });

  test('clearing nothing is not an error', () => {
    expect(() => clearSession()).not.toThrow();
    expect(restoreSession()).toBeNull();
  });

  test('it touches nothing else under the fa: prefix', () => {
    // Everything this origin stores shares one prefix. Ending a session
    // forgets where the reader was, not which view mode they like.
    window.localStorage.setItem('fa:high-fashion-view-mode', '"grid"');
    rememberSession(parseRoute('/hf/yohji-yamamoto/1234/7', ''));

    clearSession();

    expect(window.localStorage.getItem('fa:high-fashion-view-mode')).toBe('"grid"');
  });

  test('a localStorage that throws is survivable', () => {
    jest.spyOn(window.localStorage.__proto__, 'removeItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    expect(() => clearSession()).not.toThrow();
  });
});

describe('a stored value this release cannot read', () => {
  test.each([
    ['not JSON at all', '{not json'],
    ['a write cut off halfway', '"/hf/gucci/12'],
    ['an empty string', ''],
    ['a number', '42'],
    ['a null', 'null'],
    ['an object from a release that stored the route itself', '{"page":"library"}'],
    ['an array', '["/library"]'],
    ['a string that is not a path', '"hf/gucci/1234"'],
    ['an absolute URL to somewhere else', '"https://example.test/hf/x/1"'],
  ])('%s restores nothing rather than throwing', (_name, raw) => {
    window.localStorage.setItem(SESSION_KEY, raw);
    expect(() => restoreSession()).not.toThrow();
    expect(restoreSession()).toBeNull();
  });
});

describe('a localStorage that throws', () => {
  test('reading is survivable', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    expect(() => restoreSession()).not.toThrow();
    expect(restoreSession()).toBeNull();
  });

  test('writing is survivable', () => {
    // Safari private mode throws on setItem; so does a full quota.
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    expect(() => rememberSession({ page: 'library' })).not.toThrow();
  });
});

// ── A stored show that no longer resolves ─────────────────────────────────
//
// firstVIEW rows come and go, and a session stored last month can name a
// collection id that answers nothing today. There is no separate path for
// this: the restored route is handed to the same deep-link machinery a
// mistyped URL goes through, so it degrades the same way — the archive
// stays on screen and the address bar is corrected once the lookup comes
// back empty. That sameness is the thing worth testing, so the functions
// below are the page's own, not a restatement of them.

describe('a stored session naming a show that no longer resolves', () => {
  test('degrades to the archive, exactly as a bad deep link does', () => {
    rememberSession({
      page: 'high-fashion',
      slug: 'a-label-that-folded',
      collectionId: '999999',
      filters: { city: 'Paris' },
    });

    const restored = restoreSession();
    expect(buildRoute(restored)).toBe('/hf/a-label-that-folded/999999?city=Paris');

    // App hands that to navigate(replace); the page reads it back off the
    // address bar and starts the lookup.
    let sync = initialUrlSync('/');
    sync = deepLinkStarted(sync, {
      collectionId: restored.collectionId, imageNumber: restored.imageNumber,
    });
    // While it is in flight the URL is ahead of the state, so nothing is
    // written over the restored link.
    expect(urlWrite(sync, { hasSelection: false }).target).toBe('none');

    // The lookup answers with no row. Nothing opens.
    sync = deepLinkSettled(sync, { found: false });
    const decided = urlWrite(sync, { hasSelection: false });
    expect(decided.target).toBe('archive');

    // And the archive keeps the filters the stored session carried, so a
    // dead show does not also cost the reader their view.
    expect(buildRoute({ page: 'high-fashion', filters: restored.filters }))
      .toBe('/?city=Paris');
  });

  test('a stored route this app no longer recognises opens the archive', () => {
    // A path from a release that had a page this one does not.
    window.localStorage.setItem(SESSION_KEY, JSON.stringify('/moodboards/17'));
    const restored = restoreSession();
    expect(restored).toEqual(parseRoute('/moodboards/17', ''));
    expect(restored.page).toBe('high-fashion');
    expect(restored.collectionId).toBeNull();
    expect(buildRoute(restored)).toBe('/');
  });
});
