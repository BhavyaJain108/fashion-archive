import AlbumCanvas from './AlbumCanvas';
import ShareButton from '../../shared/ui/ShareButton';
import ShareEndpoints from '../../shared/api/share';
import React, { useMemo, useState } from 'react';
import TopBar from '../../shared/ui/TopBar';
import { FashionArchiveAPI } from '../../shared/api';
import { slugify } from '../../app/routes';
import { cleanDesignerName } from '../../shared/lib/designerName';
import { lookLabel, lookAlt } from '../../shared/lib/lookLabel';
import { filterPairs, kindOf, showIdOf } from '../../shared/lib/savedRow';
import { useAlbums } from '../../shared/hooks/useAlbums';
import './AlbumGrid.css';

// One album, as Finder's icon view: uniform tiles on an even grid, a caption
// under each, one click to select, and a sort control whose choice is the
// album's own.
//
// A SIBLING of LibraryPage, not a mode of it. `pageKeyForRoute` still calls
// this route 'library' — an album is inside the library and the nav must go
// on saying so — but none of LibraryPage's state means anything here. That
// page holds every favourite the reader has, split by kind, with a collection
// grouping, a single/grid toggle and a cursor into the looks; an album holds
// what somebody put in it, in an order they chose, and reads it through
// `useAlbums` rather than `getFavourites`. Rendering it as a mode would mount
// all of that to ignore all of it — and would fetch three pages of the library
// to show twelve tiles it does not hold.

// The three orders the table stores, and what to call them. The values are
// `SORT_ORDERS` in backend/userdata/albums.py verbatim: a fourth spelling
// here is a 400 from the PATCH, so this list is the server's list.
export const SORTS = [
  { value: 'added', label: 'Date added' },
  { value: 'designer', label: 'Designer' },
  { value: 'season', label: 'Season' },
];

// A sort_by from a row this build does not know — another release, a poked
// value — falls back to the column default rather than rendering a select
// with nothing chosen.
export const normalizeSort = (value) => (
  SORTS.some(s => s.value === value) ? value : 'added'
);

// ── The season order, which is this page's and not the server's ──────────
//
// `sort_by = 'season'` on the server is `ORDER BY f.season_name`, which is
// alphabetical over a display string: "Cruise 2018" before "Fall / Winter
// 1999" before "Spring / Summer 2020". `favourites` has no year column and no
// season column to order by, only the label, and task 2 said so in a comment
// rather than guessing at a parse in SQL.
//
// It is parsed here instead, because "sort by season" on a fashion archive
// means the calendar and nothing else, and a control that says Season and
// answers with every Fall from 1999 to 2024 followed by every Prefall is
// wrong in the one way the reader will certainly notice.
//
// Within a year the calendar runs Cruise -> Spring/Summer -> Prefall ->
// Fall/Winter. Those are backend/high_fashion/show_index.py's SEASON_RANK
// numbers unchanged — that file ranks them descending ("later seasons
// first"), and this reads the same numbers ascending.
//
// Prefall is tested before Fall on purpose: "Prefall 2016" contains "fall".
const SEASON_RANK = [
  [/pre\s*-?\s*fall/i, 3],
  [/cruise|resort/i, 1],
  [/spring|summer/i, 2],
  [/fall|autumn|winter/i, 4],
];

// A season label as something two labels can be compared by, or null when
// there is no year in it to stand on. Null is the honest answer for a saved
// view (no season at all) and for a label from a source whose spelling this
// does not know — and a null sorts last, in the order the server sent, which
// is the only order there is any evidence for.
export function seasonKey(name) {
  const text = String(name || '');
  const year = /(\d{4})/.exec(text);
  if (!year) return null;
  const hit = SEASON_RANK.find(([pattern]) => pattern.test(text));
  return { year: Number(year[1]), rank: hit ? hit[1] : 0 };
}

// The rows in the order to draw them.
//
// 'added' and 'designer' are the server's own ORDER BY over columns it holds,
// and are returned untouched — re-sorting them here would be a second opinion
// about one fact. Only 'season' is re-ordered, and only by the key above.
//
// The index each row arrived at is carried explicitly rather than leaning on
// Array.sort being stable: "keeps the order the server sent" is the whole of
// the tie-break and it should be readable as that.
export function orderItems(rows, sortBy) {
  const list = rows || [];
  if (normalizeSort(sortBy) !== 'season') return list;
  return list
    .map((row, at) => ({ row, at, key: seasonKey((row.season || {}).name) }))
    .sort((a, b) => {
      if (!a.key || !b.key) {
        if (a.key) return -1;
        if (b.key) return 1;
        return a.at - b.at;
      }
      return (a.key.year - b.key.year)
        || (a.key.rank - b.key.rank)
        || (a.at - b.at);
    })
    .map(entry => entry.row);
}

// ── The caption under a tile ─────────────────────────────────────────────
//
// Two lines for every kind, both single-line: the name, and what tells two
// rows with the same name apart. Two lines and not one because the tile's
// height is the grid's row height, and a designer long enough to wrap would
// otherwise make its own row taller than every other row on screen.
export function captionOf(item) {
  const r = item;
  const kind = kindOf(r);

  if (kind === 'view') {
    const pairs = filterPairs((r.view || {}).filters);
    return {
      name: (r.view || {}).name || 'Saved view',
      sub: pairs.length === 0
        ? 'Everything'
        : `${pairs.length} filter${pairs.length === 1 ? '' : 's'}`,
    };
  }

  const designer = cleanDesignerName((r.collection || {}).designer || '');
  const season = (r.season || {}).name || '';
  if (kind === 'show') return { name: designer, sub: season };

  const label = lookLabel((r.look || {}).number);
  return { name: designer, sub: season ? `${label} · ${season}` : label };
}

// ── One tile ─────────────────────────────────────────────────────────────
//
// Every kind is the same rectangle: `.alb-tile-box`, a 3:4 box the CSS gives
// a height from its width, with whatever is inside it positioned absolutely
// so that nothing inside can change its size. That is the no-reflow rule, and
// it is one rule for all three kinds rather than three that happen to agree.
//
// What goes in the box, and why:
//
//   look   the photograph. It is what the reader put in the album.
//
//   show   its cover photograph, framed and tagged SHOW. A show is a run of
//          looks, not one photograph of one, and drawing it as a look is the
//          bug the library's own shows pane was built to fix — it came
//          through the look gallery and rendered as a look with no number.
//          The tag is what a folder's shape is in Finder: the thing that says
//          this one contains the others.
//
//   view   its filters, drawn as the chips the library draws for a view. A
//          view has no image at all, so there is no photograph to show and
//          nothing to stand in for one — the filters ARE the view, and they
//          fit in the box the other kinds' photographs occupy.
//
// No <img> element is written at all unless there is an `image_path` to put
// in it. A src of '' or undefined is a request for the page itself and a
// broken-image glyph in the box, which is the one thing this must not draw —
// so the empty box is the box, and a show or a look whose image never made it
// to storage looks like the view tile's ground rather than like a failure.
function Tile({ item, selected, onSelect, onOpen }) {
  const r = item;
  const kind = kindOf(r);
  const caption = captionOf(r);
  const image = r.image_path || '';
  const pairs = kind === 'view' ? filterPairs((r.view || {}).filters) : [];

  return (
    <button
      type="button"
      className={`alb-tile alb-tile-${kind} ${selected ? 'selected' : ''}`}
      aria-pressed={selected}
      onClick={() => onSelect(r)}
      onDoubleClick={() => onOpen(r)}
    >
      <span className="alb-tile-box">
        {kind === 'view' ? (
          <span className="alb-tile-filters">
            {pairs.length === 0 ? (
              <span className="alb-filter">Everything</span>
            ) : pairs.map(([label, value]) => (
              <span className="alb-filter" key={label}>
                <span className="k">{label}</span>
                <span className="v">{value}</span>
              </span>
            ))}
          </span>
        ) : image ? (
          <img
            className="alb-tile-photo"
            src={FashionArchiveAPI.getImageUrl(image)}
            alt={kind === 'look'
              ? lookAlt((r.look || {}).number, caption.name)
              : caption.name}
            loading="lazy"
          />
        ) : null}

        {kind === 'look' ? null : (
          <span className="alb-tile-tag">{kind === 'show' ? 'Show' : 'View'}</span>
        )}
      </span>

      <span className="alb-tile-name">{caption.name}</span>
      <span className="alb-tile-sub">{caption.sub}</span>
    </button>
  );
}

// ── The page ─────────────────────────────────────────────────────────────

// `navigate` is a prop here for the same reason it is one on LibraryPage: both
// directions out of this page are addresses, and a page that imports the thing
// that writes them cannot be rendered without it.
function AlbumGrid({
  currentPage, onPageSwitch, currentUser, onLogout, albumId, navigate,
}) {
  // `shelf: false` — this page draws one album and no shelf, and the shelf is
  // the library sidebar's. Without it, opening an album made two requests and
  // discarded the answer to one of them.
  const {
    album, items, itemsLoading, setAlbumOptions, removeFromAlbum,
  } = useAlbums(albumId, { shelf: false });

  // Which tile is selected, by favourite id. Not by index: the list is
  // re-ordered by the sort control and re-read from the server after it, and
  // an index would move the selection to whatever landed in that slot.
  const [selectedId, setSelectedId] = useState(null);

  const sortBy = normalizeSort(album && album.sort_by);
  const ordered = useMemo(() => orderItems(items, sortBy), [items, sortBy]);

  // Both directions are addresses. Back is not history.back(): the reader may
  // have arrived on this album from a link, from a reload, or from anywhere
  // at all, and "back" has to mean the library in every one of those. It is
  // navigate + buildRoute, which is the one mechanism this app navigates by.
  const back = () => navigate({ page: 'library' });

  // Opening a tile, for the two kinds that live somewhere else and the one
  // that lives inside a show.
  //
  // Everything comes off one row, read once, in the one expression that uses
  // it — the same rule the library's removal path is written under. A slug
  // assembled from one row and a collection id from another builds an address
  // that opens somebody else's show and looks entirely correct doing it.
  const open = (item) => {
    const r = item;
    const kind = kindOf(r);

    if (kind === 'view') {
      navigate({ page: 'high-fashion', filters: (r.view || {}).filters || {} });
      return;
    }

    const id = showIdOf(r.collection);
    if (!id) return;
    navigate({
      page: 'high-fashion',
      collectionId: id,
      // A look opens at its own photograph; a show opens at the top of the
      // run, which is what a saved show is.
      imageNumber: kind === 'look' ? (r.look || {}).number : null,
      // Decoration only — parseRoute never reads it back. See routes.js.
      slug: slugify(
        cleanDesignerName((r.collection || {}).designer || ''),
        (r.season || {}).name
      ),
    });
  };

  const chrome = (
    <TopBar
      currentPage={currentPage}
      onPageSwitch={onPageSwitch}
      currentUser={currentUser}
      onLogout={onLogout}
    />
  );

  const backRow = (
    <div className="alb-back-row">
      <button type="button" className="ar-btn ar-btn-block alb-back" onClick={back}>
        Back to library
      </button>
    </div>
  );

  if (itemsLoading) {
    return (
      <div className="ar-page">
        {chrome}
        <div className="ar-loading">
          <span className="headline">Loading album</span>
        </div>
      </div>
    );
  }

  // An album id that is not yours is a 404, not a 403, so gone and never
  // yours arrive as one answer and there is nothing to tell apart. Both mean
  // there is no album here — and the only thing worth offering is the way
  // out, through the same navigate the Back control uses.
  if (!album) {
    return (
      <div className="ar-page">
        {chrome}
        <div className="ar-empty">
          <span className="headline">No such album</span>
          <span className="alb-empty-hint">
            It was deleted, or it was never yours. The library has the rest.
          </span>
          <button type="button" className="ar-btn alb-back" onClick={back}>
            Back to library
          </button>
        </div>
      </div>
    );
  }

  const selected = ordered.find(row => row.id === selectedId) || null;

  return (
    <div className="ar-page">
      {chrome}

      <div className="ar-content">
        <div className="ar-sidebar">
          <div className="ar-section-header">
            <span>Album</span>
            <span className="count">{ordered.length}</span>
          </div>

          <div className="alb-title">{album.name}</div>
          <div className="ar-segmented alb-layout-toggle" role="group" aria-label="Layout">
            {['grid', 'canvas'].map(mode => (
              <button
                key={mode}
                type="button"
                className={`ar-segment ${(album.layout_mode || 'grid') === mode ? 'selected' : ''}`}
                aria-pressed={(album.layout_mode || 'grid') === mode}
                onClick={() => setAlbumOptions(album.id, { layoutMode: mode })}
              >
                {mode === 'grid' ? 'GRID' : 'FREEFORM'}
              </button>
            ))}
          </div>
          <div className="alb-share">
            <ShareButton onMint={() => ShareEndpoints.mintShare('album', { album_id: album.id })} />
          </div>

          <div className="alb-sort">
            <label className="alb-sort-label" htmlFor="alb-sort-by">Sort by</label>
            <select
              id="alb-sort-by"
              className="ar-select alb-sort-select"
              value={sortBy}
              onChange={(e) => setAlbumOptions(album.id, { sortBy: e.target.value })}
            >
              {SORTS.map(s => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>

          {/* Taking a tile out of this album.

              This is NOT the button that unsaves, and it is written so that
              a reader can tell at a glance which of the two they are about
              to press. It says what it does to the thing it names, it is a
              plain control in the same ink as everything else, and the line
              under it says where the thing goes: nowhere. It carries no
              `ar-btn-danger`, because this design language spends that token
              on one thing only — discarding something irreversibly — and
              putting a tile back is one press of the same picker that put it
              here.

              The library's UNSAVE is the one that gets the colour. It ends
              the favourite, and the cascade on `album_items` takes it out of
              this album and every other one on the way past.

              It names the selected tile rather than sitting on every tile:
              one button on screen at a time, saying which thing it is about,
              is harder to press by accident than a row of small identical
              ones. */}
          <div className="alb-acts">
            <button
              type="button"
              className="ar-btn ar-btn-block alb-remove"
              onClick={() => { if (selected) removeFromAlbum(album.id, selected.id); }}
              disabled={!selected}
              title={selected
                ? `Take ${captionOf(selected).name} out of this album`
                : 'Select a tile to take it out of this album'}
            >
              Remove from album
            </button>
            <span className="alb-acts-note">
              It stays in your library. Unsaving is in the library, and takes
              it out of every album.
            </span>
          </div>

          {backRow}
        </div>

        <div className="alb-main">
          {ordered.length === 0 ? (
            <div className="ar-empty">
              <span className="headline">This album is empty</span>
              <span className="alb-empty-hint">
                Nothing has been put in it yet. Open the library and add a
                saved look, a show or a view — an album holds all three.
              </span>
            </div>
          ) : (
            (album.layout_mode === 'canvas') ? (
              <AlbumCanvas albumId={album.id} items={ordered} onOpen={open} />
            ) : (
            <div className="alb-grid-container ar-scroll">
              <div className="alb-grid">
                {ordered.map(item => (
                  <Tile
                    key={item.id}
                    item={item}
                    selected={item.id === selectedId}
                    onSelect={(row) => setSelectedId(row.id)}
                    onOpen={open}
                  />
                ))}
              </div>
            </div>
            )
          )}

          <div className="ar-status-bar">
            <span>
              {album.name} · {ordered.length}
              {ordered.length === 1 ? ' item' : ' items'}
            </span>
            <span>
              {selected && (
                <span className="active">{captionOf(selected).name}</span>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AlbumGrid;
