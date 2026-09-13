// `extractLookNumber` parses a number out of an image filename and falls
// back to the array index — it counts images in a collection, not a
// designer's numbered looks. Detail shots and back views inflate the count,
// so a collection's "LOOK 34" is frequently not that designer's thirty-fourth
// look. The word is a claim the data does not support.
//
// The number itself does not move: it is `look_number`, the identity of
// every favourite a user has ever saved, in the `favourites` table's unique
// index. Renumbering would orphan their saved work. So this module only
// decides the label — what the number is called on screen — never the
// number.
export function lookLabel(number) {
  if (number === null || number === undefined || Number.isNaN(number)) return '';
  return String(number).padStart(2, '0');
}

export function lookCounter(number, total) {
  return `${lookLabel(number)} / ${total}`;
}

// Alt text is read aloud by a screen reader, not read visually alongside the
// image it labels — a bare "07" means nothing spoken cold. This is why it
// stays a separate function from lookLabel rather than reusing its output.
export function lookAlt(number, designer) {
  return designer ? `Look ${number} by ${designer}` : `Look ${number}`;
}

export default lookLabel;
