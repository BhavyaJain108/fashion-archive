// Saving a view, end to end — the archive page, the library page, and the
// one thing that carries a view between them, which is a URL.
//
// Every other test of this feature stops at a seam. `useSaves.test.js` proves
// the view key partitions the way the server's does; `saveStars.test.js`
// proves the star in the filter bar is enabled, pressed and lit;
// `LibraryPage.test.js` proves a saved row's click writes the right address.
// None of them proves the thing the reader actually does: narrow the archive,
// press the star, go somewhere else, come back through the library, and find
// the same filters applied. That crosses two pages, the router, the URL
// parser and the page's own URL→state effect, and the awkward one — gender —
// is decided inside HighFashionPage on mount, where no seam test can see it.
//
// So this mounts `App` and drives it through the browser's own controls.
//
// The server is a fake with the real uniqueness rule. `normalise` and
// `identity` below are `normalise_filters` and `md5(view_filters::text)` from
// backend/userdata/favourites.py restated, deliberately NOT imported from
// `useSaves` — a fake that keyed views with the client's own function could
// not fail when the client's rule drifted from the server's, which is the
// whole hazard behind "the same filters saved twice is one row".
import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

jest.mock('../shared/api', () => ({
  FashionArchiveAPI: {
    getMe: jest.fn(),
    logout: jest.fn(),
    getSeasons: jest.fn(),
    getIndexStatus: jest.fn(),
    getDesigners: jest.fn(),
    getRecents: jest.fn(),
    getFavourites: jest.fn(),
    getFavouriteStats: jest.fn(),
    searchShows: jest.fn(),
    browseCatalog: jest.fn(),
    streamCollectionImages: jest.fn(),
    streamCatalog: jest.fn(),
    streamDesignerCollections: jest.fn(),
    downloadVideo: jest.fn(),
    addFavourite: jest.fn(),
    removeFavourite: jest.fn(),
    addShowFavourite: jest.fn(),
    removeShowFavourite: jest.fn(),
    addViewFavourite: jest.fn(),
    removeViewFavourite: jest.fn(),
    getImageUrl: (p) => `/images/${p}`,
  },
}));

// eslint-disable-next-line import/first
import App from './App';

// eslint-disable-next-line import/first
const { FashionArchiveAPI: API } = require('../shared/api');

// ── The fake server ───────────────────────────────────────────────────────

// backend/userdata/favourites.py FILTER_KEYS, in its order, because
// derive_view_name reads the values in it.
const SERVER_KEYS = ['gender', 'year', 'season', 'city', 'category', 'shootType', 'letter'];

// normalise_filters: known keys, trimmed, numbers as text, empties dropped.
const normalise = (raw) => {
  const out = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  for (const key of SERVER_KEYS) {
    let value = raw[key];
    if (typeof value === 'boolean') continue;
    else if (typeof value === 'number') value = String(value);
    else if (typeof value === 'string') value = value.trim();
    else continue;
    if (value) out[key] = value;
  }
  return out;
};

// md5(view_filters::text) stands in as the sorted pairs — same equivalence
// classes, and readable in a failure message.
const identity = (filters) => JSON.stringify(
  Object.keys(filters).sort().map(k => [k, filters[k]]));

// derive_view_name: the values, in FILTER_KEYS order, joined.
const deriveName = (filters) => {
  const values = SERVER_KEYS.filter(k => k in filters).map(k => filters[k]);
  return values.length ? values.join(' · ') : 'All of the archive';
};

let table = [];
let nextId = 1;

const viewRowsOnServer = () => table.filter(r => r.kind === 'view');

// ── The archive the page browses ──────────────────────────────────────────

const YOHJI = {
  collection_id: '1234',
  url: 'https://example.test/show/1234',
  season_url: 'https://example.test/season/fw1999',
  designer: 'Yohji Yamamoto',
  designer_name: 'Yohji Yamamoto',
  year: '1999',
  season: 'Fall / Winter',
  gender: 'Women',
  subtitle: 'Runway Collection — Paris',
};

if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {};

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, '', '/');
  jest.clearAllMocks();
  table = [];
  nextId = 1;

  API.getMe.mockResolvedValue({ id: 1, username: 'reader', email: 'r@example.test' });
  API.logout.mockResolvedValue({});
  API.getSeasons.mockResolvedValue([]);
  // The archive IS held locally, which is the state the gender default is
  // widened in. A test run against a crawling server would never reach the
  // effect this is here to pin.
  API.getIndexStatus.mockResolvedValue({ shows: 55700 });
  API.getDesigners.mockResolvedValue([]);
  API.getRecents.mockResolvedValue([]);
  API.getFavouriteStats.mockResolvedValue({ total: 0 });
  API.searchShows.mockResolvedValue({ success: true, shows: [], total: 0 });
  API.downloadVideo.mockResolvedValue(null);
  API.streamCatalog.mockResolvedValue({ nextPage: 0, hasMore: false });
  API.streamDesignerCollections.mockResolvedValue({});
  API.browseCatalog.mockResolvedValue({
    success: true, collections: [YOHJI], hasMore: false, total: 1, facets: null,
  });
  API.streamCollectionImages.mockImplementation(async (url, handlers = {}) => {
    if (handlers.onMeta) handlers.onMeta({ count: 2 });
    if (handlers.onImage) {
      handlers.onImage({ index: 0, path: 'shows/1234/look-01.jpg' });
      handlers.onImage({ index: 1, path: 'shows/1234/look-02.jpg' });
    }
    return {};
  });

  API.getFavourites.mockImplementation(async () => table.map(r => ({ ...r })));

  // ON CONFLICT DO NOTHING on (user_id, md5(view_filters::text)) WHERE
  // kind = 'view'. A second save of the same view is reported, not stored.
  API.addViewFavourite.mockImplementation(async (filters, name) => {
    const stored = normalise(filters);
    const key = identity(stored);
    if (viewRowsOnServer().some(r => identity(normalise(r.view.filters)) === key)) {
      return { success: false, message: 'Already in favourites', kind: 'view' };
    }
    const viewName = (typeof name === 'string' && name.trim()) || deriveName(stored);
    table.push({
      id: nextId++, kind: 'view',
      season: {}, collection: {}, look: {},
      view: { name: viewName, filters: stored },
    });
    return { success: true, kind: 'view', view: { name: viewName, filters: stored } };
  });

  API.removeViewFavourite.mockImplementation(async (filters) => {
    const key = identity(normalise(filters));
    const before = table.length;
    table = table.filter(
      r => !(r.kind === 'view' && identity(normalise(r.view.filters)) === key));
    return { success: table.length < before };
  });

  API.addFavourite.mockResolvedValue({ success: true });
  API.removeFavourite.mockResolvedValue({ success: true });
  API.addShowFavourite.mockResolvedValue({ success: true });
  API.removeShowFavourite.mockResolvedValue({ success: true });
});

// ── Driving the two pages ─────────────────────────────────────────────────

const path = () => window.location.pathname + window.location.search;

const viewStar = () => screen.getByRole('button', { name: 'Save this view' });
const starIsOn = () => viewStar().getAttribute('aria-pressed') === 'true';

// The gender segmented control: 'All' / 'Women' / 'Men'.
const genderButton = (label) => Array.from(document.querySelectorAll('.hf2-segment'))
  .find(b => b.textContent === label);
const genderChosen = () => (document.querySelector('.hf2-segment.selected') || {}).textContent;

// A facet select, found by the label beside it rather than by position, so
// adding an eighth filter does not silently move this onto another one.
const facet = (name) => {
  const label = Array.from(document.querySelectorAll('.hf2-facet'))
    .find(l => (l.querySelector('.hf2-facet-label') || {}).textContent === name);
  return label && label.querySelector('select');
};

const goToLibrary = () => fireEvent.click(
  screen.getByRole('button', { name: 'Library' }));
const goToArchive = () => fireEvent.click(
  screen.getByRole('button', { name: 'Collections' }));

const openViewsPane = () => fireEvent.click(screen.getByText('Views'));
const savedViewRows = () => document.querySelectorAll('.lib-view-row');
// The row's own open button, not its text: a view named after its only
// filter renders that word twice — once as the name, once as the chip's
// value — and a query by text would be ambiguous for exactly the views this
// file is about.
const openSavedView = (row) => fireEvent.click(row.querySelector('.lib-view-open'));

// Mount, sign in, and wait for the archive to be on screen with the index
// ready — which is the point the gender default has been widened.
const openArchive = async () => {
  render(<App />);
  await screen.findByText('Yohji Yamamoto');
  await waitFor(() => expect(genderChosen()).toBe('All'));
};

// ── 1. The round trip ─────────────────────────────────────────────────────

test('a saved view opened from the library restores its filters, gender included',
  async () => {
    await openArchive();

    // Narrow it: a gender AND a letter, because gender is the filter with the
    // default and a view that carried only it could not tell a restored
    // 'Men' from a 'Men' the page happened to be sitting on.
    fireEvent.click(genderButton('Men'));
    fireEvent.change(facet('Brand'), { target: { value: 'G' } });
    await waitFor(() => expect(path()).toBe('/?gender=Men&letter=G'));

    // Save it.
    fireEvent.click(viewStar());
    await waitFor(() => expect(API.addViewFavourite).toHaveBeenCalledTimes(1));
    expect(API.addViewFavourite.mock.calls[0][0]).toEqual({ gender: 'Men', letter: 'G' });
    await waitFor(() => expect(starIsOn()).toBe(true));

    // Go somewhere else — a different gender and a different letter, so
    // neither half of what was saved is still applied.
    fireEvent.click(genderButton('Women'));
    fireEvent.change(facet('Brand'), { target: { value: 'K' } });
    await waitFor(() => expect(path()).toBe('/?gender=Women&letter=K'));
    // And the star goes out, because this is not the view that was saved.
    await waitFor(() => expect(starIsOn()).toBe(false));

    // Back through the library, which is how a reader reaches a saved view.
    goToLibrary();
    await screen.findByText('Views');
    openViewsPane();
    await waitFor(() => expect(savedViewRows()).toHaveLength(1));
    // Named by the server from the filters, since the star sends no name.
    expect(within(savedViewRows()[0]).getByText('Men · G')).toBeInTheDocument();

    openSavedView(savedViewRows()[0]);

    // The whole assertion: the filters that come back are the filters that
    // went in.
    await screen.findByText('Yohji Yamamoto');
    expect(path()).toBe('/?gender=Men&letter=G');
    await waitFor(() => expect(genderChosen()).toBe('Men'));
    expect(facet('Brand').value).toBe('G');
    // Gender in particular: the effect that widens the default to "All" once
    // the local index is ready must not widen a gender the view named. It
    // resolves after the mount, so this has to be asserted after it has.
    await waitFor(() => expect(API.getIndexStatus).toHaveBeenCalled());
    expect(genderChosen()).toBe('Men');
    // And the star is lit, because these ARE the saved filters.
    await waitFor(() => expect(starIsOn()).toBe(true));
  });

test('a view saved with no gender comes back with no gender, not with the default',
  async () => {
    // The other half of the awkward one. 'All' is a real choice, it is stored
    // as the absence of a gender, and restoring it must not be answered by
    // the 'Women' the page starts on.
    await openArchive();

    fireEvent.change(facet('Brand'), { target: { value: 'G' } });
    await waitFor(() => expect(path()).toBe('/?letter=G'));
    expect(genderChosen()).toBe('All');

    fireEvent.click(viewStar());
    await waitFor(() => expect(API.addViewFavourite).toHaveBeenCalledTimes(1));
    // No gender key at all — not gender: ''.
    expect(API.addViewFavourite.mock.calls[0][0]).toEqual({ letter: 'G' });

    fireEvent.click(genderButton('Men'));
    await waitFor(() => expect(genderChosen()).toBe('Men'));

    goToLibrary();
    await screen.findByText('Views');
    openViewsPane();
    await waitFor(() => expect(savedViewRows()).toHaveLength(1));
    openSavedView(savedViewRows()[0]);

    await screen.findByText('Yohji Yamamoto');
    expect(path()).toBe('/?letter=G');
    await waitFor(() => expect(API.getIndexStatus).toHaveBeenCalled());
    await waitFor(() => expect(genderChosen()).toBe('All'));
    expect(facet('Brand').value).toBe('G');
  });

// ── 2. The same filters saved twice is one row ────────────────────────────

test('the star is already lit on a view that is saved, so it is not saved twice',
  async () => {
    await openArchive();

    fireEvent.click(genderButton('Men'));
    fireEvent.change(facet('Brand'), { target: { value: 'G' } });
    fireEvent.click(viewStar());
    await waitFor(() => expect(starIsOn()).toBe(true));
    expect(viewRowsOnServer()).toHaveLength(1);

    // Reach the same filter set again by a different route: leave the page
    // entirely and come back to it, which remounts the archive and reloads
    // the saves from the server.
    goToLibrary();
    await screen.findByText('Views');
    goToArchive();
    await screen.findByText('Yohji Yamamoto');
    fireEvent.click(genderButton('Men'));
    fireEvent.change(facet('Brand'), { target: { value: 'G' } });

    // Lit, on a fresh mount, from the row the server sent — which is what
    // stops the reader pressing it again and seeing nothing happen.
    await waitFor(() => expect(starIsOn()).toBe(true));
    expect(API.addViewFavourite).toHaveBeenCalledTimes(1);
    expect(viewRowsOnServer()).toHaveLength(1);

    // And the library lists it once.
    goToLibrary();
    await screen.findByText('Views');
    openViewsPane();
    await waitFor(() => expect(savedViewRows()).toHaveLength(1));
  });

test('the same filters spelled in another order are the one saved view', async () => {
  // The filters go into the URL sorted, so the only way to reach the same
  // view by another spelling is to build it in another order. This asserts
  // the server's rule directly, because it is the rule the UI is trusting.
  await API.addViewFavourite({ letter: 'G', gender: 'Men' }, '');
  const second = await API.addViewFavourite({ gender: 'Men', letter: 'G' }, 'A second name');

  expect(second.success).toBe(false);
  expect(viewRowsOnServer()).toHaveLength(1);
  expect(viewRowsOnServer()[0].view.name).toBe('Men · G');
});

// ── 3. A view is a list state, not a reading position ─────────────────────

test('a saved view does not carry the show that was open when it was saved',
  async () => {
    await openArchive();

    fireEvent.click(genderButton('Men'));
    fireEvent.change(facet('Brand'), { target: { value: 'G' } });
    // The list refetches on every filter change; the row has to be back on
    // screen before it can be clicked.
    await screen.findByText('Yohji Yamamoto');

    // Open a show, so the address bar names one and the viewer holds its
    // photographs.
    fireEvent.click(screen.getByText('Yohji Yamamoto'));
    await waitFor(() => expect(path()).toContain('/hf/'));
    await waitFor(() => expect(document.querySelectorAll('.hf2-thumb')).not.toHaveLength(0));

    fireEvent.click(viewStar());
    await waitFor(() => expect(API.addViewFavourite).toHaveBeenCalledTimes(1));

    // The filters and nothing else. No collection, no look, no url.
    expect(API.addViewFavourite.mock.calls[0][0]).toEqual({ gender: 'Men', letter: 'G' });
    expect(viewRowsOnServer()[0].view.filters).toEqual({ gender: 'Men', letter: 'G' });

    goToLibrary();
    await screen.findByText('Views');
    openViewsPane();
    await waitFor(() => expect(savedViewRows()).toHaveLength(1));
    openSavedView(savedViewRows()[0]);

    // Opened, it is the list with those filters — not the show.
    await screen.findByText('Yohji Yamamoto');
    expect(path()).toBe('/?gender=Men&letter=G');
    expect(path()).not.toContain('/hf/');
    await waitFor(() => expect(document.querySelectorAll('.hf2-thumb')).toHaveLength(0));
  });

// ── 4. Gender is a filter, once "All" is a choice ─────────────────────────

test('a gender on its own is a view, and can be saved', async () => {
  // Half the archive is a narrowing. It is the one filter the "Clear N
  // filters" badge deliberately does not count — in the crawling fallback
  // gender can never be empty, so counting it would put the badge at 1 with
  // nothing chosen — but the star is a different question from the badge:
  // with the index held locally the reader starts on "All", so choosing
  // "Men" is something they did and something they can come back to.
  await openArchive();
  expect(genderChosen()).toBe('All');
  // Nothing set is not a view: this is still the whole archive.
  expect(viewStar()).toBeDisabled();

  fireEvent.click(genderButton('Men'));
  await waitFor(() => expect(path()).toBe('/?gender=Men'));

  expect(viewStar()).not.toBeDisabled();
  fireEvent.click(viewStar());
  await waitFor(() => expect(API.addViewFavourite).toHaveBeenCalledTimes(1));
  expect(API.addViewFavourite.mock.calls[0][0]).toEqual({ gender: 'Men' });

  // And it round trips like any other view.
  fireEvent.click(genderButton('All'));
  await waitFor(() => expect(starIsOn()).toBe(false));

  goToLibrary();
  await screen.findByText('Views');
  openViewsPane();
  await waitFor(() => expect(savedViewRows()).toHaveLength(1));
  openSavedView(savedViewRows()[0]);

  await screen.findByText('Yohji Yamamoto');
  expect(path()).toBe('/?gender=Men');
  await waitFor(() => expect(genderChosen()).toBe('Men'));
  await waitFor(() => expect(starIsOn()).toBe(true));
});

test('going back to "All" is not a view, and the star goes out with it', async () => {
  await openArchive();

  fireEvent.click(genderButton('Men'));
  await waitFor(() => expect(viewStar()).not.toBeDisabled());

  fireEvent.click(genderButton('All'));
  await waitFor(() => expect(genderChosen()).toBe('All'));
  // "All" with nothing else is where every reader already starts.
  expect(viewStar()).toBeDisabled();
});
