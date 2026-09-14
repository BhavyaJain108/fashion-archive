import {
  normalizeViewMode, normalizeGroupMode, normalizeSortBy,
} from './preferences';

// One rule, three vocabularies: a value restored from storage is checked
// against the set the component renders, and anything else becomes the
// default rather than a state nothing draws.
//
// These were three test files against three definitions in three pages,
// two of which held the same function twice. See preferences.js.

describe('normalizeViewMode', () => {
  test('passes through the two panes both galleries render', () => {
    expect(normalizeViewMode('single')).toBe('single');
    expect(normalizeViewMode('grid')).toBe('grid');
  });

  test('anything else falls back to the default rather than rendering a blank pane', () => {
    expect(normalizeViewMode('gird')).toBe('single');
    expect(normalizeViewMode('')).toBe('single');
    expect(normalizeViewMode(null)).toBe('single');
    expect(normalizeViewMode(undefined)).toBe('single');
    expect(normalizeViewMode(42)).toBe('single');
  });
});

describe('normalizeGroupMode', () => {
  test('passes through the two groupings the sidebar chips render', () => {
    expect(normalizeGroupMode('view-all')).toBe('view-all');
    expect(normalizeGroupMode('by-collection')).toBe('by-collection');
  });

  test('anything else falls back to the default', () => {
    expect(normalizeGroupMode('by-designer')).toBe('view-all');
    expect(normalizeGroupMode('')).toBe('view-all');
    expect(normalizeGroupMode(null)).toBe('view-all');
    expect(normalizeGroupMode(7)).toBe('view-all');
  });
});

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
    expect(normalizeSortBy(undefined)).toBe('');
  });
});

// The three defaults, together: what a first visit and an unreadable stored
// value both produce. They were spread across three files and nothing
// stated them in one place.
test('every default is what a first-time visitor gets', () => {
  expect(normalizeViewMode(undefined)).toBe('single');
  expect(normalizeGroupMode(undefined)).toBe('view-all');
  expect(normalizeSortBy(undefined)).toBe('');
});
