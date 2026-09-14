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
//
// `favourites_collection_id` in backend/userdata/schema.sql is the same rule,
// and this is written to be the same rule and not merely a similar one — the
// column that function fills is what `showIdOf` below prefers, so a client
// that read the url differently from the database would open one show from an
// album tile and refuse to open it from a library tile. Two things follow from
// that file and neither is decoration:
//
//   `id` wins over `collection`, wherever both appear and in whichever order,
//   because that is `qs.get("id") or qs.get("collection")` in
//   firstview.collection_id_from_url — the two alternatives are tried in turn
//   rather than matched as one `(?:id|collection)` group, which answers with
//   whichever comes FIRST IN THE STRING and reads `?collection=99&id=1234` as
//   show 99.
//
//   a value ends where a query parameter ends — `&`, `#`, or the end of the
//   string — so `?id=1234#top` is show 1234 and `?id=123abc` is not a show id
//   at all.
const ID_PARAM = /[?&]id=(\d+)(?:[&#]|$)/;
const COLLECTION_PARAM = /[?&]collection=(\d+)(?:[&#]|$)/;

export function collectionIdOf(collection) {
  const url = String((collection || {}).url || '');
  const byId = ID_PARAM.exec(url);
  if (byId) return byId[1];
  const byCollection = COLLECTION_PARAM.exec(url);
  return byCollection ? byCollection[1] : null;
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
