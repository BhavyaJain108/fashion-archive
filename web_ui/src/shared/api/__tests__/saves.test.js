import SavesEndpoints from '../saves';
import ApiClient from '../client';

// What each call puts on the wire. The endpoints are keyed differently per
// kind on the server, so the body this file asserts is the whole contract —
// a look body sent for a show saves the wrong thing and reports success.

let fetchMock;

beforeEach(() => {
  fetchMock = jest.fn(() => Promise.resolve({
    ok: true,
    statusText: 'OK',
    json: () => Promise.resolve({ success: true }),
  }));
  global.fetch = fetchMock;
});

afterEach(() => {
  delete global.fetch;
  jest.restoreAllMocks();
});

const lastCall = () => {
  const [url, options] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return { url, method: options.method, body: JSON.parse(options.body) };
};

const SEASON = { name: 'Fall 2024', url: 'https://ex.com/f24', link_text: 'F24' };
const COLLECTION = { designer: 'Balenciaga', url: 'https://ex.com/balenciaga-f24' };

describe('a look — unchanged, because the pages call it today', () => {
  test('addFavourite sends no kind, which the server reads as a look', async () => {
    await SavesEndpoints.addFavourite(SEASON, COLLECTION, { number: 12 }, '/img/12.jpg', 'note');
    const { url, method, body } = lastCall();
    expect(url).toBe(`${ApiClient.BASE_URL}/api/favourites`);
    expect(method).toBe('POST');
    expect(body).toEqual({
      season: SEASON,
      collection: COLLECTION,
      look: { number: 12 },
      image_path: '/img/12.jpg',
      notes: 'note',
    });
    expect(body.kind).toBeUndefined();
  });

  // Two of the three arguments are URLs, so a renumbering is invisible at the
  // call site and wrong at the server. Phase 3 adds call sites; it does not
  // get to renumber this.
  test('removeFavourite is still (seasonUrl, collectionUrl, lookNumber)', async () => {
    await SavesEndpoints.removeFavourite('https://ex.com/f24', 'https://ex.com/bal', 12);
    const { method, body } = lastCall();
    expect(method).toBe('DELETE');
    expect(body).toEqual({
      season_url: 'https://ex.com/f24',
      collection_url: 'https://ex.com/bal',
      look_number: 12,
    });
    expect(body.kind).toBeUndefined();
  });

  test('removeFavourite has exactly three declared parameters', () => {
    expect(SavesEndpoints.removeFavourite.length).toBe(3);
  });
});

describe('a show', () => {
  test('addShowFavourite sends kind show and no look', async () => {
    await SavesEndpoints.addShowFavourite(SEASON, COLLECTION, '/img/1.jpg');
    const { method, body } = lastCall();
    expect(method).toBe('POST');
    expect(body).toEqual({
      kind: 'show',
      season: SEASON,
      collection: COLLECTION,
      image_path: '/img/1.jpg',
      notes: '',
    });
    expect(body.look).toBeUndefined();
  });

  // The server keys a show on season + collection. Sending a look number
  // would be ignored there, but sending one here would mean the caller
  // thought it mattered.
  test('removeShowFavourite sends no look number at all', async () => {
    await SavesEndpoints.removeShowFavourite('https://ex.com/f24', 'https://ex.com/bal');
    const { method, body } = lastCall();
    expect(method).toBe('DELETE');
    expect(body).toEqual({
      kind: 'show',
      season_url: 'https://ex.com/f24',
      collection_url: 'https://ex.com/bal',
    });
  });

  test('checkShowFavourite unwraps the answer to a boolean', async () => {
    fetchMock.mockResolvedValue({
      ok: true, statusText: 'OK', json: () => Promise.resolve({ is_favourite: true }),
    });
    await expect(
      SavesEndpoints.checkShowFavourite('https://ex.com/f24', 'https://ex.com/bal'),
    ).resolves.toBe(true);
    expect(lastCall().url).toBe(`${ApiClient.BASE_URL}/api/favourites/check`);
  });

  test('an absent is_favourite is false, not undefined', async () => {
    fetchMock.mockResolvedValue({
      ok: true, statusText: 'OK', json: () => Promise.resolve({}),
    });
    await expect(SavesEndpoints.checkShowFavourite('a', 'b')).resolves.toBe(false);
  });
});

describe('a view', () => {
  // A saved view IS its filters — the server hashes them to decide whether it
  // already has this view. Wrapping them, or adding anything beside them,
  // makes the same view save twice.
  test('addViewFavourite sends the filter object itself', async () => {
    await SavesEndpoints.addViewFavourite({ year: '1997', city: 'Paris' }, 'Paris 1997');
    const { body } = lastCall();
    expect(body).toEqual({
      kind: 'view',
      filters: { year: '1997', city: 'Paris' },
      name: 'Paris 1997',
    });
  });

  test('the filters are not wrapped in anything', async () => {
    await SavesEndpoints.addViewFavourite({ city: 'Paris' });
    expect(lastCall().body.filters).toEqual({ city: 'Paris' });
  });

  test('no name sends an empty one, and the server derives it', async () => {
    await SavesEndpoints.addViewFavourite({ city: 'Paris' });
    expect(lastCall().body.name).toBe('');
  });

  test('no filters is an empty object, never null', async () => {
    await SavesEndpoints.addViewFavourite(null);
    expect(lastCall().body.filters).toEqual({});
  });

  test('removeViewFavourite matches on the filters', async () => {
    await SavesEndpoints.removeViewFavourite({ city: 'Paris' });
    const { method, body } = lastCall();
    expect(method).toBe('DELETE');
    expect(body).toEqual({ kind: 'view', filters: { city: 'Paris' } });
  });

  test('checkViewFavourite unwraps the answer to a boolean', async () => {
    fetchMock.mockResolvedValue({
      ok: true, statusText: 'OK', json: () => Promise.resolve({ is_favourite: false }),
    });
    await expect(SavesEndpoints.checkViewFavourite({ city: 'Paris' })).resolves.toBe(false);
  });
});

describe('every delete goes through one place', () => {
  test('same URL, same method, same content type', async () => {
    await SavesEndpoints.removeFavourite('s', 'c', 1);
    await SavesEndpoints.removeShowFavourite('s', 'c');
    await SavesEndpoints.removeViewFavourite({ city: 'Paris' });
    for (const [url, options] of fetchMock.mock.calls) {
      expect(url).toBe(`${ApiClient.BASE_URL}/api/favourites`);
      expect(options.method).toBe('DELETE');
      expect(options.credentials).toBe('include');
      expect(options.headers['Content-Type']).toBe('application/json');
    }
  });

  test('a failed delete throws rather than reporting a silent success', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    fetchMock.mockResolvedValue({ ok: false, statusText: 'Bad Request' });
    await expect(SavesEndpoints.removeViewFavourite({ city: 'Paris' })).rejects.toThrow();
  });
});
