// The season a row belongs to, taken from the row rather than from the
// filters — with the filters empty there is no selected season to read, and
// the row has always known its own.
//
// Exported rather than threaded through props: the status bar, the video
// lookup and the favourite writer all need it, and passing a module-level
// pure function down as a prop was only ever a symptom of it not being
// importable.
export function videoSeasonName(collection) {
  if (!collection) return '';
  const { season, year } = collection;
  if (season && year) return `${season} ${year}`;
  return year ? String(year) : '';
}

export default videoSeasonName;
