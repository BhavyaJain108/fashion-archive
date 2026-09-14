// The library page, which holds three kinds of saved thing.
//
// It had no test file at all until this one: Task 5 deleted a whole feature
// out of it and the only things that noticed were the build and a grep. What
// is pinned here is the part a build cannot see — that each kind renders as
// itself, that clicking one goes where it should, and above all that
// removing one removes that one.
//
// The removal hazard is the reason this file exists. `removeFavourite` is
// positional and two of its three arguments are URLs, so a triple assembled
// out of two different rows names a row that exists, deletes it, and reports
// success — no error, no failing build, somebody else's favourite gone. The
// two Yohji fixtures below are the trap: a saved SHOW and a saved LOOK of
// that same show share a season url and a collection url and differ only in
// kind and look number. Removing either must leave the other standing.
import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

jest.mock('../../shared/api', () => ({
  FashionArchiveAPI: {
    getFavourites: jest.fn(),
    getFavouriteStats: jest.fn(),
    removeFavourite: jest.fn(),
    removeShowFavourite: jest.fn(),
    removeViewFavourite: jest.fn(),
    getImageUrl: (p) => `/images/${p}`,
  },
  // The sidebar's albums shelf reads this. It is the way in to an album and
  // nothing else on this page touches it, so the shelf is empty in every
  // test but the one below that gives it a row.
  AlbumsAPI: {
    getAlbums: jest.fn(),
  },
}));

// eslint-disable-next-line import/first
import LibraryPage from './LibraryPage';

// eslint-disable-next-line import/first
const { FashionArchiveAPI: API, AlbumsAPI } = require('../../shared/api');

// jsdom implements Element.scrollTo on window but not on elements, and the
// page centres the active thumbnail by calling it on the strip.
if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {};

const YOHJI_SEASON = 'https://www.firstview.com/season.php?id=fw1999';
const YOHJI_SHOW = 'https://www.firstview.com/collection_images.php?id=1234&list=all';
const RAF_SEASON = 'https://www.firstview.com/season.php?id=fw2001';
const RAF_SHOW = 'https://www.firstview.com/collection_images.php?id=5678&list=all';

// A saved look of the Yohji show.
const LOOK = {
  id: 'fav-look',
  kind: 'look',
  season: { name: 'Fall 1999', url: YOHJI_SEASON },
  collection: { designer: 'Yohji Yamamoto Ready To Wear Fall 1999', url: YOHJI_SHOW },
  look: { number: 7, total: 40 },
  view: { name: '', filters: {} },
  image_path: 'shows/1234/look-07.jpg',
  date_added: '2026-09-01T10:00:00',
};

// The SAME show, saved whole. Same two urls as LOOK, different kind.
const SHOW = {
  id: 'fav-show',
  kind: 'show',
  season: { name: 'Fall 1999', url: YOHJI_SEASON },
  collection: { designer: 'Yohji Yamamoto Ready To Wear Fall 1999', url: YOHJI_SHOW },
  look: { number: null, total: null },
  view: { name: '', filters: {} },
  image_path: 'shows/1234/look-01.jpg',
  date_added: '2026-09-02T10:00:00',
};

// A second show, so a removal has something to leave alone.
const OTHER_SHOW = {
  id: 'fav-show-2',
  kind: 'show',
  season: { name: 'Fall 2001', url: RAF_SEASON },
  collection: { designer: 'Raf Simons Menswear Fall 2001', url: RAF_SHOW },
  look: { number: null, total: null },
  view: { name: '', filters: {} },
  image_path: 'shows/5678/look-01.jpg',
  date_added: '2026-09-03T10:00:00',
};

const VIEW = {
  id: 'fav-view',
  kind: 'view',
  season: { name: '', url: '' },
  collection: { designer: '', url: '' },
  look: { number: null, total: null },
  view: { name: 'Paris 2020', filters: { year: '2020', city: 'Paris' } },
  image_path: '',
  date_added: '2026-09-04T10:00:00',
};

const OTHER_VIEW = {
  id: 'fav-view-2',
  kind: 'view',
  season: { name: '', url: '' },
  collection: { designer: '', url: '' },
  look: { number: null, total: null },
  view: { name: 'Milan couture', filters: { city: 'Milan', category: 'Haute Couture' } },
  image_path: '',
  date_added: '2026-09-05T10:00:00',
};

const ALL = [LOOK, SHOW, OTHER_SHOW, VIEW, OTHER_VIEW];

const path = () => window.location.pathname + window.location.search;

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, '', '/library');
  jest.clearAllMocks();
  API.getFavourites.mockResolvedValue(ALL);
  API.getFavouriteStats.mockResolvedValue({});
  API.removeFavourite.mockResolvedValue({ success: true });
  API.removeShowFavourite.mockResolvedValue({ success: true });
  API.removeViewFavourite.mockResolvedValue({ success: true });
  AlbumsAPI.getAlbums.mockResolvedValue([]);
});

const kindRow = (label) => screen.getByText(label).closest('.lib-kind');
const openKind = (label) => fireEvent.click(kindRow(label));

const showCards = () => Array.from(document.querySelectorAll('.lib-show-card'));
const viewRows = () => Array.from(document.querySelectorAll('.lib-view-row'));

const renderPage = async () => {
  render(<LibraryPage currentPage="library" currentUser={{ username: 'test' }} />);
  // The looks pane is the default, and the look's number is the first thing
  // on it that only appears once the response has landed.
  await screen.findByText('Looks');
  await waitFor(() => expect(API.getFavourites).toHaveBeenCalled());
};

// ── The albums shelf, which is the way in to one ───────────────────

test('the sidebar lists the albums, and clicking one opens it', async () => {
  AlbumsAPI.getAlbums.mockResolvedValue([
    { id: 7, name: 'Resort', item_count: 4, cover_image_path: null, sort_by: 'added' },
    { id: 9, name: 'Tailoring', item_count: 0, cover_image_path: null, sort_by: 'added' },
  ]);
  await renderPage();

  await waitFor(() => expect(document.querySelectorAll('.lib-album')).toHaveLength(2));
  const [resort, tailoring] = Array.from(document.querySelectorAll('.lib-album'));
  expect(within(resort).getByText('Resort')).toBeInTheDocument();
  expect(within(resort).getByText('4')).toBeInTheDocument();
  expect(within(tailoring).getByText('Tailoring')).toBeInTheDocument();

  // An address, built by buildRoute, so Back walks out of it.
  fireEvent.click(tailoring);
  expect(path()).toBe('/library/albums/9');
});

test('a reader with no albums is told so rather than shown nothing', async () => {
  await renderPage();

  await screen.findByText('No albums yet');
  expect(document.querySelectorAll('.lib-album')).toHaveLength(0);
});

// ── The sidebar groups by kind ────────────────────────────────────────────

test('the sidebar names all three kinds and counts each', async () => {
  await renderPage();

  await waitFor(() => expect(within(kindRow('Looks')).getByText('1')).toBeInTheDocument());
  expect(within(kindRow('Shows')).getByText('2')).toBeInTheDocument();
  expect(within(kindRow('Views')).getByText('2')).toBeInTheDocument();
});

test('the grouping the page already had is still there, for looks', async () => {
  await renderPage();

  // Recent / By collection, and the collection list below it.
  await screen.findByText('By collection');
  expect(screen.getByText('Recent')).toBeInTheDocument();
  expect(screen.getByText('All looks')).toBeInTheDocument();
  // One collection: the Yohji show the saved look belongs to. The saved SHOW
  // of the same collection is not a look and must not be grouped in here.
  expect(document.querySelectorAll('.fav-collection')).toHaveLength(2); // "All" + one
});

// ── Each kind renders as itself ───────────────────────────────────────────

test('a look renders as a look', async () => {
  await renderPage();

  await waitFor(() => expect(document.querySelector('.fav-look-label')).not.toBeNull());
  expect(document.querySelector('.fav-look-label').textContent).toBe('07');
  expect(document.querySelector('.fav-image-frame img'))
    .toHaveAttribute('src', '/images/shows/1234/look-07.jpg');
});

test('a saved show renders as a show, not as a look with empty fields', async () => {
  await renderPage();
  openKind('Shows');

  await waitFor(() => expect(showCards()).toHaveLength(2));
  const [yohji] = showCards();
  // Designer and season, cleaned of the season tail firstVIEW staples on.
  expect(within(yohji).getByText('Yohji Yamamoto')).toBeInTheDocument();
  expect(within(yohji).getByText('Fall 1999')).toBeInTheDocument();
  // And nothing from the look gallery: no look number, no thumb strip, no
  // "of 2" counter. Before this the show came through the look pane and
  // rendered as a look whose number was blank.
  expect(document.querySelector('.fav-look-label')).toBeNull();
  expect(document.querySelector('.fav-thumb-strip')).toBeNull();
});

test('a saved view renders as its name and its filters', async () => {
  await renderPage();
  openKind('Views');

  await waitFor(() => expect(viewRows()).toHaveLength(2));
  const [paris] = viewRows();
  expect(within(paris).getByText('Paris 2020')).toBeInTheDocument();
  // The filters themselves, labelled the way the archive's own facets are.
  expect(within(paris).getByText('Year')).toBeInTheDocument();
  expect(within(paris).getByText('2020')).toBeInTheDocument();
  expect(within(paris).getByText('City')).toBeInTheDocument();
  expect(within(paris).getByText('Paris')).toBeInTheDocument();
});

// ── Clicking each does the right thing ────────────────────────────────────

test('clicking a saved show opens it on the archive page', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  fireEvent.click(within(showCards()[0]).getByText('Yohji Yamamoto'));

  // The collection id out of the show's own url, and the readable slug.
  expect(path()).toBe('/hf/yohji-yamamoto-fall-1999/1234');
});

test('the second saved show opens its own show, not the first row show', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  fireEvent.click(within(showCards()[1]).getByText('Raf Simons'));

  // Raf's collection id, off Raf's own row.
  expect(path()).toBe('/hf/raf-simons-fall-2001/5678');
});

test('clicking a saved view opens the archive with those filters applied', async () => {
  await renderPage();
  openKind('Views');
  await waitFor(() => expect(viewRows()).toHaveLength(2));

  fireEvent.click(within(viewRows()[0]).getByText('Paris 2020'));

  // A URL — buildRoute's sorted query string — and not some second
  // mechanism for handing filters across.
  expect(path()).toBe('/?city=Paris&year=2020');
});

test('the second saved view opens its own filters, not the first row filters', async () => {
  await renderPage();
  openKind('Views');
  await waitFor(() => expect(viewRows()).toHaveLength(2));

  fireEvent.click(within(viewRows()[1]).getByText('Milan couture'));

  expect(path()).toBe('/?category=Haute+Couture&city=Milan');
});

// ── Removal: the right row goes, and only it ──────────────────────────────

test('removing a look removes that look and nothing else', async () => {
  await renderPage();
  await waitFor(() => expect(document.querySelector('.fav-remove')).not.toBeNull());

  fireEvent.click(document.querySelector('.fav-remove'));

  await waitFor(() => expect(API.removeFavourite).toHaveBeenCalledTimes(1));
  // The whole triple off the one row: season url, collection url, number.
  expect(API.removeFavourite).toHaveBeenCalledWith(YOHJI_SEASON, YOHJI_SHOW, 7);
  // A look is not a show. The saved show of this very same collection must
  // not be touched by either the request or the list.
  expect(API.removeShowFavourite).not.toHaveBeenCalled();
  expect(API.removeViewFavourite).not.toHaveBeenCalled();

  // The look is gone from the pane; both shows survive.
  await waitFor(() => expect(within(kindRow('Looks')).getByText('0')).toBeInTheDocument());
  expect(within(kindRow('Shows')).getByText('2')).toBeInTheDocument();
  expect(within(kindRow('Views')).getByText('2')).toBeInTheDocument();
});

test('removing a show removes that show and leaves the saved look of it', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  fireEvent.click(within(showCards()[0]).getByText('Remove'));

  await waitFor(() => expect(API.removeShowFavourite).toHaveBeenCalledTimes(1));
  // Season url and collection url off the one row — no look number, because
  // a show has none, and the server keys it on the pair alone.
  expect(API.removeShowFavourite).toHaveBeenCalledWith(YOHJI_SEASON, YOHJI_SHOW);
  expect(API.removeFavourite).not.toHaveBeenCalled();

  // Raf's show stays, and so does the saved LOOK of the Yohji show that was
  // just removed: they are separate rows, and removing one is not removing
  // the other.
  await waitFor(() => expect(showCards()).toHaveLength(1));
  expect(within(showCards()[0]).getByText('Raf Simons')).toBeInTheDocument();
  expect(within(kindRow('Looks')).getByText('1')).toBeInTheDocument();
  expect(within(kindRow('Shows')).getByText('1')).toBeInTheDocument();
});

test('removing the second show does not remove the first', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  fireEvent.click(within(showCards()[1]).getByText('Remove'));

  await waitFor(() => expect(API.removeShowFavourite).toHaveBeenCalledTimes(1));
  // Raf's pair, not Yohji's, and not one of each.
  expect(API.removeShowFavourite).toHaveBeenCalledWith(RAF_SEASON, RAF_SHOW);

  await waitFor(() => expect(showCards()).toHaveLength(1));
  expect(within(showCards()[0]).getByText('Yohji Yamamoto')).toBeInTheDocument();
});

test('removing a view removes that view and leaves the other', async () => {
  await renderPage();
  openKind('Views');
  await waitFor(() => expect(viewRows()).toHaveLength(2));

  fireEvent.click(within(viewRows()[0]).getByText('Remove'));

  await waitFor(() => expect(API.removeViewFavourite).toHaveBeenCalledTimes(1));
  // The filters this row was drawn from, which is the whole of a view's
  // identity — the server hashes them to find the row.
  expect(API.removeViewFavourite).toHaveBeenCalledWith({ year: '2020', city: 'Paris' });
  expect(API.removeFavourite).not.toHaveBeenCalled();
  expect(API.removeShowFavourite).not.toHaveBeenCalled();

  await waitFor(() => expect(viewRows()).toHaveLength(1));
  expect(within(viewRows()[0]).getByText('Milan couture')).toBeInTheDocument();
});

test('removing the second view sends its own filters, not the first row filters', async () => {
  await renderPage();
  openKind('Views');
  await waitFor(() => expect(viewRows()).toHaveLength(2));

  fireEvent.click(within(viewRows()[1]).getByText('Remove'));

  await waitFor(() => expect(API.removeViewFavourite).toHaveBeenCalledTimes(1));
  // Milan's filters, off Milan's row. A view's filters ARE its identity on
  // the server, so sending another row's is deleting another row.
  expect(API.removeViewFavourite)
    .toHaveBeenCalledWith({ city: 'Milan', category: 'Haute Couture' });

  await waitFor(() => expect(viewRows()).toHaveLength(1));
  expect(within(viewRows()[0]).getByText('Paris 2020')).toBeInTheDocument();
});

test('a removal the server refuses leaves the row on screen', async () => {
  API.removeShowFavourite.mockResolvedValue({ success: false });
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  fireEvent.click(within(showCards()[0]).getByText('Remove'));

  await waitFor(() => expect(API.removeShowFavourite).toHaveBeenCalled());
  expect(showCards()).toHaveLength(2);
});

// ── Empty states, per kind ────────────────────────────────────────────────

test('a reader with looks but no views is told what a view is', async () => {
  API.getFavourites.mockResolvedValue([LOOK]);
  await renderPage();
  openKind('Views');

  await screen.findByText('No saved views');
  expect(screen.getByText(/a year, a season, a city/i)).toBeInTheDocument();
  expect(screen.getByText(/Save this view/i)).toBeInTheDocument();
});

// The hint named a designer first, and a designer is the one thing a saved
// view cannot hold: it is not in FILTER_KEYS, and the star is disabled in
// designer mode for exactly that reason. An empty state that teaches the one
// move that does not work is worse than no empty state.
test('the hint does not offer a designer, which a view cannot hold', async () => {
  API.getFavourites.mockResolvedValue([LOOK]);
  await renderPage();
  openKind('Views');

  await screen.findByText('No saved views');
  expect(screen.queryByText(/a designer, a year, a city/i)).not.toBeInTheDocument();
});

test('a reader with looks but no shows is told what a show is', async () => {
  API.getFavourites.mockResolvedValue([LOOK]);
  await renderPage();
  openKind('Shows');

  await screen.findByText('No saved shows');
  expect(screen.getByText(/a whole collection/i)).toBeInTheDocument();
});

test('a reader with nothing saved still sees all three kinds', async () => {
  API.getFavourites.mockResolvedValue([]);
  await renderPage();

  await screen.findByText('No saved looks');
  // Not one page-wide "no favourites" line: the other two kinds are still
  // reachable, and clicking one is how a reader finds out it exists.
  expect(kindRow('Shows')).not.toBeNull();
  openKind('Views');
  await screen.findByText('No saved views');
});
