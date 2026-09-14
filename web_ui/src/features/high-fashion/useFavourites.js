import { useCallback } from 'react';
import { useSaves } from '../../shared/hooks/useSaves';
import { videoSeasonName } from './seasonName';

// Which looks this user has kept, and the one way to change that.
//
//   useFavourites(shownCollection, lookTotal)
//     -> { isFavourite, toggleFavourite }
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

export function useFavourites(shownCollection, lookTotal) {
  const { isSaved, toggle } = useSaves();

  const isFavourite = useCallback((lookNumber) => {
    const target = lookTarget(shownCollection, lookNumber, lookTotal);
    return !!target && isSaved(target);
  }, [shownCollection, lookTotal, isSaved]);

  const toggleFavourite = useCallback(async (lookNumber, imagePath) => {
    const target = lookTarget(shownCollection, lookNumber, lookTotal, imagePath);
    if (!target) return;
    await toggle(target);
  }, [shownCollection, lookTotal, toggle]);

  return { isFavourite, toggleFavourite };
}

export default useFavourites;
