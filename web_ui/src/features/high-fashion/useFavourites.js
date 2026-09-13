import { useCallback, useEffect, useState } from 'react';
import { FashionArchiveAPI } from '../../shared/api';
import { videoSeasonName } from './seasonName';

// Which looks this user has kept, and the one way to change that.
//
//   useFavourites(shownCollection, lookTotal)
//     -> { isFavourite, toggleFavourite }
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

// Held as a set of "collection url|look number", loaded once, because the
// question is asked of every thumbnail on screen — a request per look to
// answer "is this one favourited" would be hundreds of requests to draw a
// strip. Favourites are per user by construction: the endpoint reads the
// session, so there is no user id to pass and no way to see anyone else's.
const favouriteKey = (collectionUrl, lookNumber) => `${collectionUrl}|${lookNumber}`;

export function useFavourites(shownCollection, lookTotal) {
  const [favouriteKeys, setFavouriteKeys] = useState(() => new Set());
  const [favouriteBusy, setFavouriteBusy] = useState(false);

  const loadFavourites = useCallback(async () => {
    const rows = await FashionArchiveAPI.getFavourites();
    // The list endpoint nests these — collection.url and look.number, not the
    // flat column names the write side takes. Reading the flat names produced
    // "undefined|undefined" for every key, so nothing was ever marked as kept
    // after a reload while the writes themselves looked fine.
    setFavouriteKeys(new Set(
      (rows || [])
        .map(f => favouriteKey(f.collection?.url, f.look?.number))
        .filter(k => !k.startsWith('undefined'))));
  }, []);

  useEffect(() => { loadFavourites(); }, [loadFavourites]);

  const isFavourite = useCallback((lookNumber) =>
    !!shownCollection
    && favouriteKeys.has(favouriteKey(shownCollection.url, lookNumber)),
  [shownCollection, favouriteKeys]);

  const toggleFavourite = useCallback(async (lookNumber, imagePath) => {
    // `shown` is read once, here, and every field below comes off it.
    // removeFavourite(seasonUrl, collectionUrl, lookNumber) is positional
    // and two of the three are urls: a triple assembled out of two
    // collections names a row that exists, deletes it, and returns success.
    // Nothing in this function may reach for a collection by any other
    // name.
    const shown = shownCollection;
    if (!shown || favouriteBusy) return;

    const key = favouriteKey(shown.url, lookNumber);
    const had = favouriteKeys.has(key);

    // Move the marker first: keeping a look should feel instantaneous, and
    // the request is undone below if it turns out not to have worked.
    setFavouriteKeys(prev => {
      const next = new Set(prev);
      if (had) next.delete(key); else next.add(key);
      return next;
    });
    setFavouriteBusy(true);

    try {
      if (had) {
        await FashionArchiveAPI.removeFavourite(
          shown.season_url || '', shown.url, lookNumber);
      } else {
        await FashionArchiveAPI.addFavourite(
          {
            name: videoSeasonName(shown),
            url: shown.season_url || '',
            link_text: shown.subtitle || '',
          },
          {
            designer: shown.designer_name || shown.designer,
            url: shown.url,
          },
          { number: lookNumber, total: lookTotal },
          imagePath,
        );
      }
    } catch (error) {
      console.error('Could not change favourite:', error);
      setFavouriteKeys(prev => {          // put it back the way it was
        const next = new Set(prev);
        if (had) next.add(key); else next.delete(key);
        return next;
      });
    } finally {
      setFavouriteBusy(false);
    }
  }, [shownCollection, favouriteKeys, favouriteBusy, lookTotal]);

  return { isFavourite, toggleFavourite };
}

export default useFavourites;
