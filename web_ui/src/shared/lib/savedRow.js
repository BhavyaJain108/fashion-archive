// What a saved row is, for the two pages that draw one.
//
// These were all four inside LibraryPage.js, which was their only reader
// until the album grid. They are here rather than imported out of that page
// for the reason `preferences.js` and `designerName.js` are here: a saved
// view must read the same in an album as it does in the library, and two
// copies of one regex is two chances for the two to stop agreeing.

// What a row is, when the row is old enough not to say. Rows saved before
// kinds existed carry no `kind` at all, and the server reads those as looks.
export const kindOf = (row) => (row && row.kind) || 'look';

// What each filter is called on screen. The keys are FILTER_KEYS from
// routes.js; the words are the ones the archive's own facets use, so a saved
// view reads the same wherever it is drawn as it did where it was made.
//
// A designer is deliberately not in this list. A saved view is its filters,
// `designer` is not one of them, and the star in the filter bar is disabled
// in designer mode for that reason.
export const FILTER_LABELS = {
  letter: 'Brand',
  gender: 'Gender',
  year: 'Year',
  season: 'Season',
  category: 'Type',
  shootType: 'Shoot',
  city: 'City',
};

// A saved view's filters as [label, value] pairs, in the order FILTER_LABELS
// names them rather than whatever order the object arrived in — two readers
// who saved the same view must see the same line.
export function filterPairs(filters) {
  const f = filters || {};
  return Object.keys(FILTER_LABELS)
    .filter(key => f[key])
    .map(key => [FILTER_LABELS[key], String(f[key])]);
}

// firstVIEW's own collection id, pulled out of the collection url it is a
// query parameter of (`…/collection_images.php?id=1234&list=all`).
//
// See routes.js, where a show URL is /hf/<slug>/<collectionId> and the id is
// the only authoritative segment. A crawled row whose url carries no id is
// not openable, and this answers null rather than building
// /hf/<slug>/undefined.
export function collectionIdOf(collection) {
  const match = /[?&](?:id|collection)=(\d+)(?:&|$)/
    .exec(String((collection || {}).url || ''));
  return match ? match[1] : null;
}

// The same id, preferring the column over the parse.
//
// Phase 4 task 1 put `collection_id` on `favourites` precisely so this stops
// being a regex over a URL: both phase-3 bugs were URL-spelling differences
// a stored id would not have had. The parse stays as the fallback for rows
// saved before that column existed and never backfilled.
export function showIdOf(collection) {
  const stored = (collection || {}).id;
  if (stored !== null && stored !== undefined && String(stored) !== '') {
    return String(stored);
  }
  return collectionIdOf(collection);
}
