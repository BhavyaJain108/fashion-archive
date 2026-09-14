import { FashionArchiveAPI, ArchiveAPI } from '../index';
import ArchiveEndpoints from '../archive';

test('every method the pages call still resolves', () => {
  for (const name of [
    'getMe', 'login', 'register', 'logout', 'resendVerification',
    'requestPasswordReset', 'resetPassword', 'callPython', 'consumeSSE',
    'getImageUrl', 'getSeasons', 'downloadVideo', 'streamCatalog',
    'getIndexStatus', 'browseCatalog', 'searchShows', 'getDesigners',
    'streamDesignerCollections', 'streamCollectionImages', 'getRecents',
    'getFavourites', 'addFavourite', 'removeFavourite', 'getFavouriteStats',
    'addShowFavourite', 'removeShowFavourite',
    'addViewFavourite', 'removeViewFavourite',
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
  expect(require('../client').default.onUnauthorized).toBe(fn);
  FashionArchiveAPI.onUnauthorized = null;
});

// Regression test for the memo caches following the receiver: getIndexStatus
// and getDesigners memoise into archive.js's own class fields. A call routed
// through the facade must still land the cache on ArchiveEndpoints itself,
// not on FashionArchiveAPI (whatever `this` happened to be bound to) — any
// other module importing ArchiveEndpoints directly needs to see the same
// cache, or it silently refetches the ~87 KB designer index every time.
test('memoised archive caches are pinned to the archive module, not the receiver', async () => {
  const originalFetch = global.fetch;
  ArchiveEndpoints._indexReady = null;
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ shows: 42 }),
  }));
  try {
    const result = await FashionArchiveAPI.getIndexStatus();
    expect(result).toEqual({ shows: 42 });
    expect(ArchiveEndpoints._indexReady).toEqual({ shows: 42 });
  } finally {
    global.fetch = originalFetch;
    ArchiveEndpoints._indexReady = null;
  }
});

// Regression test for the facade's property-copy loop silently letting a
// later module overwrite an earlier one's export of the same name. Exercised
// directly against the copy helper rather than by forcing a real collision
// between the three live modules (there isn't one today, and shouldn't be).
test('the facade copy loop throws on a name collision between modules', () => {
  // eslint-disable-next-line global-require
  const { copyStatics } = require('../index');
  class ModuleA { static shared() {} }
  class ModuleB { static shared() {} }
  const target = {};
  copyStatics(target, ModuleA);
  expect(() => copyStatics(target, ModuleB)).toThrow(/shared/);
});
