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
  filters: { gender: 'Women', year: '', season: '', category: '',
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

  test('it says whether this view is already kept', () => {
    render(<Filters {...filterProps({ activeFilterCount: 1, viewSaved: true })} />);
    expect(screen.getByRole('button', { name: 'Save this view' }))
      .toHaveAttribute('aria-pressed', 'true');
  });
});
