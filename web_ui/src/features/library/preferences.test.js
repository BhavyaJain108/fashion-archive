import { normalizeGroupMode, normalizeViewMode } from './LibraryPage';

// The sidebar only ever renders two groupings; the gallery only ever
// renders two panes. A restored value outside either set must fall back to
// the default rather than leaving the page in a state nothing else agrees
// with.
describe('normalizeGroupMode', () => {
  test('passes through the two groupings the sidebar chips render', () => {
    expect(normalizeGroupMode('view-all')).toBe('view-all');
    expect(normalizeGroupMode('by-collection')).toBe('by-collection');
  });

  test('an invalid enum falls back to the default', () => {
    expect(normalizeGroupMode('by-designer')).toBe('view-all');
    expect(normalizeGroupMode('')).toBe('view-all');
    expect(normalizeGroupMode(null)).toBe('view-all');
  });
});

describe('normalizeViewMode', () => {
  test('passes through the two panes the gallery renders', () => {
    expect(normalizeViewMode('single')).toBe('single');
    expect(normalizeViewMode('grid')).toBe('grid');
  });

  test('an invalid enum falls back to the default', () => {
    expect(normalizeViewMode('gird')).toBe('single');
    expect(normalizeViewMode(7)).toBe('single');
  });
});
