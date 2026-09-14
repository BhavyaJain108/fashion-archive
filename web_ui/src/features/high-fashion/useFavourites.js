import { useCallback, useMemo } from 'react';
import { useSaves } from '../../shared/hooks/useSaves';
import { videoSeasonName } from './seasonName';

// What this user has kept on this page, and the one way to change it.
//
//   useFavourites(shownCollection, lookTotal)
//     -> { isFavourite, toggleFavourite,        // a look, on screen
//          isShowSaved, toggleShowSave,         // a whole show, any row
//          isViewSaved, toggleViewSave,         // the current filters
//          savesError, reloadSaves }            // why the stars are dark
//
// One hook, because one useSaves() is one store: called twice it would fetch
// the list twice and hold two copies of it, and the star on a row and the
// star on a look would be answering out of different lists.
//
// The store and the writing are useSaves' now, which knows about looks, shows
// and views and nothing about this page. What is left here is the one thing
// only this page knows: which show the reader is actually looking at, and how
// to describe it.
//
// `shownCollection` is the collection whose photographs are ON SCREEN —
// useCollectionImages.imagesCollection — and not the one that was clicked.
// The two are the same almost always and differ exactly when it matters:
// from the click on a new show until its first image lands, the pane still
// holds the previous show, and on a failed load it holds it indefinitely.
// A star is a statement about the photograph the reader is looking at, so
// the look number and the collection it is filed under must come from the
// same place. Keying on the requested show while numbering from the shown
// one is how look 34 of Gucci gets filed under Prada.
//
// This was three states and two closures inside HighFashionPage, where the
// mismatch was invisible and untestable. Out here the contract is one
// sentence: everything is read off the one collection you pass in.

// The show on screen, written the way a save is keyed and stored. One
// expression, off one object: removeFavourite(seasonUrl, collectionUrl,
// lookNumber) is positional and two of the three are urls, so a target
// assembled out of two collections names a row that exists, deletes it, and
// returns success.
export function lookTarget(shown, lookNumber, lookTotal, imagePath) {
  if (!shown) return null;
  return {
    kind: 'look',
    season: {
      name: videoSeasonName(shown),
      url: shown.season_url || '',
      link_text: shown.subtitle || '',
    },
    collection: {
      designer: shown.designer_name || shown.designer,
      url: shown.url,
    },
    look: { number: lookNumber, total: lookTotal },
    imagePath,
  };
}

// A whole show, written the same way — season and collection, no look
// number. Same expression, off one row of the list, and deliberately NOT
// lookTarget with the number left out: the two are different rows in the
// table and a saved show must not light its looks.
//
// This one takes the row that was clicked rather than the show on screen,
// and that is not the same rule as above by accident. A star on a row is a
// statement about THAT row — the reader can see which one they pressed —
// whereas a star in the viewer is a statement about the photograph in front
// of them, which during the stale window belongs to the previous show.
export function showTarget(row) {
  if (!row || !row.url) return null;
  return {
    kind: 'show',
    season: {
      name: videoSeasonName(row),
      url: row.season_url || '',
      link_text: row.subtitle || '',
    },
    collection: {
      designer: row.designer_name || row.designer,
      url: row.url,
    },
  };
}

export function useFavourites(shownCollection, lookTotal) {
  const {
    isSaved, setSaved, toggle, onUnsaved,
    error: savesError, reload: reloadSaves,
  } = useSaves();

  const isFavourite = useCallback((lookNumber) => {
    const target = lookTarget(shownCollection, lookNumber, lookTotal);
    return !!target && isSaved(target);
  }, [shownCollection, lookTotal, isSaved]);

  const toggleFavourite = useCallback(async (lookNumber, imagePath) => {
    const target = lookTarget(shownCollection, lookNumber, lookTotal, imagePath);
    if (!target) return;
    await toggle(target);
  }, [shownCollection, lookTotal, toggle]);

  const isShowSaved = useCallback((row) => {
    const target = showTarget(row);
    return !!target && isSaved(target);
  }, [isSaved]);

  const toggleShowSave = useCallback(async (row) => {
    const target = showTarget(row);
    if (!target) return;
    await toggle(target);
  }, [toggle]);

  // A view IS its filters; useSaves does the normalising, so what is handed
  // over here is whatever the page currently has set.
  const isViewSaved = useCallback((filters) => isSaved({ kind: 'view', filters }),
    [isSaved]);

  const toggleViewSave = useCallback(async (filters, name) => {
    await toggle({ kind: 'view', filters, name });
  }, [toggle]);

  // What the reader is looking at, as a target, for anything on this page
  // that is NOT the star — putting it in an album, to begin with.
  //
  // These exist so there is one answer to "which show is this about". The
  // star's answer is the show whose photographs are on screen, worked out
  // above; a second caller building its own target out of
  // `selectedCollection` would file the look the reader is looking at under
  // the show they have just clicked, which is the phase-2 data-corruption bug
  // with a different button on it.
  const lookOnScreen = useCallback(
    (lookNumber, imagePath) => lookTarget(shownCollection, lookNumber, lookTotal, imagePath),
    [shownCollection, lookTotal]);

  const showOnScreen = useCallback(() => showTarget(shownCollection), [shownCollection]);

  // The collaborator `useAlbums` takes, and the reason it takes one.
  //
  // Adding an unsaved thing to an album saves it inside the album endpoint's
  // own transaction, so the star has to light without a second request. It
  // lights by asking the owner of the saved list to move one marker — this
  // pair — rather than by `useAlbums` keeping a list of its own, because two
  // owners of that list is how a star ends up lit for a row nobody saved.
  //
  // `onUnsaved` is the other direction over the same seam. Pressing the star
  // a second time deletes the favourite, and `album_items` is ON DELETE
  // CASCADE on it — so the server empties the look out of every album it was
  // in and tells nobody. Without this the shelf goes on showing the count it
  // had before the press, and the next add counts up from that stale number,
  // so an album holding one reads as two until the page is remounted.
  //
  // One object, memoised, so a page writing `useAlbums(null, { saves })`
  // hands over the same reference on every render.
  const saves = useMemo(
    () => ({ isSaved, setSaved, onUnsaved }), [isSaved, setSaved, onUnsaved]);

  return {
    isFavourite, toggleFavourite,
    isShowSaved, toggleShowSave,
    isViewSaved, toggleViewSave,
    lookOnScreen, showOnScreen,
    saves,
    // Why every star on the page is dark, when it is dark for a reason that
    // is not "you have kept nothing".
    //
    // `useSaves` refuses to write while the keys have not loaded, which stops
    // the second press of a dark star from deleting a save — but a control
    // that does nothing and says nothing is its own bug. The page renders this
    // where the stars are, and `reloadSaves` is the way out of it.
    savesError, reloadSaves,
  };
}

export default useFavourites;
