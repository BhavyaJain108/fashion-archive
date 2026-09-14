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
    // The page reads its rows a page at a time, per kind, and counts with the
    // `total` that comes back beside them.
    getFavouritesPage: jest.fn(),
    removeFavourite: jest.fn(),
    removeShowFavourite: jest.fn(),
    removeViewFavourite: jest.fn(),
    getImageUrl: (p) => `/images/${p}`,
  },
  // The sidebar's albums shelf reads this, and so does the picker that puts
  // ticked things into one. The shelf is empty in every test but the ones
  // below that give it rows.
  AlbumsAPI: {
    getAlbums: jest.fn(),
    getAlbum: jest.fn(),
    createAlbum: jest.fn(),
    addSavedToAlbum: jest.fn(),
    addLookToAlbum: jest.fn(),
    addShowToAlbum: jest.fn(),
    addViewToAlbum: jest.fn(),
    removeFromAlbum: jest.fn(),
  },
}));

// eslint-disable-next-line import/first
import LibraryPage from './LibraryPage';
// The page is handed `navigate`, so what a navigation test can check is the
// ROUTE it was asked for. `buildRoute` is the same function the real navigate
// puts through to window.history, so the URLs asserted below are the URLs the
// address bar would have held — the assertions did not get weaker when the
// module stub went away, they got one step earlier.
// eslint-disable-next-line import/first
import { buildRoute } from '../../app/routes';

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

// The fake server. One table, answered per kind with its own count — which is
// what GET /api/favourites?kind=…&limit=… does. Narrowing here rather than in
// the page is the point: the page must ask for the kind it is showing, and a
// fake that returned everything to every request could not fail when it didn't.
const serve = (table, { pageSize = Infinity } = {}) => {
  API.getFavouritesPage.mockImplementation(async ({ kind = null, cursor = null } = {}) => {
    const all = table.filter(r => kind === null || (r.kind || 'look') === kind);
    const from = cursor ? all.findIndex(r => r.id === cursor) + 1 : 0;
    const rows = all.slice(from, from + pageSize);
    const end = from + rows.length;
    return {
      favourites: rows,
      total: all.length,
      hasMore: end < all.length,
      nextCursor: end < all.length ? rows[rows.length - 1].id : null,
    };
  });
};

// Where the page asked to go, as a URL. Not "navigate was called" — that
// passes for a route built out of the wrong row, which is the mistake these
// tests exist to catch. The whole route object is asserted in two places
// below; everywhere else this is it, spelled as the address.
let navigate;
const wentTo = () => buildRoute(navigate.mock.calls[navigate.mock.calls.length - 1][0]);

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, '', '/library');
  jest.clearAllMocks();
  navigate = jest.fn();
  serve(ALL);
  API.removeFavourite.mockResolvedValue({ success: true });
  API.removeShowFavourite.mockResolvedValue({ success: true });
  API.removeViewFavourite.mockResolvedValue({ success: true });
  AlbumsAPI.getAlbums.mockResolvedValue([]);
  AlbumsAPI.createAlbum.mockResolvedValue({
    ok: true, status: 201, success: true,
    album: { id: 11, name: 'Archive', layout_mode: 'grid', sort_by: 'added' },
  });
  // What POST /api/albums/<id>/items answers for something already saved:
  // the favourite id it filed, and `saved: false` because it was already.
  AlbumsAPI.addSavedToAlbum.mockImplementation(async (albumId, favouriteId) => ({
    ok: true, status: 201, success: true,
    favourite_id: favouriteId, saved: false, added: true,
  }));
});

const SHELF = [
  { id: 7, name: 'Resort', item_count: 4, cover_image_path: null,
    layout_mode: 'grid', sort_by: 'added' },
  { id: 9, name: 'Tailoring', item_count: 0, cover_image_path: null,
    layout_mode: 'grid', sort_by: 'added' },
];

const albumButton = (name) => Array.from(document.querySelectorAll('.alp-album'))
  .find(node => node.querySelector('.alp-album-name').textContent === name);

const tick = (label) => fireEvent.click(screen.getByLabelText(`Select ${label}`));

const kindRow = (label) => screen.getByText(label).closest('.lib-kind');
const openKind = (label) => fireEvent.click(kindRow(label));

const showCards = () => Array.from(document.querySelectorAll('.lib-show-card'));
const viewRows = () => Array.from(document.querySelectorAll('.lib-view-row'));

const renderPage = async () => {
  render(
    <LibraryPage
      currentPage="library"
      currentUser={{ username: 'test' }}
      navigate={navigate}
    />,
  );
  // The looks pane is the default, and the look's number is the first thing
  // on it that only appears once the response has landed.
  await screen.findByText('Looks');
  await waitFor(() => expect(API.getFavouritesPage).toHaveBeenCalled());
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
  expect(wentTo()).toBe('/library/albums/9');
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
  expect(wentTo()).toBe('/hf/yohji-yamamoto-fall-1999/1234');
});

test('the second saved show opens its own show, not the first row show', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  fireEvent.click(within(showCards()[1]).getByText('Raf Simons'));

  // The whole route object, not just the URL it spells: `collectionId` is the
  // one authoritative segment and the slug is decoration, so a route carrying
  // Raf's slug and Yohji's id would open Yohji's show and read correctly in
  // the address bar while doing it.
  expect(navigate).toHaveBeenCalledTimes(1);
  expect(navigate).toHaveBeenCalledWith({
    page: 'high-fashion',
    collectionId: '5678',
    slug: 'raf-simons-fall-2001',
  });
  expect(wentTo()).toBe('/hf/raf-simons-fall-2001/5678');
});

test('clicking a saved view opens the archive with those filters applied', async () => {
  await renderPage();
  openKind('Views');
  await waitFor(() => expect(viewRows()).toHaveLength(2));

  fireEvent.click(within(viewRows()[0]).getByText('Paris 2020'));

  // A URL — buildRoute's sorted query string — and not some second
  // mechanism for handing filters across.
  expect(wentTo()).toBe('/?city=Paris&year=2020');
});

test('the second saved view opens its own filters, not the first row filters', async () => {
  await renderPage();
  openKind('Views');
  await waitFor(() => expect(viewRows()).toHaveLength(2));

  fireEvent.click(within(viewRows()[1]).getByText('Milan couture'));

  // Milan's filters, off Milan's own row, and no collection dragged along
  // from whatever was open before.
  expect(navigate).toHaveBeenCalledTimes(1);
  expect(navigate).toHaveBeenCalledWith({
    page: 'high-fashion',
    filters: { city: 'Milan', category: 'Haute Couture' },
  });
  expect(wentTo()).toBe('/?category=Haute+Couture&city=Milan');
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

  fireEvent.click(within(showCards()[0]).getByText('Unsave'));

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

  fireEvent.click(within(showCards()[1]).getByText('Unsave'));

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

  fireEvent.click(within(viewRows()[0]).getByText('Unsave'));

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

  fireEvent.click(within(viewRows()[1]).getByText('Unsave'));

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

  fireEvent.click(within(showCards()[0]).getByText('Unsave'));

  await waitFor(() => expect(API.removeShowFavourite).toHaveBeenCalled());
  expect(showCards()).toHaveLength(2);
});

// ── Empty states, per kind ────────────────────────────────────────────────

test('a reader with looks but no views is told what a view is', async () => {
  serve([LOOK]);
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
  serve([LOOK]);
  await renderPage();
  openKind('Views');

  await screen.findByText('No saved views');
  expect(screen.queryByText(/a designer, a year, a city/i)).not.toBeInTheDocument();
});

test('a reader with looks but no shows is told what a show is', async () => {
  serve([LOOK]);
  await renderPage();
  openKind('Shows');

  await screen.findByText('No saved shows');
  expect(screen.getByText(/a whole collection/i)).toBeInTheDocument();
});

test('a reader with nothing saved still sees all three kinds', async () => {
  serve([]);
  await renderPage();

  await screen.findByText('No saved looks');
  // Not one page-wide "no favourites" line: the other two kinds are still
  // reachable, and clicking one is how a reader finds out it exists.
  expect(kindRow('Shows')).not.toBeNull();
  openKind('Views');
  await screen.findByText('No saved views');
});

// ── Putting saved things in an album ──────────────────────────────────────
//
// Everything on this page is saved already, so every add here goes by
// favourite id — `addSavedToAlbum` and nothing else. A page that reached for
// `addLookToAlbum` with a body would file a SECOND copy of something the
// reader had already starred, which is the one mistake this half of the
// feature can make.

test('several saved things go into one album in one press', async () => {
  AlbumsAPI.getAlbums.mockResolvedValue(SHELF);
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  tick('Yohji Yamamoto Fall 1999');
  tick('Raf Simons Fall 2001');
  expect(screen.getByText('2 selected')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Add to album' }));
  await screen.findByRole('dialog');
  fireEvent.click(albumButton('Resort'));

  await waitFor(() => expect(AlbumsAPI.addSavedToAlbum).toHaveBeenCalledTimes(2));
  // Both of them, by their own ids, into the album that was chosen. One call
  // would mean the bar acts on the last tick rather than on the selection.
  expect(AlbumsAPI.addSavedToAlbum).toHaveBeenCalledWith(7, 'fav-show');
  expect(AlbumsAPI.addSavedToAlbum).toHaveBeenCalledWith(7, 'fav-show-2');
  // Saved things are added by id; nothing is re-saved.
  expect(AlbumsAPI.addShowToAlbum).not.toHaveBeenCalled();

  // The panel closes and the ticks are cleared, so the next press is not an
  // accidental second filing of the same two.
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.queryByText('2 selected')).toBeNull();
});

test('an album can be made from the picker and filled in the same press', async () => {
  AlbumsAPI.getAlbums.mockResolvedValue(SHELF);
  await renderPage();
  openKind('Views');
  await waitFor(() => expect(viewRows()).toHaveLength(2));

  tick('Paris 2020');
  fireEvent.click(screen.getByRole('button', { name: 'Add to album' }));
  await screen.findByRole('dialog');

  fireEvent.click(screen.getByRole('button', { name: 'New album' }));
  fireEvent.change(screen.getByLabelText('New album name'), { target: { value: 'Archive' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create and add' }));

  await waitFor(() => expect(AlbumsAPI.createAlbum).toHaveBeenCalledWith('Archive', {}));
  // The id is the server's to mint, so the add has to wait for it and use it.
  await waitFor(() => expect(AlbumsAPI.addSavedToAlbum).toHaveBeenCalledWith(11, 'fav-view'));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

test('the selection is dropped when the pane changes under it', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));
  tick('Yohji Yamamoto Fall 1999');
  expect(screen.getByText('1 selected')).toBeInTheDocument();

  openKind('Views');
  // "1 selected" over a pane holding none of it is a bar the reader cannot
  // check, and a press on it adds something they cannot see.
  expect(screen.queryByText('1 selected')).toBeNull();
});

// ── The two destructive acts ──────────────────────────────────────────────

test('the button that unsaves says so, and is the only one wearing the danger token', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  const unsave = within(showCards()[0]).getByText('Unsave');
  expect(unsave).toHaveClass('ar-btn-danger');
  expect(unsave).toHaveAttribute(
    'title', 'Take it out of the library. It leaves every album with it.');
  // Nothing else on this page claims that token.
  expect(document.querySelectorAll('.ar-btn-danger')).toHaveLength(showCards().length);
});

test('unsaving something re-reads the albums, because the server has taken it out of them', async () => {
  // Four items in Resort before, three after: `album_items` is ON DELETE
  // CASCADE on the favourite, so unsaving one takes it out of every album it
  // was in — in one statement, in the database, without asking the client.
  AlbumsAPI.getAlbums
    .mockResolvedValueOnce([{ ...SHELF[0], item_count: 4 }])
    .mockResolvedValue([{ ...SHELF[0], item_count: 3 }]);
  await renderPage();
  await waitFor(() => expect(document.querySelector('.lib-album')).not.toBeNull());
  expect(within(document.querySelector('.lib-album')).getByText('4')).toBeInTheDocument();

  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));
  fireEvent.click(within(showCards()[0]).getByText('Unsave'));
  await waitFor(() => expect(API.removeShowFavourite).toHaveBeenCalled());

  // The shelf is read again and the count comes down. Without the re-read the
  // sidebar goes on claiming four items in an album that holds three, and the
  // reader only finds out by opening it.
  await waitFor(() => expect(AlbumsAPI.getAlbums).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(
    within(document.querySelector('.lib-album')).getByText('3')).toBeInTheDocument());
});

test('a ticked thing that is unsaved stops being ticked', async () => {
  await renderPage();
  openKind('Shows');
  await waitFor(() => expect(showCards()).toHaveLength(2));

  tick('Yohji Yamamoto Fall 1999');
  tick('Raf Simons Fall 2001');
  fireEvent.click(within(showCards()[0]).getByText('Unsave'));

  // One left, and it is the one still on screen — a selection holding an id
  // the library no longer has would file a row that does not exist.
  await waitFor(() => expect(screen.getByText('1 selected')).toBeInTheDocument());
});

// ── Paging ────────────────────────────────────────────────────────────────
//
// The library used to fetch every favourite on every mount. It now fetches one
// page per kind and asks for the rest on a control. What is pinned here is the
// part that is easy to get wrong and impossible to see: the counts must be the
// SERVER's, not the loaded rows'; the panes must page independently, because
// the kinds are interleaved by date and one shared page would leave the Views
// pane empty behind four hundred looks; and a page that fails must not look
// like the end of the library.

const manyLooks = (count) => Array.from({ length: count }, (_, i) => ({
  ...LOOK,
  id: `fav-look-${i}`,
  look: { number: i + 1, total: 40 },
  image_path: `shows/1234/look-${i + 1}.jpg`,
}));

const moreButton = () => document.querySelector('.lib-more-btn');

test('each pane asks for its own kind, not for the whole library', async () => {
  await renderPage();

  // Three requests, one per kind, each naming it. A single unkinded fetch is
  // the thing this replaced: interleaved by date, it would fill the first page
  // with whatever was saved most recently and leave the other panes empty.
  const kinds = API.getFavouritesPage.mock.calls.map(([args]) => args.kind);
  expect(kinds.sort()).toEqual(['look', 'show', 'view']);
  for (const [args] of API.getFavouritesPage.mock.calls) {
    expect(args.limit).toBeGreaterThan(0);
    expect(args.cursor).toBeUndefined();
  }
});

test('the counts are the server’s, not the number of rows loaded', async () => {
  serve(manyLooks(412), { pageSize: 200 });
  await renderPage();

  // 412, with 200 drawn. Counting the loaded rows would tell a reader with
  // four hundred saved looks that they have two hundred — and the number they
  // are being told is the one thing on this page they cannot check by eye.
  await waitFor(() => expect(within(kindRow('Looks')).getByText('412')).toBeInTheDocument());
  expect(document.querySelectorAll('.fav-thumb')).toHaveLength(200);
  expect(screen.getByText('All looks').closest('.fav-collection'))
    .toHaveTextContent('412 looks');
});

test('the control loads the next page and appends it', async () => {
  serve(manyLooks(412), { pageSize: 200 });
  await renderPage();

  await waitFor(() => expect(moreButton()).not.toBeNull());
  // It says how much is left rather than just "more": a control with no end in
  // sight over a library of four hundred is a control nobody presses twice.
  expect(moreButton()).toHaveTextContent('200 of 412 shown');

  fireEvent.click(moreButton());

  await waitFor(() => expect(document.querySelectorAll('.fav-thumb')).toHaveLength(400));
  // The cursor came from the server's answer and went back untouched.
  const [last] = API.getFavouritesPage.mock.calls[API.getFavouritesPage.mock.calls.length - 1];
  expect(last).toEqual({ kind: 'look', limit: 200, cursor: 'fav-look-199' });

  fireEvent.click(moreButton());
  await waitFor(() => expect(document.querySelectorAll('.fav-thumb')).toHaveLength(412));
  // And at the end of the list the control is gone, rather than sitting there
  // fetching nothing.
  await waitFor(() => expect(moreButton()).toBeNull());
});

test('the panes page independently of each other', async () => {
  // Three views, saved before four hundred looks. One shared page over the
  // interleaved list would put all four hundred looks in front of them.
  serve([...manyLooks(400), VIEW, OTHER_VIEW], { pageSize: 2 });
  await renderPage();

  openKind('Views');

  // Both views, on the first page of their own pane, with no looks loaded
  // beyond that pane's own first two.
  await waitFor(() => expect(viewRows()).toHaveLength(2));
  expect(within(kindRow('Views')).getByText('2')).toBeInTheDocument();
  expect(within(kindRow('Looks')).getByText('400')).toBeInTheDocument();
  // Nothing left to load in this pane, so no control over it.
  expect(moreButton()).toBeNull();
});

test('a page that fails leaves the control pressable rather than ending the list',
  async () => {
    serve(manyLooks(412), { pageSize: 200 });
    await renderPage();
    await waitFor(() => expect(moreButton()).not.toBeNull());

    const working = API.getFavouritesPage.getMockImplementation();
    API.getFavouritesPage.mockRejectedValueOnce(new Error('down'));
    fireEvent.click(moreButton());

    // Still 200 drawn, and the control is still there — a reader whose
    // network blipped must not be told their library ends at two hundred.
    await waitFor(() => expect(moreButton()).toBeEnabled());
    expect(document.querySelectorAll('.fav-thumb')).toHaveLength(200);

    API.getFavouritesPage.mockImplementation(working);
    fireEvent.click(moreButton());
    await waitFor(() => expect(document.querySelectorAll('.fav-thumb')).toHaveLength(400));
  });

test('unsaving a row brings the count down with it', async () => {
  serve(manyLooks(412), { pageSize: 200 });
  await renderPage();
  await waitFor(() => expect(within(kindRow('Looks')).getByText('412')).toBeInTheDocument());

  fireEvent.click(document.querySelector('.fav-remove'));

  await waitFor(() => expect(API.removeFavourite).toHaveBeenCalled());
  // 411, from 412 — not recounted off the loaded rows, which would drop it to
  // 199, and not left at 412, which would be a count the reader can see is
  // wrong the moment the list is short enough to count.
  await waitFor(() => expect(within(kindRow('Looks')).getByText('411')).toBeInTheDocument());
});
