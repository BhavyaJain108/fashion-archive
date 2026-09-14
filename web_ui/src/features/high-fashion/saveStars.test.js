import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

import Viewer from './Viewer';
import ShowList from './ShowList';
import Filters from './Filters';

// The star in its four places.
//
// One thing is asked of every one of them: pressing it saves the thing it
// sits on, and pressing it does NOT do whatever pressing the thing it sits on
// does. A star on a show row that also opens the show, or on a grid tile that
// also selects the look, is the defect this task was most likely to ship, so
// each site asserts the parent's handler was not called.

jest.mock('../../shared/api', () => ({
  FashionArchiveAPI: { getImageUrl: (p) => `/images/${p}` },
}));

const IMAGES = ['gucci/look-01.jpg', 'gucci/look-02.jpg', 'gucci/look-03.jpg'];
const lookOf = (path, idx) => idx + 1;

const viewerProps = (over = {}) => ({
  images: IMAGES,
  imagesLoading: false,
  imagesStale: false,
  imagesError: null,
  imagesCollection: null,
  expectedCount: IMAGES.length,
  streamComplete: true,
  currentImageIndex: 1,
  setCurrentImageIndex: jest.fn(),
  currentLookNumber: 2,
  extractLookNumber: lookOf,
  selectedCollection: null,
  viewMode: 'single',
  setViewMode: jest.fn(),
  selectImageFromGrid: jest.fn(),
  isFavourite: () => false,
  toggleFavourite: jest.fn(),
  showVideo: false,
  videoData: null,
  videoState: 'idle',
  ...over,
});

const ROWS = [
  { collection_id: '1', url: 'https://ex.test/show/1234',
    season_url: 'https://ex.test/season/fw99',
    designer: 'Yohji Yamamoto', designer_name: 'Yohji Yamamoto',
    year: '1999', season: 'Fall / Winter', subtitle: 'Runway Collection — Paris' },
  { collection_id: '2', url: 'https://ex.test/show/5678',
    season_url: 'https://ex.test/season/fw01',
    designer: 'Raf Simons', designer_name: 'Raf Simons',
    year: '2001', season: 'Fall / Winter', subtitle: 'Runway Collection — Paris' },
];

const listProps = (over = {}) => ({
  designerMode: null,
  searchText: '',
  exitDesigner: jest.fn(),
  visibleCollections: ROWS,
  indexReady: true,
  cursor: { total: 2, hasMore: false },
  designerRows: [],
  handleListScroll: jest.fn(),
  listLoading: false,
  listError: null,
  selectedCollection: null,
  handleCollectionSelect: jest.fn(),
  designerLoading: false,
  loadingMore: false,
  isShowSaved: () => false,
  toggleShowSave: jest.fn(),
  ...over,
});

const filterProps = (over = {}) => ({
  designerIndex: null,
  query: '',
  setQuery: jest.fn(),
  searchFocused: false,
  setSearchFocused: jest.fn(),
  handleSearchKeyDown: jest.fn(),
  suggestionList: [],
  activeSuggestion: 0,
  setActiveSuggestion: jest.fn(),
  chooseSuggestion: jest.fn(),
  indexReady: true,
  designerMode: null,
  // The archive at rest, as the page actually holds it with the index ready:
  // gender is empty, because "All" is the default once All is on offer. It
  // used to say 'Women' here alongside indexReady: true, which is a pair of
  // values the page only ever holds for the beat before getIndexStatus
  // answers — and the star's rule now reads gender, so the fixture has to be
  // a state the page is really in.
  filters: { gender: '', year: '', season: '', category: '',
             shootType: '', city: '', letter: '' },
  setFilter: jest.fn(),
  years: [],
  designerYears: null,
  seasonsAvailable: [],
  designerSeasons: null,
  categoriesAvailable: [],
  designerCategories: null,
  designerShootTypes: null,
  facetValues: () => [],
  facetCount: () => 0,
  clearFilters: jest.fn(),
  activeFilterCount: 0,
  viewSaved: false,
  toggleViewSave: jest.fn(),
  ...over,
});

// ── 1. The single view ────────────────────────────────────────────────────

describe('the single view', () => {
  test('keeps the look on screen, by its number and its photograph', () => {
    const props = viewerProps();
    render(<Viewer {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save look 2' }));
    expect(props.toggleFavourite).toHaveBeenCalledWith(2, 'gucci/look-02.jpg');
  });

  test('the star is lit when the look is kept, and the tooltip still names F', () => {
    render(<Viewer {...viewerProps({ isFavourite: (n) => n === 2 })} />);
    const star = screen.getByRole('button', { name: 'Save look 2' });
    expect(star).toHaveAttribute('aria-pressed', 'true');
    expect(star).toHaveAttribute('title', 'Remove from favourites (F)');
  });
});

// ── 2. The grid tile ──────────────────────────────────────────────────────

describe('a grid tile', () => {
  const grid = (over) => viewerProps({ viewMode: 'grid', ...over });

  test('every tile has a star, top right, whatever is saved', () => {
    render(<Viewer {...grid()} />);
    expect(screen.getAllByRole('button', { name: /^Save look/ })).toHaveLength(3);
  });

  test('pressing it keeps that look', () => {
    const props = grid();
    render(<Viewer {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save look 3' }));
    expect(props.toggleFavourite).toHaveBeenCalledWith(3, 'gucci/look-03.jpg');
  });

  test('pressing it does NOT select the tile', () => {
    const props = grid();
    render(<Viewer {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save look 3' }));
    expect(props.selectImageFromGrid).not.toHaveBeenCalled();

    // And the tile itself still selects, so the star did not disarm it.
    fireEvent.click(document.querySelectorAll('.hf2-grid-item')[2]);
    expect(props.selectImageFromGrid).toHaveBeenCalledWith(2);
  });
});

// ── 3. A show list row ────────────────────────────────────────────────────

describe('a show list row', () => {
  test('pressing the star keeps the whole show', () => {
    const props = listProps();
    render(<ShowList {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save this show — Raf Simons' }));
    expect(props.toggleShowSave).toHaveBeenCalledWith(ROWS[1]);
  });

  test('pressing the star does NOT open the show', () => {
    const props = listProps();
    render(<ShowList {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save this show — Raf Simons' }));
    expect(props.handleCollectionSelect).not.toHaveBeenCalled();

    // The row still opens when the row is what was pressed.
    fireEvent.click(screen.getByText('Raf Simons'));
    expect(props.handleCollectionSelect).toHaveBeenCalledWith(ROWS[1]);
  });

  test('the star is lit only on the row that is saved', () => {
    render(<ShowList {...listProps({ isShowSaved: (row) => row.url === ROWS[0].url })} />);
    expect(screen.getByRole('button', { name: 'Save this show — Yohji Yamamoto' }))
      .toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Save this show — Raf Simons' }))
      .toHaveAttribute('aria-pressed', 'false');
  });

  // The reflow guarantee, on the React side: the star is not conditional on
  // anything, so no row gains a child when the saves finally land. (The box
  // itself is .ar-star's, and was measured in a browser — see the report.)
  test('every row has a star before any save has loaded', () => {
    const { rerender } = render(<ShowList {...listProps()} />);
    const before = document.querySelectorAll('.hf2-collection-item .ar-star').length;
    expect(before).toBe(ROWS.length);

    // Saves arrive: same number of stars, same markup, one class different.
    rerender(<ShowList {...listProps({ isShowSaved: () => true })} />);
    expect(document.querySelectorAll('.hf2-collection-item .ar-star')).toHaveLength(before);
    expect(document.querySelectorAll('.hf2-collection-item .ar-star.on')).toHaveLength(before);
  });
});

// ── 4. The filter bar ─────────────────────────────────────────────────────

describe('the filter bar', () => {
  test('with nothing filtered the star is off: everything is not a view', () => {
    const props = filterProps({ activeFilterCount: 0 });
    render(<Filters {...props} />);
    const star = screen.getByRole('button', { name: 'Save this view' });
    expect(star).toBeDisabled();
    fireEvent.click(star);
    expect(props.toggleViewSave).not.toHaveBeenCalled();
  });

  test('with a filter set it keeps the view', () => {
    const props = filterProps({ activeFilterCount: 2 });
    render(<Filters {...props} />);
    const star = screen.getByRole('button', { name: 'Save this view' });
    expect(star).not.toBeDisabled();
    fireEvent.click(star);
    expect(props.toggleViewSave).toHaveBeenCalledTimes(1);
  });

  test('it sits beside Clear and does not clear', () => {
    const props = filterProps({ activeFilterCount: 2 });
    render(<Filters {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save this view' }));
    expect(props.clearFilters).not.toHaveBeenCalled();
    expect(document.querySelector('.hf2-filter-actions .hf2-filter-clear')).not.toBeNull();
    expect(document.querySelector('.hf2-filter-actions .ar-star')).not.toBeNull();
  });

  // Gender is the filter the "Clear N filters" badge does not count, and the
  // star has to disagree with the badge about it — see `viewSavable` in
  // Filters.js. These two are that disagreement, in both directions.
  test('a gender chosen from All is a view, though the badge does not count it', () => {
    const props = filterProps({
      activeFilterCount: 0,
      indexReady: true,
      filters: { gender: 'Men', year: '', season: '', category: '',
                 shootType: '', city: '', letter: '' },
    });
    render(<Filters {...props} />);
    const star = screen.getByRole('button', { name: 'Save this view' });
    expect(star).not.toBeDisabled();
    fireEvent.click(star);
    expect(props.toggleViewSave).toHaveBeenCalledTimes(1);
  });

  test('a gender the crawl requires is not a view', () => {
    // No local index: the segmented control offers Women and Men and no All,
    // so a gender is not something the reader chose and the screen is still
    // the whole of what this page can show.
    const props = filterProps({
      activeFilterCount: 0,
      indexReady: false,
      filters: { gender: 'Women', year: '', season: '', category: '',
                 shootType: '', city: '', letter: '' },
    });
    render(<Filters {...props} />);
    expect(screen.getByRole('button', { name: 'Save this view' })).toBeDisabled();
  });

  // ── designer mode and search: list state a view cannot hold ───────────
  //
  // `openDesigner` clears gender and letter and leaves year, season,
  // category, shootType and city set, so the star was enabled in designer
  // mode with nothing further pressed. Saving there stored the FILTER_KEYS
  // filters alone and lost the designer, so reopening the view gave every
  // show of that year rather than that designer's.
  //
  // Worse was `isViewSaved(filters)`, which is designer-blind in the same
  // way: with {year:'1997'} already saved the star rendered FILLED in
  // designer mode, and pressing it deleted that unrelated saved view — a row
  // the reader cannot even see from here.
  //
  // `designer` is not in FILTER_KEYS, `buildRoute` never writes it and
  // designer mode has no URL, so making it savable is a route-schema change.
  // Until then the star is off in both states, and says so.

  const withFilter = (over = {}) => filterProps({
    activeFilterCount: 2,
    filters: { gender: '', year: '1997', season: '', category: 'Ready-to-Wear',
               shootType: '', city: '', letter: '' },
    ...over,
  });

  test('in designer mode the star is off, though the filters survived', () => {
    const props = withFilter({ designerMode: { id: '77', name: 'Helmut Lang' } });
    render(<Filters {...props} />);
    const star = screen.getByRole('button', { name: 'Save this view' });
    expect(star).toBeDisabled();
    fireEvent.click(star);
    expect(props.toggleViewSave).not.toHaveBeenCalled();
  });

  test('during a search the star is off for the same reason', () => {
    const props = withFilter({ searchText: 'yohji' });
    render(<Filters {...props} />);
    const star = screen.getByRole('button', { name: 'Save this view' });
    expect(star).toBeDisabled();
    fireEvent.click(star);
    expect(props.toggleViewSave).not.toHaveBeenCalled();
  });

  test('it says why, rather than greying with no reason', () => {
    render(<Filters {...withFilter({ designerMode: { id: '77', name: 'Helmut Lang' } })} />);
    expect(screen.getByRole('button', { name: 'Save this view' }))
      .toHaveAttribute('title', expect.stringContaining('designer'));
  });

  // The delete this prevents. A saved {year:'1997'} lights the star on the
  // archive list; in designer mode the same filters are still set, so
  // `isViewSaved` says saved there too. Unlit and unpressable is what stops
  // a press from deleting it.
  test.each([
    ['designer mode', { designerMode: { id: '77', name: 'Helmut Lang' } }],
    ['a search', { searchText: 'yohji' }],
  ])('a view saved elsewhere cannot be deleted from %s', (_name, over) => {
    const props = withFilter({ viewSaved: true, ...over });
    render(<Filters {...props} />);
    const star = screen.getByRole('button', { name: 'Save this view' });
    expect(star).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(star);
    expect(props.toggleViewSave).not.toHaveBeenCalled();
  });

  test('it says whether this view is already kept', () => {
    render(<Filters {...filterProps({ activeFilterCount: 1, viewSaved: true })} />);
    expect(screen.getByRole('button', { name: 'Save this view' }))
      .toHaveAttribute('aria-pressed', 'true');
  });
});
