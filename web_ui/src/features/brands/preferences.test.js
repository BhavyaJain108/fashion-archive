import {
  clampDetailPanelWidth,
  detailPanelMaxWidth,
  DETAIL_PANEL_MIN_WIDTH,
} from './BrandsPage';

// normalizeSortBy moved to shared/lib/preferences.js with the other two
// stored-value enums; its tests moved with it.

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
