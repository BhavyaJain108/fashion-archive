// How many looks the stream has promised and not yet delivered.
//
// Two parts of the screen are the same sentence — "the rest of this show is
// still coming" — and they were two independent formulas:
//
//   ThumbStrip drew that many empty slots, so the strip is its final width
//   from the first photograph and the show visibly fills in.
//   StatusBar printed the word "arriving" when there were any.
//
// They agreed, and nothing made them. A change to one — a clamp instead of
// a gate, one more reason to stop — left the strip drawing slots for looks
// the bar had stopped promising, or the bar promising looks the strip had
// no room for.
//
// Three states answer zero, and each is a defect that was fixed separately
// in the two places:
//
//   isStale — a different show has been asked for. `expectedCount` is
//   already the NEW show's total (meta arrives before the first
//   photograph) while `imagesLength` is still the OLD show's, so the
//   subtraction is meaningless in both directions: negative before the new
//   meta lands, and a different show's total after it. Clamping at zero
//   hides the negative and leaves the other half standing — the previous
//   show's twelve thumbnails behind the new show's thirty-eight slots,
//   under the new show's name.
//
//   streamComplete — the stream has said it is done. A look that fails to
//   download does not fail the stream; it is logged and skipped. So
//   `expectedCount` can sit above `imagesLength` forever with nothing else
//   coming, and both a ghost slot and the word "arriving" would be about a
//   photograph that is never going to land.
//
//   Nothing outstanding — everything promised has arrived.
export function pendingLooks({
  imagesLength = 0,
  expectedCount = 0,
  isStale = false,
  streamComplete = false,
} = {}) {
  if (isStale || streamComplete) return 0;
  return expectedCount > imagesLength ? expectedCount - imagesLength : 0;
}

export default pendingLooks;
