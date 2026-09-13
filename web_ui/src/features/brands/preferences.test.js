import {
  normalizeSortBy,
  clampDetailPanelWidth,
  detailPanelMaxWidth,
  DETAIL_PANEL_MIN_WIDTH,
} from './BrandsPage';

// The <select> only ever offers these five values (including the empty
// "Sort by..." default). A stored option an old build removed must not
// silently sort by nothing recognisable.
describe('normalizeSortBy', () => {
  test('passes through every option the sort <select> offers', () => {
    expect(normalizeSortBy('')).toBe('');
    expect(normalizeSortBy('name-asc')).toBe('name-asc');
    expect(normalizeSortBy('name-desc')).toBe('name-desc');
    expect(normalizeSortBy('price-asc')).toBe('price-asc');
    expect(normalizeSortBy('price-desc')).toBe('price-desc');
  });

  test('an option no longer offered falls back to the default', () => {
    expect(normalizeSortBy('brand-asc')).toBe('');
    expect(normalizeSortBy(null)).toBe('');
  });
});

// Same bounds as the drag handle in handleResizeMouseDown: at least
// DETAIL_PANEL_MIN_WIDTH (300), at most half the viewport.
describe('clampDetailPanelWidth', () => {
  const originalInnerWidth = window.innerWidth;

  afterEach(() => {
    window.innerWidth = originalInnerWidth;
  });

  test('a value within bounds passes through unchanged', () => {
    window.innerWidth = 1200; // max = 600
    expect(clampDetailPanelWidth(400)).toBe(400);
  });

  test('zero, negative, and a too-small value clamp up to the minimum', () => {
    window.innerWidth = 1200;
    expect(clampDetailPanelWidth(0)).toBe(DETAIL_PANEL_MIN_WIDTH);
    expect(clampDetailPanelWidth(-50)).toBe(DETAIL_PANEL_MIN_WIDTH);
    expect(clampDetailPanelWidth(299)).toBe(DETAIL_PANEL_MIN_WIDTH);
  });

  test('an absurdly large value clamps down to the same max the drag handle enforces', () => {
    window.innerWidth = 1200; // max = 600
    expect(clampDetailPanelWidth(99999)).toBe(detailPanelMaxWidth());
    expect(clampDetailPanelWidth(99999)).toBe(600);
  });
});
