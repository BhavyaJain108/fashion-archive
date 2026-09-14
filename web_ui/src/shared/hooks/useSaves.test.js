import { renderHook, act, waitFor } from '@testing-library/react';
import { FashionArchiveAPI } from '../api';
import {
  useSaves, PAGE_SIZE,
  lookKey, showKey, viewKey, canonicalFilters, keyOf, targetOfRow, rowOfTarget,
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

// The hook reads the table twice: the keys, whole, and the rows, a page at a
// time. `seed` sets both from one list of rows, because in the real server they
// ARE one list — a key is a row with the display fields left off. The tests
// that care about the split say so by seeding the two differently themselves.
const seed = (rows) => {
  api.getFavouriteKeys.mockResolvedValue(rows);
  api.getFavouritesPage.mockResolvedValue({
    favourites: rows, total: rows.length, hasMore: false, nextCursor: null,
  });
};

beforeEach(() => {
  api = {
    getFavouriteKeys:
      jest.spyOn(FashionArchiveAPI, 'getFavouriteKeys').mockResolvedValue([]),
    getFavouritesPage: jest.spyOn(FashionArchiveAPI, 'getFavouritesPage')
      .mockResolvedValue({ favourites: [], total: 0, hasMore: false, nextCursor: null }),
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

// `{ withRows: true }`, because most of what is asserted below is about the
// rows — the shelf half — and they are opt-in now. The keys come whole on
// every mount; the rows come only for a caller that draws them, which is what
// `describe('the rows are asked for only by a caller that draws them')`
// pins. Nothing else in this file is about that choice, so it is made once,
// here, rather than in fifty mounts.
const mount = async (options = { withRows: true }) => {
  const hook = renderHook(() => useSaves(options));
  await waitFor(() => expect(api.getFavouriteKeys).toHaveBeenCalled());
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

// ── the show's own id, riding along ───────────────────────────────────────
//
// Rows now carry `collection.id` — firstVIEW's id for the show, derived by the
// server from collection_url. It is the identity the two phase-3 bugs would not
// have had, and the one the archive page already uses everywhere else. The keys
// here must stay the server's unique indexes restated, and those are still the
// URL ones, so the id is carried and not keyed on.

describe("the show's id on a saved row", () => {
  const WITH_ID = {
    season: GUCCI.season,
    collection: { ...GUCCI.collection, id: '12345' },
  };

  test('is not part of any key', () => {
    expect(lookKey(look(WITH_ID, 3))).toBe(lookKey(look(GUCCI, 3)));
    expect(showKey(show(WITH_ID))).toBe(showKey(show(GUCCI)));
  });

  // The bug this guards against is the tempting one: swapping the client key
  // to the id while the server still keys on the url. The star would light off
  // the id and the delete would go out with a url the server matches
  // differently, which is the phase-3 failure with the two halves swapped.
  test('two spellings of one show are still two rows here, as on the server', () => {
    const listUrl = 'https://www.firstview.com/collection_images.php?id=12345&list=all';
    const drawerUrl = 'https://www.firstview.com/collection_images.php?id=12345';
    const fromList = { season: GUCCI.season, collection: { designer: 'G', url: listUrl, id: '12345' } };
    const fromDrawer = { season: GUCCI.season, collection: { designer: 'G', url: drawerUrl, id: '12345' } };
    expect(lookKey(look(fromList, 3))).not.toBe(lookKey(look(fromDrawer, 3)));
  });

  test('survives the row and target round trip, so it is there when the key moves', () => {
    const back = targetOfRow(rowOfTarget(look(WITH_ID, 3)));
    expect(back.collection.id).toBe('12345');
  });

  test('a row the server sent without one still keys', () => {
    expect(keyOf(targetOfRow(row(look(GUCCI, 3))))).toBe(keyOf(look(GUCCI, 3)));
  });

  test('an optimistic row and the server row for one look key alike, id or not', async () => {
    seed([row(look(WITH_ID, 3))]);
    const { result } = await mount();
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
  });
});

// ── the hook ──────────────────────────────────────────────────────────────

describe('what is already saved', () => {
  test('marks each kind from the rows the server sent', async () => {
    seed([
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
    seed([row(view({ city: 'Paris', year: '1997' }))]);
    const { result } = await mount();
    expect(result.current.isSaved(view({ year: 1997, city: ' Paris ', page: 4 }))).toBe(true);
  });

  test('loading is true until the rows land, and error stays null', async () => {
    const { result } = renderHook(() => useSaves({ withRows: true }));
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });
});

// ── when the keys never arrive ────────────────────────────────────────────
//
// `getFavouriteKeys` rethrows precisely so a caller can report this, and for
// a while nobody did. An empty key set and a failed one look identical on
// screen: every star reads dark. The reader presses one, the server answers
// "Already in favourites" — which this hook deliberately does not roll back,
// because a dark star over a saved row is the same bug pointing the other
// way — and the press after that goes out as a DELETE and takes the save.
//
// So a star whose state is unknown does not write at all. Not the add, which
// would be a second save of a row the server already holds, and above all not
// the delete, which is the one press here that destroys something.

describe('a key load that failed', () => {
  const dead = () => {
    api.getFavouriteKeys.mockRejectedValue(new Error('session gone'));
  };

  const mountDead = async () => {
    const hook = renderHook(() => useSaves());
    await waitFor(() => expect(hook.result.current.loading).toBe(false));
    return hook;
  };

  test('is reported rather than swallowed into an empty library', async () => {
    dead();
    const { result } = await mountDead();

    expect(result.current.error).toBeTruthy();
    // And the list is left alone rather than being answered as "nothing
    // saved", which is what an all-dark star field would otherwise mean.
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);
  });

  test('a press writes nothing, because nothing here knows what is saved', async () => {
    dead();
    const { result } = await mountDead();

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(api.addFavourite).not.toHaveBeenCalled();
    expect(api.removeFavourite).not.toHaveBeenCalled();
  });

  test('and the second press does not delete the save', async () => {
    dead();
    const { result } = await mountDead();

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });
    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    // THE press this guard exists for. Without it the first press flips the
    // marker to lit, and the second reads that marker and sends a delete for
    // a row the reader never asked to lose.
    expect(api.removeFavourite).not.toHaveBeenCalled();
    expect(api.addFavourite).not.toHaveBeenCalled();
  });

  test('a show and a view are refused on the same ground', async () => {
    dead();
    const { result } = await mountDead();

    await act(async () => { await result.current.toggle(show(GUCCI)); });
    await act(async () => { await result.current.toggle(view({ city: 'Paris' })); });

    expect(api.addShowFavourite).not.toHaveBeenCalled();
    expect(api.removeShowFavourite).not.toHaveBeenCalled();
    expect(api.addViewFavourite).not.toHaveBeenCalled();
    expect(api.removeViewFavourite).not.toHaveBeenCalled();
  });

  test('once the keys do arrive, the star writes again', async () => {
    dead();
    const { result } = await mountDead();
    api.getFavouriteKeys.mockResolvedValue([]);

    await act(async () => { await result.current.reload(); });
    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(api.addFavourite).toHaveBeenCalledTimes(1);
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
    seed([row(show(GUCCI)), row(look(GUCCI, 3))]);
    const { result } = await mount();
    expect(result.current.isSaved(show(GUCCI))).toBe(true);

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(api.removeFavourite).toHaveBeenCalledTimes(1);
    expect(api.removeShowFavourite).not.toHaveBeenCalled();
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);
    expect(result.current.isSaved(show(GUCCI))).toBe(true);
  });

  test('unsaving the show leaves its saved look alone', async () => {
    seed([row(show(GUCCI)), row(look(GUCCI, 3))]);
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
    seed([row(look(GUCCI, 3)), row(look(PRADA, 3))]);
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

    seed([row(show(PRADA))]);
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

    seed([row(view({ city: 'Paris', year: '1997' }))]);
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
    seed(before);
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
    seed(before);
    const { result } = await mount();
    expect(result.current.isSaved(target())).toBe(true);

    await act(async () => { await result.current.toggle(target()); });

    expect(result.current.isSaved(target())).toBe(true);
    expect(result.current.saves).toEqual(before);
    expect(result.current.isSaved(look(PRADA, 9))).toBe(true);
    expect(result.current.isSaved(show(PRADA))).toBe(true);
  });

  // ── the server answering 200 with a refusal ────────────────────────────
  //
  // A rejected promise is not the only way a write fails. The API answers a
  // delete that matched nothing with HTTP 200 and
  // {"success": false, "message": "Not found in favourites"}, so `callPython`
  // resolves and, before this, the star went dark while the row stayed in the
  // database. LibraryPage already read `result.success` on the same endpoint;
  // this hook did not, which is what made the recents key split silent rather
  // than noisy.

  const deleteCases = [
    ['a look', () => look(GUCCI, 3), 'removeFavourite'],
    ['a show', () => show(GUCCI), 'removeShowFavourite'],
    ['a view', () => view({ city: 'Paris' }), 'removeViewFavourite'],
  ];

  test.each(deleteCases)('%s the server would not delete stays starred',
    async (_name, target, del) => {
      api[del].mockResolvedValue({ success: false, message: 'Not found in favourites' });
      const before = [row(target()), row(look(PRADA, 9)), row(show(PRADA))];
      seed(before);
      const { result } = await mount();
      expect(result.current.isSaved(target())).toBe(true);

      await act(async () => { await result.current.toggle(target()); });

      expect(result.current.isSaved(target())).toBe(true);
      expect(result.current.saves).toEqual(before);
      expect(result.current.error).toBeTruthy();
      expect(errorLog).toHaveBeenCalled();
    });

  test('the reason the server gave is the reason that surfaces', async () => {
    api.removeFavourite.mockResolvedValue({
      success: false, message: 'Not found in favourites',
    });
    seed([row(look(GUCCI, 3))]);
    const { result } = await mount();

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(String(result.current.error.message)).toContain('Not found in favourites');
  });

  // The other direction is not a failure and must not be rolled back. The
  // server answers an add for a row it already holds with the same
  // `success: false`, meaning "Already in favourites" — the state the press
  // asked for. Un-starring it would be the very bug above, pointing the other
  // way: a star dark over a row that is saved.
  test.each([
    ['a look', () => look(GUCCI, 3), 'addFavourite'],
    ['a show', () => show(GUCCI), 'addShowFavourite'],
    ['a view', () => view({ city: 'Paris' }), 'addViewFavourite'],
  ])('%s the server already had stays starred', async (_name, target, add) => {
    api[add].mockResolvedValue({ success: false, message: 'Already in favourites' });
    const { result } = await mount();

    await act(async () => { await result.current.toggle(target()); });

    expect(result.current.isSaved(target())).toBe(true);
    expect(result.current.error).toBeNull();
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

// ── one write at a time, per saved thing ─────────────────────────────────
//
// The flag this replaced was global: one write anywhere, and every other
// star on the page was inert until it landed. With the star in four places
// that is a lost click, silently — keep a show while a look's write is still
// out and the look you starred a moment earlier is simply not written.

test('different things are written at the same time', async () => {
  api.addFavourite.mockImplementation(() => new Promise(() => {}));   // never settles
  const { result } = await mount();

  await act(async () => { result.current.toggle(look(GUCCI, 3)); });
  await act(async () => { result.current.toggle(show(GUCCI)); });
  await act(async () => { result.current.toggle(view({ city: 'Paris' })); });

  // The look's write is still out and neither of the others waited for it.
  expect(api.addFavourite).toHaveBeenCalledTimes(1);
  expect(api.addShowFavourite).toHaveBeenCalledTimes(1);
  expect(api.addViewFavourite).toHaveBeenCalledTimes(1);
  // And all three are lit, on one list.
  expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
  expect(result.current.isSaved(show(GUCCI))).toBe(true);
  expect(result.current.isSaved(view({ city: 'Paris' }))).toBe(true);
});

// The optimistic marker is what makes a double press on ONE star dangerous:
// the second press reads the marker the first one moved and would send the
// opposite write against a row the server has not heard about yet.
test('a second press on the same star waits for the first', async () => {
  let settleAdd;
  api.addFavourite.mockImplementation(() => new Promise((res) => { settleAdd = res; }));
  const { result } = await mount();

  await act(async () => { result.current.toggle(look(GUCCI, 3)); });
  await act(async () => { result.current.toggle(look(GUCCI, 3)); });

  // One write out, the second press not sent alongside it.
  expect(api.addFavourite).toHaveBeenCalledTimes(1);
  expect(api.removeFavourite).not.toHaveBeenCalled();

  // And not dropped either: it runs the moment the first one lands.
  await act(async () => { settleAdd({}); });
  await waitFor(() => expect(api.removeFavourite).toHaveBeenCalledTimes(1));
  expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);
});

test('a held press is the last one, not every one', async () => {
  let settleAdd;
  api.addFavourite.mockImplementation(() => new Promise((res) => { settleAdd = res; }));
  const { result } = await mount();

  // Star, un-star, star again while the first write is still out. Two and
  // three are the same star; what the reader asked for in the end is saved,
  // and the middle state is not a state they ever asked to end up in.
  await act(async () => { result.current.toggle(look(GUCCI, 3)); });
  await act(async () => { result.current.toggle(look(GUCCI, 3)); });
  await act(async () => { result.current.toggle(look(GUCCI, 3)); });

  await act(async () => { settleAdd({}); });
  await waitFor(() => expect(api.addFavourite).toHaveBeenCalledTimes(2));
  expect(api.removeFavourite).not.toHaveBeenCalled();
  expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
});

test('a list that will not load leaves an error and an empty set', async () => {
  api.getFavouriteKeys.mockRejectedValue(new Error('down'));
  const { result } = await mount();
  expect(result.current.saves).toEqual([]);
  expect(result.current.error).toBeTruthy();
  expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);
});

// ── setSaved: the marker, moved, with nothing sent ────────────────────────
//
// The collaborator `useAlbums` takes. The album endpoint saves and files in
// one transaction, so when it answers the row exists and there is nothing
// left to send — only a star to light. Anything here that reached for the
// favourites API would be a second add of a row the server already has.

// ── telling the rest of the app a save is gone ────────────────────────────
//
// Unsaving something does not only empty a star. `album_items` is ON DELETE
// CASCADE on the favourite, so the server takes the row out of every album it
// was in, in the same statement — and nothing on the client is asked. The
// album shelf goes on showing the count it had before.
//
// `LibraryPage` re-reads the shelf after its own delete for exactly this
// reason. The archive page has the same delete, on the star, and had no way
// to hear about it: a look starred, filed into Resort, then unstarred left
// the shelf saying 1 over an album holding 0, and the next add to that album
// counted up from the wrong number and stayed wrong until the page remounted.
//
// So this hook — the one owner of the saved list — announces a delete that
// the SERVER has actually made. `useAlbums` listens, and re-reads. It does
// not get a copy of the list, because two owners of that list is the bug this
// whole split exists to prevent.

describe('a delete announces itself', () => {
  const heard = () => {
    const calls = [];
    return { calls, fn: jest.fn(key => calls.push(key)) };
  };

  test('a listener hears the key of a save the server removed', async () => {
    seed([row(look(GUCCI, 3))]);
    const { result } = await mount();
    const listener = heard();
    act(() => { result.current.onUnsaved(listener.fn); });

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(listener.fn).toHaveBeenCalledTimes(1);
    expect(listener.calls[0]).toBe(keyOf(look(GUCCI, 3)));
  });

  test('an add announces nothing — nothing cascaded', async () => {
    const { result } = await mount();
    const listener = heard();
    act(() => { result.current.onUnsaved(listener.fn); });

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(listener.fn).not.toHaveBeenCalled();
  });

  // The announcement is about what the SERVER did. A delete that was refused
  // or never went out is rolled back here, and a listener told about it would
  // re-read a shelf that had not changed — or, worse, act on a removal that
  // did not happen.
  test('a delete the server refused announces nothing', async () => {
    seed([row(look(GUCCI, 3))]);
    api.removeFavourite.mockResolvedValue(
      { success: false, message: 'Not found in favourites' });
    const { result } = await mount();
    const listener = heard();
    act(() => { result.current.onUnsaved(listener.fn); });

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(listener.fn).not.toHaveBeenCalled();
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
  });

  // `setSaved` moves a marker and sends nothing — it exists for the album add,
  // whose server transaction has already done the saving. Nothing was deleted,
  // so there is nothing to announce, in either direction.
  test('a marker moved without a write announces nothing', async () => {
    seed([row(look(GUCCI, 3))]);
    const { result } = await mount();
    const listener = heard();
    act(() => { result.current.onUnsaved(listener.fn); });

    act(() => { result.current.setSaved(look(GUCCI, 3), false); });

    expect(listener.fn).not.toHaveBeenCalled();
  });

  test('a listener that has gone is not called', async () => {
    seed([row(look(GUCCI, 3)), row(look(GUCCI, 4))]);
    const { result } = await mount();
    const listener = heard();
    let stop;
    act(() => { stop = result.current.onUnsaved(listener.fn); });
    act(() => { stop(); });

    await act(async () => { await result.current.toggle(look(GUCCI, 3)); });

    expect(listener.fn).not.toHaveBeenCalled();
  });

  test('subscribing does not change identity on every render', async () => {
    const { result, rerender } = await mount();
    const first = result.current.onUnsaved;
    rerender();
    expect(result.current.onUnsaved).toBe(first);
  });
});

describe('setSaved', () => {
  test('lights a star without sending anything', async () => {
    const { result } = await mount();
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);

    act(() => { result.current.setSaved(look(GUCCI, 3), true); });

    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
    expect(api.addFavourite).not.toHaveBeenCalled();
    expect(api.removeFavourite).not.toHaveBeenCalled();
  });

  test('puts one out again, and only the one', async () => {
    const { result } = await mount();
    act(() => { result.current.setSaved(look(GUCCI, 3), true); });
    act(() => { result.current.setSaved(look(PRADA, 3), true); });

    act(() => { result.current.setSaved(look(GUCCI, 3), false); });

    expect(result.current.isSaved(look(GUCCI, 3))).toBe(false);
    expect(result.current.isSaved(look(PRADA, 3))).toBe(true);
    expect(api.removeFavourite).not.toHaveBeenCalled();
  });

  test('asked for the state the list is already in, it does nothing', async () => {
    seed([row(look(GUCCI, 3))]);
    const { result } = await mount();
    const before = result.current.saves;

    act(() => { result.current.setSaved(look(GUCCI, 3), true); });

    // The same array, untouched. A second row for a look already in the list
    // is how a rollback later takes out a star somebody else lit.
    expect(result.current.saves).toBe(before);
    expect(result.current.saves).toHaveLength(1);
  });

  test('a target that names nothing moves nothing', async () => {
    const { result } = await mount();
    act(() => { result.current.setSaved({ kind: 'look', look: { number: 1 } }, true); });
    expect(result.current.saves).toHaveLength(0);
  });

  test('all three kinds, keyed the way the star reads them', async () => {
    const { result } = await mount();
    act(() => {
      result.current.setSaved(show(GUCCI), true);
      result.current.setSaved(view({ year: '2020' }, 'Twenty'), true);
    });

    expect(result.current.isSaved(show(GUCCI))).toBe(true);
    expect(result.current.isSaved(view({ year: '2020' }))).toBe(true);
    // A saved show is not a saved look of it.
    expect(result.current.isSaved(look(GUCCI, 1))).toBe(false);
  });
});

// ── The trap: a star over a row on a page nobody fetched ──────────────────
//
// This is the whole reason the keys and the rows are two readings. Before the
// split, `isSaved` answered off the fetched list — so capping or paging that
// list meant a look the reader had saved read as UNSAVED the moment its row
// fell past the first page. The star drew dark over something they kept, and
// pressing it sent an ADD the server answers "Already in favourites" for.
//
// The fixtures below make the two readings disagree deliberately: the page
// holds one row, the keys hold three. Nothing but the split can pass these.

describe('a save whose row is on a page that has not been fetched', () => {
  const PAGE_ONE = [row(look(GUCCI, 3))];
  const EVERYTHING = [row(look(GUCCI, 3)), row(look(PRADA, 9)), row(show(PRADA))];

  const mountPaged = async () => {
    api.getFavouriteKeys.mockResolvedValue(EVERYTHING);
    api.getFavouritesPage.mockResolvedValue({
      favourites: PAGE_ONE, total: 3, hasMore: true, nextCursor: 'c1',
    });
    return mount();
  };

  test('reads as saved anyway', async () => {
    const { result } = await mountPaged();

    // On the page, and lit.
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
    // NOT on the page, and lit — which is the bug this task closes.
    expect(result.current.isSaved(look(PRADA, 9))).toBe(true);
    expect(result.current.isSaved(show(PRADA))).toBe(true);
    // And the rows really are only the first page, so the test is not passing
    // because everything happened to be fetched after all.
    expect(result.current.saves).toHaveLength(1);
    expect(result.current.total).toBe(3);
    expect(result.current.hasMore).toBe(true);
  });

  test('something genuinely unsaved still reads dark', async () => {
    const { result } = await mountPaged();

    // The keys are the answer, so they have to be able to say no. A hook that
    // answered "saved" to everything would pass the test above.
    expect(result.current.isSaved(look(GUCCI, 4))).toBe(false);
    expect(result.current.isSaved(show(GUCCI))).toBe(false);
    expect(result.current.isSaved(view({ city: 'Paris' }))).toBe(false);
  });

  test('pressing its star UNSAVES it rather than saving it a second time',
    async () => {
      const { result } = await mountPaged();

      await act(async () => { await result.current.toggle(look(PRADA, 9)); });

      // The direction is read off the keys, not off the page. Off the page it
      // would have looked unsaved and this would have been an add.
      expect(api.removeFavourite).toHaveBeenCalledWith(
        PRADA.season.url, PRADA.collection.url, 9);
      expect(api.addFavourite).not.toHaveBeenCalled();
      expect(result.current.isSaved(look(PRADA, 9))).toBe(false);
    });

  test('the keys are asked for whole — no limit, no cursor', async () => {
    await mountPaged();

    // There is no page of keys to ask for, and a `limit` creeping in here is
    // the bug coming back by another door.
    expect(api.getFavouriteKeys).toHaveBeenCalledWith();
    expect(api.getFavouriteKeys).toHaveBeenCalledTimes(1);
  });
});

// ── what a mount actually costs ───────────────────────────────────────────
//
// The keys and the rows were split so the archive page would stop fetching
// the library to draw none of it — and then both halves were fetched on every
// mount anyway, so the page made two requests where it had made one and
// discarded two hundred rows instead of all of them. Only `useFavourites`
// calls this hook, and it reads `isSaved`, `setSaved` and `toggle`: every one
// of those is a function of the KEYS. `saves`, `total`, `hasMore` and
// `loadMore` had no caller at all.
//
// So the rows are opt-in. The keys stay eager, because the star needs them
// and there is no page of them to ask for.

describe('the rows are asked for only by a caller that draws them', () => {
  const mountBare = async () => {
    const hook = renderHook(() => useSaves());
    await waitFor(() => expect(hook.result.current.loading).toBe(false));
    return hook;
  };

  test('a plain mount fetches the keys and nothing else', async () => {
    seed([row(look(GUCCI, 3)), row(look(PRADA, 9))]);
    const { result } = await mountBare();

    expect(api.getFavouriteKeys).toHaveBeenCalledTimes(1);
    expect(api.getFavouritesPage).not.toHaveBeenCalled();

    // And the star is right about every one of them, which is the whole
    // point of the split: the keys are complete.
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
    expect(result.current.isSaved(look(PRADA, 9))).toBe(true);
    expect(result.current.isSaved(look(GUCCI, 4))).toBe(false);
    expect(result.current.saves).toEqual([]);
  });

  test('loadRows fetches the first page when one is actually wanted', async () => {
    seed([row(look(GUCCI, 3)), row(look(PRADA, 9))]);
    const { result } = await mountBare();

    await act(async () => { await result.current.loadRows(); });

    expect(api.getFavouritesPage).toHaveBeenCalledWith({ limit: PAGE_SIZE });
    expect(result.current.saves).toHaveLength(2);
    expect(result.current.total).toBe(2);
  });

  test('a reload after that keeps fetching them', async () => {
    seed([row(look(GUCCI, 3))]);
    const { result } = await mountBare();
    await act(async () => { await result.current.loadRows(); });

    await act(async () => { await result.current.reload(); });

    expect(api.getFavouritesPage).toHaveBeenCalledTimes(2);
    expect(result.current.saves).toHaveLength(1);
  });

  test('a reload before that still does not', async () => {
    const { result } = await mountBare();

    await act(async () => { await result.current.reload(); });

    expect(api.getFavouriteKeys).toHaveBeenCalledTimes(2);
    expect(api.getFavouritesPage).not.toHaveBeenCalled();
  });

  test('asked for them at mount, the mount fetches both', async () => {
    seed([row(look(GUCCI, 3))]);
    const { result } = await mount();

    expect(api.getFavouritesPage).toHaveBeenCalledWith({ limit: PAGE_SIZE });
    expect(result.current.saves).toHaveLength(1);
  });

  // A page that failed to load rows must not report the library as ending
  // here, and must not lose the error.
  test('a first page that fails is reported and leaves the keys alone', async () => {
    seed([row(look(GUCCI, 3))]);
    api.getFavouritesPage.mockRejectedValue(new Error('down'));
    const { result } = await mountBare();

    await act(async () => { await result.current.loadRows(); });

    expect(result.current.error).toBeTruthy();
    expect(result.current.isSaved(look(GUCCI, 3))).toBe(true);
  });
});

// ── Paging the rows ───────────────────────────────────────────────────────

describe('the rows come a page at a time', () => {
  const PAGE_ONE = [row(look(GUCCI, 3)), row(look(GUCCI, 4))];
  const PAGE_TWO = [row(look(PRADA, 9)), row(show(PRADA))];

  const pages = () => {
    api.getFavouriteKeys.mockResolvedValue([...PAGE_ONE, ...PAGE_TWO]);
    api.getFavouritesPage.mockImplementation(async ({ cursor } = {}) => (
      cursor === 'c1'
        ? { favourites: PAGE_TWO, total: 4, hasMore: false, nextCursor: null }
        : { favourites: PAGE_ONE, total: 4, hasMore: true, nextCursor: 'c1' }
    ));
  };

  test('the first page is asked for with a limit and no cursor', async () => {
    pages();
    await mount();

    expect(api.getFavouritesPage).toHaveBeenCalledWith({ limit: PAGE_SIZE });
  });

  test('loadMore appends the next page and stops at the end', async () => {
    pages();
    const { result } = await mount();
    expect(result.current.saves).toHaveLength(2);
    expect(result.current.hasMore).toBe(true);

    await act(async () => { await result.current.loadMore(); });

    // Appended, in order, and the cursor the SERVER gave was handed back
    // untouched rather than a page number built here.
    expect(api.getFavouritesPage).toHaveBeenLastCalledWith(
      { limit: PAGE_SIZE, cursor: 'c1' });
    expect(result.current.saves).toHaveLength(4);
    expect(result.current.saves.slice(0, 2)).toEqual(PAGE_ONE);
    expect(result.current.saves.slice(2)).toEqual(PAGE_TWO);
    expect(result.current.hasMore).toBe(false);
  });

  test('loadMore at the end of the list asks for nothing', async () => {
    pages();
    const { result } = await mount();
    await act(async () => { await result.current.loadMore(); });
    const calls = api.getFavouritesPage.mock.calls.length;

    await act(async () => { await result.current.loadMore(); });

    expect(api.getFavouritesPage).toHaveBeenCalledTimes(calls);
  });

  test('two presses in the same tick fetch one page, not the same page twice',
    async () => {
      pages();
      const { result } = await mount();

      await act(async () => {
        await Promise.all([result.current.loadMore(), result.current.loadMore()]);
      });

      // `hasMore` is state and lags a render; the cursor is a ref and is taken
      // the moment a page is asked for. Without that guard both presses see
      // `hasMore === true` and page two lands twice.
      expect(result.current.saves).toHaveLength(4);
      expect(api.getFavouritesPage).toHaveBeenCalledTimes(2);   // page one, page two
    });

  test('a page that fails leaves the control pressable rather than ending the list',
    async () => {
      pages();
      const { result } = await mount();
      api.getFavouritesPage.mockRejectedValueOnce(new Error('down'));

      await act(async () => { await result.current.loadMore(); });
      expect(result.current.error).toBeTruthy();
      expect(result.current.saves).toHaveLength(2);
      expect(result.current.hasMore).toBe(true);

      // And pressing again works: the cursor went back where it was.
      await act(async () => { await result.current.loadMore(); });
      expect(result.current.saves).toHaveLength(4);
    });

  test('a star pressed while a page is in flight is not dropped by it', async () => {
    pages();
    let releasePage;
    const { result } = await mount();
    api.getFavouritesPage.mockImplementationOnce(() => new Promise((resolve) => {
      releasePage = () => resolve(
        { favourites: PAGE_TWO, total: 4, hasMore: false, nextCursor: null });
    }));

    let pending;
    act(() => { pending = result.current.loadMore(); });
    await act(async () => { await result.current.toggle(look(PRADA, 40)); });
    await act(async () => { releasePage(); await pending; });

    // Five rows: two from page one, the one just starred, and two from page
    // two. Appending to a snapshot taken before the request went out would
    // have thrown the new one away.
    expect(result.current.saves).toHaveLength(5);
    expect(result.current.isSaved(look(PRADA, 40))).toBe(true);
  });
});
