import { renderHook, act, waitFor } from '@testing-library/react';
import { FashionArchiveAPI } from '../api';
import {
  useSaves, lookKey, showKey, viewKey, canonicalFilters, keyOf, targetOfRow, rowOfTarget,
} from './useSaves';

// Two shows, each fully described, because the mistake this hook has to keep
// making impossible is a save written out of two of them at once. The writes
// are positional and two of a look's three arguments are urls, so a mixed
// triple names a row that exists, deletes it, and reports success.
const GUCCI = {
  season: { name: 'Spring 1999', url: 'https://ex.test/season/ss99', link_text: 'SS99' },
  collection: { designer: 'Gucci', url: 'https://ex.test/show/gucci-ss99' },
};

const PRADA = {
  season: { name: 'Fall 2001', url: 'https://ex.test/season/fw01', link_text: 'FW01' },
  collection: { designer: 'Prada', url: 'https://ex.test/show/prada-fw01' },
};

const look = (show, number, total = 40) => ({
  kind: 'look', ...show, look: { number, total }, imagePath: `x/look-${number}.jpg`,
});
const show = (s) => ({ kind: 'show', ...s, imagePath: 'x/look-1.jpg' });
const view = (filters, name) => ({ kind: 'view', filters, name });

// A row as GET /api/favourites returns one.
const row = (target) => rowOfTarget(target);

let api;
let errorLog;

beforeEach(() => {
  api = {
    getFavourites: jest.spyOn(FashionArchiveAPI, 'getFavourites').mockResolvedValue([]),
    addFavourite: jest.spyOn(FashionArchiveAPI, 'addFavourite').mockResolvedValue({}),
    removeFavourite: jest.spyOn(FashionArchiveAPI, 'removeFavourite').mockResolvedValue({}),
    addShowFavourite: jest.spyOn(FashionArchiveAPI, 'addShowFavourite').mockResolvedValue({}),
    removeShowFavourite:
      jest.spyOn(FashionArchiveAPI, 'removeShowFavourite').mockResolvedValue({}),
    addViewFavourite: jest.spyOn(FashionArchiveAPI, 'addViewFavourite').mockResolvedValue({}),
    removeViewFavourite:
      jest.spyOn(FashionArchiveAPI, 'removeViewFavourite').mockResolvedValue({}),
  };
  errorLog = jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => jest.restoreAllMocks());

const mount = async () => {
  const hook = renderHook(() => useSaves());
  await waitFor(() => expect(api.getFavourites).toHaveBeenCalled());
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  return hook;
};

// ── the three keys, on their own ──────────────────────────────────────────

describe('the key of a look', () => {
  test('is season, collection and number together', () => {
    expect(lookKey(look(GUCCI, 3))).toBe(lookKey(look(GUCCI, 3)));
    expect(lookKey(look(GUCCI, 3))).not.toBe(lookKey(look(GUCCI, 4)));
    expect(lookKey(look(GUCCI, 3))).not.toBe(lookKey(look(PRADA, 3)));
  });

  test('a different season is a different look', () => {
    const elsewhere = { ...GUCCI, season: { ...GUCCI.season, url: 'https://ex.test/other' } };
    expect(lookKey(look(GUCCI, 3))).not.toBe(lookKey(look(elsewhere, 3)));
  });

  test('the number is read as text, so 3 and "3" are one look', () => {
    expect(lookKey(look(GUCCI, 3))).toBe(lookKey(look(GUCCI, '3')));
  });

  test('a missing season url is the empty string the writer sends', () => {
    const noSeason = { ...GUCCI, season: {} };
    expect(lookKey(look(noSeason, 3))).toBe(lookKey(look({ ...GUCCI, season: { url: '' } }, 3)));
  });

  // The list response nests these, and reading the flat column names off it
  // once keyed every row as "undefined|undefined": nothing was marked kept
  // after a reload while the writes themselves looked fine.
  test('a row that names no look has no key at all', () => {
    expect(lookKey({ kind: 'look' })).toBeNull();
    expect(lookKey({ kind: 'look', collection: { url: 'u' } })).toBeNull();
    expect(lookKey({ kind: 'look', look: { number: 3 } })).toBeNull();
  });

  test('key number zero is a look, not a missing one', () => {
    expect(lookKey(look(GUCCI, 0))).not.toBeNull();
  });
});

describe('the key of a show', () => {
  test('is season and collection, with no number in it', () => {
    expect(showKey(show(GUCCI))).toBe(showKey({ kind: 'show', ...GUCCI }));
    expect(showKey(show(GUCCI))).not.toBe(showKey(show(PRADA)));
  });

  test('two looks of one show share the show key and not their own', () => {
    expect(showKey(look(GUCCI, 3))).toBe(showKey(look(GUCCI, 9)));
    expect(lookKey(look(GUCCI, 3))).not.toBe(lookKey(look(GUCCI, 9)));
  });

  test('a row that names no show has no key', () => {
    expect(showKey({ kind: 'show' })).toBeNull();
  });
});

describe('the key of a view', () => {
  // The server's identity is md5(view_filters::text) after
  // backend/userdata/favourites.py normalise_filters: known keys only,
  // trimmed, empty dropped, numbers as text. Each case below is one of that
  // function's rules.
  test('key order does not make two views', () => {
    expect(viewKey(view({ year: '1997', city: 'Paris' })))
      .toBe(viewKey(view({ city: 'Paris', year: '1997' })));
  });

  test('a number and its text are one view', () => {
    expect(viewKey(view({ year: 1997 }))).toBe(viewKey(view({ year: '1997' })));
  });

  test('empty and whitespace values are dropped', () => {
    expect(viewKey(view({ city: 'Paris', year: '' }))).toBe(viewKey(view({ city: 'Paris' })));
    expect(viewKey(view({ city: 'Paris', year: '  ' }))).toBe(viewKey(view({ city: 'Paris' })));
    expect(viewKey(view({ city: ' Paris ' }))).toBe(viewKey(view({ city: 'Paris' })));
  });

  test('unknown keys are dropped rather than making a second view', () => {
    expect(viewKey(view({ city: 'Paris', page: 3, t: Date.now() })))
      .toBe(viewKey(view({ city: 'Paris' })));
  });

  test('a value that is not a filter is dropped', () => {
    expect(viewKey(view({ city: 'Paris', year: ['1997'] })))
      .toBe(viewKey(view({ city: 'Paris' })));
    expect(viewKey(view({ city: 'Paris', year: true }))).toBe(viewKey(view({ city: 'Paris' })));
    expect(viewKey(view({ city: 'Paris', year: { a: 1 } })))
      .toBe(viewKey(view({ city: 'Paris' })));
  });

  test('no filters at all is the whole archive, and one view', () => {
    expect(viewKey(view({}))).toBe(viewKey(view(null)));
    expect(viewKey(view(undefined))).toBe(viewKey(view({ page: 2 })));
  });

  test('different filters are different views', () => {
    expect(viewKey(view({ city: 'Paris' }))).not.toBe(viewKey(view({ city: 'Milan' })));
    expect(viewKey(view({ city: 'Paris' }))).not.toBe(viewKey(view({ year: 'Paris' })));
    expect(viewKey(view({ city: 'Paris' }))).not.toBe(viewKey(view({})));
  });

  // Restated from backend/userdata/favourites.py FILTER_KEYS. The server keeps
  // its own copy for the same reason: a key one side knows and the other drops
  // makes the same view two rows, one of which can never be matched again.
  test('the seven filters the server will store are the seven kept here', () => {
    const server = ['gender', 'year', 'season', 'city', 'category', 'shootType', 'letter'];
    const all = Object.fromEntries(server.map(k => [k, 'x']));
    expect(canonicalFilters(all)).toEqual(all);
    expect(Object.keys(canonicalFilters({ ...all, nope: 'x' }))).toHaveLength(server.length);
  });
});

describe('a key names one kind and never another', () => {
  // The show key is season + collection and the look key is those plus a
  // number, so a careless key would make one a prefix of the other and a
  // saved show would light every look in it.
  test('a saved show and a saved look of it are different keys', () => {
    expect(keyOf(show(GUCCI))).not.toBe(keyOf(look(GUCCI, 1)));
  });

  test('a row with no kind is a look, as the server reads it', () => {
    expect(keyOf({ collection: GUCCI.collection, season: GUCCI.season, look: { number: 3 } }))
      .toBe(keyOf(look(GUCCI, 3)));
  });

  test('an optimistic row keys exactly as the row the server returns', () => {
    for (const target of [look(GUCCI, 3), show(PRADA), view({ city: 'Paris' })]) {
      expect(keyOf(targetOfRow(rowOfTarget(target)))).toBe(keyOf(target));
    }
  });

  test('nothing is not a key', () => {
    expect(keyOf(null)).toBeNull();
    expect(keyOf({ kind: 'nonsense' })).toBeNull();
  });
});

// ── the hook ──────────────────────────────────────────────────────────────

describe('what is already saved', () => {
  test('marks each kind from the rows the server sent', async () => {
    api.getFavourites.mockResolvedValue([
      row(look(GUCCI, 3)), row(show(PRADA)), row(view({ city: 'Paris' })),
    ]);
    const { result } = await mount();

    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
    expect(result.current.isSaved(look(GUCCI, 4))).toBe(false);
    expect(result.current.isSaved(show(PRADA))).toBe(true);
    expect(result.current.isSaved(show(GUCCI))).toBe(false);
    expect(result.current.isSaved(view({ city: 'Paris' }))).toBe(true);
    expect(result.current.isSaved(view({ city: 'Milan' }))).toBe(false);
    expect(result.current.saves).toHaveLength(3);
  });

  test('a saved view is recognised however its filters are spelled', async () => {
    api.getFavourites.mockResolvedValue([row(view({ city: 'Paris', year: '1997' }))]);
    const { result } = await mount();
    expect(result.current.isSaved(view({ year: 1997, city: ' Paris ', page: 4 }))).toBe(true);
  });

  test('loading is true until the rows land, and error stays null', async () => {
    const { result } = renderHook(() => useSaves());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });
});

// The one most likely to be got subtly wrong, in both directions.
describe('a show and its looks are independent', () => {
  test('saving the whole show stars no look in it', async () => {
    const { result } = await mount();

    await act(async () => { await result.current.toggle(show(GUCCI)); });

    expect(api.addShowFavourite).toHaveBeenCalledTimes(1);
    expect(api.addFavourite).not.toHaveBeenCalled();
    expect(result.current.isSaved(show(GUCCI))).toBe(true);
    expect(result.current.isSaved(look(GUCCI, 1))).toBe(false);
    expect(result.current.isSaved(look(GUCCI, 40))).toBe(false);
  });

  test('unsaving a look leaves the show saved', async () => {
    api.getFavourites.mockResolvedValue([row(show(GUCCI)), row(look(GUCCI, 3))]);
    const { result } = await mount();
    expect(result.current.isSaved(show(GUCCI))).toBe(true);

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(api.removeFavourite).toHaveBeenCalledTimes(1);
    expect(api.removeShowFavourite).not.toHaveBeenCalled();
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);
    expect(result.current.isSaved(show(GUCCI))).toBe(true);
  });

  test('unsaving the show leaves its saved look alone', async () => {
    api.getFavourites.mockResolvedValue([row(show(GUCCI)), row(look(GUCCI, 3))]);
    const { result } = await mount();

    await act(async () => { await result.current.toggle(show(GUCCI)); });

    expect(api.removeShowFavourite).toHaveBeenCalledTimes(1);
    expect(api.removeFavourite).not.toHaveBeenCalled();
    expect(result.current.isSaved(show(GUCCI))).toBe(false);
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
  });

  test('saving a look stars no other look and not the show', async () => {
    const { result } = await mount();

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
    expect(result.current.isSaved(look(GUCCI, 4))).toBe(false);
    expect(result.current.isSaved(show(GUCCI))).toBe(false);
  });
});

describe('what each kind puts on the wire', () => {
  // removeFavourite(seasonUrl, collectionUrl, lookNumber) is positional and
  // two of the three are urls. All three come off the one target.
  test('a look is deleted with all three arguments off one show', async () => {
    api.getFavourites.mockResolvedValue([row(look(GUCCI, 3)), row(look(PRADA, 3))]);
    const { result } = await mount();

    await act(async () => { await result.current.toggle(look(PRADA, 3)); });

    expect(api.removeFavourite).toHaveBeenCalledWith(
      PRADA.season.url, PRADA.collection.url, 3);
    expect(api.removeFavourite.mock.calls[0][0]).not.toBe(GUCCI.season.url);
    expect(api.removeFavourite.mock.calls[0][1]).not.toBe(GUCCI.collection.url);
  });

  test('a look is saved with the season, collection and look it was given', async () => {
    const { result } = await mount();
    await act(async () => { await result.current.toggle(look(PRADA, 7, 27)); });
    expect(api.addFavourite).toHaveBeenCalledWith(
      PRADA.season, PRADA.collection, { number: 7, total: 27 }, 'x/look-7.jpg');
  });

  test('a show sends no look number in either direction', async () => {
    const { result } = await mount();
    await act(async () => { await result.current.toggle(show(PRADA)); });
    expect(api.addShowFavourite)
      .toHaveBeenCalledWith(PRADA.season, PRADA.collection, 'x/look-1.jpg');

    api.getFavourites.mockResolvedValue([row(show(PRADA))]);
    const second = await mount();
    await act(async () => { await second.result.current.toggle(show(PRADA)); });
    expect(api.removeShowFavourite)
      .toHaveBeenCalledWith(PRADA.season.url, PRADA.collection.url);
  });

  // Saving through one rule and deleting through another is how a view
  // becomes undeletable, so both ends send the filters this client keyed on.
  test('a view sends the filters it was keyed on, canonical, both ways', async () => {
    const { result } = await mount();
    await act(async () => {
      await result.current.toggle(view({ city: ' Paris ', year: 1997, page: 2 }, 'Paris 1997'));
    });
    expect(api.addViewFavourite)
      .toHaveBeenCalledWith({ city: 'Paris', year: '1997' }, 'Paris 1997');

    api.getFavourites.mockResolvedValue([row(view({ city: 'Paris', year: '1997' }))]);
    const second = await mount();
    await act(async () => {
      await second.result.current.toggle(view({ year: 1997, city: ' Paris ' }));
    });
    expect(api.removeViewFavourite).toHaveBeenCalledWith({ city: 'Paris', year: '1997' });
  });

  test('a target that names nothing is not a write', async () => {
    const { result } = await mount();
    await act(async () => { await result.current.toggle({ kind: 'look' }); });
    await act(async () => { await result.current.toggle(null); });
    expect(api.addFavourite).not.toHaveBeenCalled();
    expect(api.removeFavourite).not.toHaveBeenCalled();
  });
});

describe('a write that fails puts back exactly what was there', () => {
  const cases = [
    ['a look', () => look(GUCCI, 3), 'addFavourite', 'removeFavourite'],
    ['a show', () => show(GUCCI), 'addShowFavourite', 'removeShowFavourite'],
    ['a view', () => view({ city: 'Paris' }), 'addViewFavourite', 'removeViewFavourite'],
  ];

  test.each(cases)('%s that will not save is unstarred again', async (_name, target, add) => {
    api[add].mockRejectedValue(new Error('nope'));
    // Something of every kind is already saved, so a rollback that rebuilt
    // the list rather than restoring it would show up here.
    const before = [row(look(PRADA, 9)), row(show(PRADA)), row(view({ city: 'Milan' }))];
    api.getFavourites.mockResolvedValue(before);
    const { result } = await mount();

    await act(async () => { await result.current.toggle(target()); });

    expect(result.current.isSaved(target())).toBe(false);
    expect(result.current.saves).toEqual(before);
    expect(result.current.isSaved(look(PRADA, 9))).toBe(true);
    expect(result.current.isSaved(show(PRADA))).toBe(true);
    expect(result.current.isSaved(view({ city: 'Milan' }))).toBe(true);
    expect(result.current.error).toBeTruthy();
    expect(errorLog).toHaveBeenCalled();
  });

  test.each(cases)('%s that will not delete is starred again', async (_name, target, _a, del) => {
    api[del].mockRejectedValue(new Error('nope'));
    const before = [row(target()), row(look(PRADA, 9)), row(show(PRADA))];
    api.getFavourites.mockResolvedValue(before);
    const { result } = await mount();
    expect(result.current.isSaved(target())).toBe(true);

    await act(async () => { await result.current.toggle(target()); });

    expect(result.current.isSaved(target())).toBe(true);
    expect(result.current.saves).toEqual(before);
    expect(result.current.isSaved(look(PRADA, 9))).toBe(true);
    expect(result.current.isSaved(show(PRADA))).toBe(true);
  });

  test('a later write that works clears the error', async () => {
    api.addFavourite.mockRejectedValueOnce(new Error('nope'));
    const { result } = await mount();
    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });
    expect(result.current.error).toBeTruthy();

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });
    expect(result.current.error).toBeNull();
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
  });
});

// The optimistic marker is what makes a double press dangerous: the second
// press reads the marker the first one moved and would send the opposite
// write against a row the server has not heard about yet.
test('one write at a time, across kinds', async () => {
  api.addFavourite.mockImplementation(() => new Promise(() => {}));   // never settles
  const { result } = await mount();

  await act(async () => { result.current.toggle(look(GUCCI, 3)); });
  await act(async () => { result.current.toggle(show(GUCCI)); });
  await act(async () => { result.current.toggle(view({ city: 'Paris' })); });

  expect(api.addFavourite).toHaveBeenCalledTimes(1);
  expect(api.addShowFavourite).not.toHaveBeenCalled();
  expect(api.addViewFavourite).not.toHaveBeenCalled();
});

test('a list that will not load leaves an error and an empty set', async () => {
  api.getFavourites.mockRejectedValue(new Error('down'));
  const { result } = await mount();
  expect(result.current.saves).toEqual([]);
  expect(result.current.error).toBeTruthy();
  expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);
});
