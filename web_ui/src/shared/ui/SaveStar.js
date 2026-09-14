import React from 'react';
import './SaveStar.css';

// The star. One component, in four places: the single view, a grid tile, a
// row of the show list, and the filter bar.
//
//   <SaveStar saved={bool} onToggle={fn} label="Save this show" size="sm" />
//
// The affordance, in the reader's words: "like stars on Apple Music, both in
// terms of placement and how to click on them." That is a whole
// specification — a consistent position on the item, outline until saved,
// filled when saved, one click to toggle, and no confirmation, no menu, no
// "which album?" in between. Everything below follows from it.
//
// A <button>, not a <div> with an onClick. It is in the tab order, it is
// pressed with Enter or Space without anything here handling a key, and it
// says what it is and whether it is on — `aria-pressed` for the state, and a
// label naming the thing, because "Save this show" and "Save look 12" are
// different promises and a reader who cannot see which row the star is on
// has nothing else to tell them apart.
//
// It renders in both states and takes the same box in both, and it renders
// whether or not the saves have loaded. That is deliberate and it is what
// keeps a list still: saves arrive over the network, and a star that took
// space only once it was known to be lit would jolt every row it landed in.
// The box is in SaveStar.css, on `.ar-star`, in one place.
function SaveStar({
  saved = false,
  onToggle,
  label,
  // Defaults to the label. Passed separately only where the tooltip carries
  // something the accessible name should not, like the keyboard shortcut.
  title,
  size = 'md',
  disabled = false,
  className = '',
}) {
  // The one rule that makes this safe to put inside something clickable: a
  // star on a show row sits inside a row that opens the show, and on a grid
  // tile inside a tile that selects the look. Starring is not opening. The
  // click stops here — on mousedown too, so a parent that acts on the press
  // rather than on the click is no different.
  const handleClick = (event) => {
    event.stopPropagation();
    // A disabled button dispatches no click in a browser; this is for the
    // paths that do not go through one.
    if (disabled) return;
    if (onToggle) onToggle(event);
  };

  return (
    <button
      type="button"
      className={`ar-star ${size} ${saved ? 'on' : ''} ${className}`.trim()}
      onClick={handleClick}
      onMouseDown={(event) => event.stopPropagation()}
      disabled={disabled}
      aria-pressed={saved}
      aria-label={label}
      title={title || label}
    >
      {/* Outline until saved, filled when saved. The two glyphs are the same
          width in the archive's monospace face, and the box around them is
          fixed anyway, so the swap moves nothing. */}
      <span aria-hidden="true">{saved ? '★' : '☆'}</span>
    </button>
  );
}

export default SaveStar;
