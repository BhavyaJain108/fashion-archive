import { FashionArchiveAPI, ArchiveAPI } from '../index';

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
  expect(require('../client').default.onUnauthorized).toBe(fn);
  FashionArchiveAPI.onUnauthorized = null;
});
