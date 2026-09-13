import { normalizeViewMode } from './HighFashionPage';

// Viewer only ever branches on 'single' or 'grid' (see Viewer.js). A stored
// value that predates a spelling change, or one poked in through devtools,
// must not slip through and render neither branch.
describe('normalizeViewMode', () => {
  test('passes through the two values Viewer actually handles', () => {
    expect(normalizeViewMode('single')).toBe('single');
    expect(normalizeViewMode('grid')).toBe('grid');
  });

  test('an unrecognised value falls back to the default instead of rendering a blank pane', () => {
    expect(normalizeViewMode('gird')).toBe('single');
    expect(normalizeViewMode('')).toBe('single');
    expect(normalizeViewMode(null)).toBe('single');
    expect(normalizeViewMode(undefined)).toBe('single');
    expect(normalizeViewMode(42)).toBe('single');
  });
});
