// The stored-preference enums, and the one rule they all share: a value
// read back out of localStorage is not trusted, it is checked against the
// set the component actually renders.
//
// The value in storage was written by some earlier release, or poked in
// through devtools, or is a spelling this build no longer has. Handing one
// of those to a component that branches on two cases renders neither and
// leaves a blank pane — which is a stored string away from every user, and
// survives a reload, because the bad value is still in storage.
//
// They live together because they are one rule with three vocabularies, and
// they live under shared/lib rather than in any one page because two of
// them already had two copies: normalizeViewMode was written out verbatim
// in both HighFashionPage and LibraryPage, with a test file each, and
// nothing made the two copies agree. Phase 3 rebuilds the library page and
// adds more stored values.
//
// Each takes anything at all — a string, a number, null, undefined — and
// returns a value the caller can render.

// Single or grid. Both the archive's Viewer and the library's gallery
// branch on exactly these two.
export function normalizeViewMode(value) {
  return value === 'grid' ? 'grid' : 'single';
}

// The library sidebar's two groupings: everything in one list, or split by
// collection.
export function normalizeGroupMode(value) {
  return value === 'by-collection' ? 'by-collection' : 'view-all';
}

// The library's three kinds of saved thing. The page renders one pane per
// kind and there is no fourth pane, so a stored kind from another build — or
// a `kind` this release does not have — falls back to looks, which is the
// kind every user has had for longest.
export function normalizeKind(value) {
  return value === 'show' || value === 'view' ? value : 'look';
}

// The values the My Brands sort <select> offers. '' is the default —
// "Sort by...", archive order — and is itself one of the options, so an
// unrecognised value falls back to sorting by nothing rather than to
// sorting by something nobody chose.
const SORT_OPTIONS = ['name-asc', 'name-desc', 'price-asc', 'price-desc'];

export function normalizeSortBy(value) {
  return SORT_OPTIONS.includes(value) ? value : '';
}
