import { renderHook, act, waitFor } from '@testing-library/react';
import { FashionArchiveAPI } from '../../shared/api';
import { useFavourites } from './useFavourites';

// Two shows, each fully described, because the bug this hook was extracted
// to kill was a favourite written out of two of them at once: the look
// number off the photographs on screen and the urls off the show that had
// just been clicked. removeFavourite takes (seasonUrl, collectionUrl,
// lookNumber) positionally and deletes whatever that triple names, so a
// mixed triple deletes a different row from the account and reports success.
const GUCCI = {
  url: 'https://example.test/show/gucci-ss99',
  season_url: 'https://example.test/season/spring-1999',
  designer_name: 'Gucci',
  designer: 'Gucci Ready To Wear Spring 1999',
  subtitle: 'Runway Collection — Milan',
  season: 'Spring',
  year: '1999',
};

const PRADA = {
  url: 'https://example.test/show/prada-fw01',
  season_url: 'https://example.test/season/fall-2001',
  designer_name: 'Prada',
  designer: 'Prada Ready To Wear Fall 2001',
  subtitle: 'Runway Collection — Milan',
  season: 'Fall',
  year: '2001',
};

// A row as GET /api/favourites returns one: nested, and carrying the season
// url as well as the collection's, because a look is keyed on
// (season, collection, number) — the server's unique index — and a fixture
// that left the season out would let a key that ignores it pass.
const kept = (collection, number) => ({
  kind: 'look',
  season: { url: collection.season_url },
  collection: { url: collection.url },
  look: { number },
});

let getFavourites;
let addFavourite;
let removeFavourite;
let errorLog;

beforeEach(() => {
  getFavourites = jest.spyOn(FashionArchiveAPI, 'getFavourites').mockResolvedValue([]);
  addFavourite = jest.spyOn(FashionArchiveAPI, 'addFavourite').mockResolvedValue({});
  removeFavourite = jest.spyOn(FashionArchiveAPI, 'removeFavourite').mockResolvedValue({});
  errorLog = jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
});

// The hook is given the collection whose photographs are ON SCREEN — never
// the one that was requested. Mounting it is therefore mounting it against
// one show at a time, and swapping shows is a rerender.
function mount(collection, lookTotal = 40) {
  return renderHook(
    ({ c, t }) => useFavourites(c, t),
    { initialProps: { c: collection, t: lookTotal } },
  );
}

const settled = async (result) => {
  await waitFor(() => expect(getFavourites).toHaveBeenCalled());
  return result;
};

describe('useFavourites', () => {
  test('marks the looks this user has already kept', async () => {
    getFavourites.mockResolvedValue([kept(GUCCI, 3), kept(PRADA, 12)]);
    const { result } = mount(GUCCI);
    await settled(result);

    await waitFor(() => expect(result.current.isFavourite(3)).toBe(true));
    expect(result.current.isFavourite(4)).toBe(false);
  });

  // The heart of it. The look number comes from the photographs on screen;
  // if the key's other half came from anywhere else, every star, title,
  // aria-pressed and kept class would be answering for a different show.
  test('answers for the show on screen, not for any other', async () => {
    getFavourites.mockResolvedValue([kept(GUCCI, 3)]);
    const { result, rerender } = mount(PRADA);
    await settled(result);

    // Look 3 is kept — of Gucci. Prada's look 3 is not.
    expect(result.current.isFavourite(3)).toBe(false);

    rerender({ c: GUCCI, t: 40 });
    expect(result.current.isFavourite(3)).toBe(true);
  });

  // The season url is the third part of a look's key and the first argument
  // of the positional delete. A row filed under another season is another
  // row, and the star must not claim it.
  test('a look kept under another season is not this look', async () => {
    getFavourites.mockResolvedValue([
      { ...kept(PRADA, 7), season: { url: GUCCI.season_url } },
    ]);
    const { result } = mount(PRADA, 27);
    await settled(result);
    expect(result.current.isFavourite(7)).toBe(false);
  });

  test('nothing is kept when there is nothing on screen', async () => {
    getFavourites.mockResolvedValue([kept(GUCCI, 3)]);
    const { result } = mount(null);
    await settled(result);
    expect(result.current.isFavourite(3)).toBe(false);

    await act(async () => { await result.current.toggleFavourite(3, 'gucci/look-03.jpg'); });
    expect(addFavourite).not.toHaveBeenCalled();
    expect(removeFavourite).not.toHaveBeenCalled();
  });

  test('keeping a look writes every field off the show on screen', async () => {
    const { result } = mount(PRADA, 27);
    await settled(result);

    await act(async () => { await result.current.toggleFavourite(7, 'prada/look-07.jpg'); });

    expect(addFavourite).toHaveBeenCalledTimes(1);
    const [season, collection, look, imagePath] = addFavourite.mock.calls[0];
    expect(season).toEqual({
      name: 'Fall 2001',
      url: PRADA.season_url,
      link_text: PRADA.subtitle,
    });
    expect(collection).toEqual({ designer: 'Prada', url: PRADA.url });
    expect(look).toEqual({ number: 7, total: 27 });
    expect(imagePath).toBe('prada/look-07.jpg');
    expect(result.current.isFavourite(7)).toBe(true);
  });

  // removeFavourite(seasonUrl, collectionUrl, lookNumber) is positional and
  // two of the three are urls. This pins that all three come off the same
  // object — the show on screen — and never a mix.
  test('dropping a look sends all three arguments off the same show', async () => {
    getFavourites.mockResolvedValue([kept(PRADA, 7)]);
    const { result } = mount(PRADA, 27);
    await settled(result);
    await waitFor(() => expect(result.current.isFavourite(7)).toBe(true));

    await act(async () => { await result.current.toggleFavourite(7, 'prada/look-07.jpg'); });

    expect(removeFavourite).toHaveBeenCalledTimes(1);
    expect(removeFavourite).toHaveBeenCalledWith(PRADA.season_url, PRADA.url, 7);
    // Named explicitly: the other show's season url in slot one would
    // delete a Gucci favourite and report success.
    expect(removeFavourite.mock.calls[0][0]).not.toBe(GUCCI.season_url);
    expect(removeFavourite.mock.calls[0][1]).not.toBe(GUCCI.url);
    expect(result.current.isFavourite(7)).toBe(false);
  });

  test('a show with no season url sends an empty string, not undefined', async () => {
    const { season_url: _drop, ...noSeason } = PRADA;
    const { result } = mount(noSeason, 27);
    await settled(result);

    await act(async () => { await result.current.toggleFavourite(7, 'prada/look-07.jpg'); });
    expect(addFavourite.mock.calls[0][0].url).toBe('');
  });

  test('a write that fails puts the star back', async () => {
    addFavourite.mockRejectedValue(new Error('nope'));
    const { result } = mount(PRADA, 27);
    await settled(result);

    await act(async () => { await result.current.toggleFavourite(7, 'prada/look-07.jpg'); });

    expect(result.current.isFavourite(7)).toBe(false);
    expect(errorLog).toHaveBeenCalled();
  });

  // The optimistic marker is what makes a double press dangerous: the
  // second press reads the marker the first one moved and would send the
  // opposite write against a row the server has not heard about yet.
  test('one write at a time', async () => {
    addFavourite.mockImplementation(() => new Promise(() => {}));   // never settles
    const { result } = mount(PRADA, 27);
    await settled(result);

    await act(async () => { result.current.toggleFavourite(7, 'prada/look-07.jpg'); });
    await act(async () => { result.current.toggleFavourite(8, 'prada/look-08.jpg'); });

    expect(addFavourite).toHaveBeenCalledTimes(1);
    expect(removeFavourite).not.toHaveBeenCalled();
  });
});
