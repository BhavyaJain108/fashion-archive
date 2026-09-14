// Smoke renders for the six components extracted out of HighFashionPage.
//
// The rest of this suite is pure functions, which means the wiring between
// the page and these components — every prop name, every handler — has never
// been executed by a test. Rename a prop and 122 tests still pass while the
// app white-screens, because nothing renders a component and there is no
// error boundary to catch it.
//
// These are deliberately shallow: mount with plausible props, assert one
// identifying piece of output. They are here to fail when a prop stops
// connecting, not to describe behaviour. None of the six needs a mock —
// they are all presentational, and the one API call between them
// (getImageUrl) is a pure string builder.
import fs from 'fs';
import path from 'path';
import React, { createRef } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { lookCounter } from '../../shared/lib/lookLabel';

import StatusBar from './StatusBar';
import ThumbStrip from './ThumbStrip';
import VideoPanel from './VideoPanel';
import Filters from './Filters';
import ShowList from './ShowList';
import Viewer from './Viewer';

const noop = () => {};

const COLLECTION = {
  collection_id: '1234',
  url: 'https://example.test/show/1234',
  designer: 'Yohji Yamamoto',
  year: '1999',
  season: 'Fall / Winter',
  gender: 'Women',
  subtitle: 'Runway Collection — Paris',
};

// The show that was open a moment ago and is still on screen while another
// one loads — a different designer and a different season, so a message that
// names the wrong one is visible in the assertion.
const PREVIOUS = {
  collection_id: '5678',
  url: 'https://example.test/show/5678',
  designer: 'Helmut Lang Ready To Wear Spring 1998',
  year: '1998',
  season: 'Spring',
  gender: 'Women',
};

const FILTERS = {
  gender: 'Women', year: '', season: '', category: '',
  shootType: '', city: '', letter: '',
};

const IMAGES = ['shows/1234/look-01.jpg', 'shows/1234/look-02.jpg'];

// A part-loaded show: twelve of the thirty-eight looks its stream said to
// expect. These are the numbers the ghost-slot behaviour is specified in.
const IMAGES_12 = Array.from(
  { length: 12 },
  (_, i) => `shows/1234/look-${String(i + 1).padStart(2, '0')}.jpg`
);

const extractLookNumber = (path, idx) => idx + 1;

describe('StatusBar', () => {
  it('renders the look readout for a selected show', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        filters={FILTERS}
        imagesLength={12}
        expectedCount={12}
        currentLookNumber={3}
      />
    );
    expect(screen.getByText('Yohji Yamamoto')).toBeInTheDocument();
    // Zero-padded, and the count beside it.
    expect(screen.getByText('03')).toBeInTheDocument();
  });

  it('falls back to the filter path when no show is open', () => {
    render(
      <StatusBar
        selectedCollection={null}
        filters={{ ...FILTERS, year: '1999' }}
        imagesLength={0}
        currentLookNumber={1}
      />
    );
    expect(screen.getByText(/Women/)).toBeInTheDocument();
  });

  // The counter is the readout of a show that is still growing, so it counts
  // against the total the stream promised, not against the handful that have
  // landed so far — a total that climbed 12, 13, 14 as photographs arrived
  // would make a reader think the show was short.
  it('counts against the promised total and says the rest is arriving', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={COLLECTION}
        filters={FILTERS}
        imagesLength={12}
        expectedCount={38}
        currentLookNumber={12}
      />
    );
    expect(document.querySelector('.hf2-status-look').textContent)
      .toBe('12 / 38 arriving');
  });

  // The left number is where the reader IS, not how many have landed. It is
  // the one the .active rule blackens, and it only moves when they move.
  it('keeps the left number on the look being read', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={COLLECTION}
        filters={FILTERS}
        imagesLength={12}
        expectedCount={38}
        currentLookNumber={1}
      />
    );
    expect(document.querySelector('.hf2-status-look').textContent)
      .toBe('01 / 38 arriving');
    expect(document.querySelector('.hf2-status-look .active').textContent).toBe('01');
  });

  it('drops the word once every look has landed', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={COLLECTION}
        filters={FILTERS}
        imagesLength={38}
        expectedCount={38}
        currentLookNumber={3}
      />
    );
    // Character for character the shared counter form.
    expect(document.querySelector('.hf2-status-look').textContent)
      .toBe(lookCounter(3, 38));
    expect(screen.queryByText('arriving')).not.toBeInTheDocument();
  });

  // Meta has not arrived, so there is no total to count against. "07 / 0" is
  // worse than nothing.
  it('renders no counter before the stream has said how many', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={null}
        filters={FILTERS}
        imagesLength={0}
        expectedCount={0}
        currentLookNumber={0}
      />
    );
    expect(document.querySelector('.hf2-status-look').textContent).toBe('');
    expect(screen.queryByText(/\/ 0$/)).not.toBeInTheDocument();
  });

  // The bug this task owns. A new show has been asked for and the previous
  // one is still on screen: the name came from the new show, the numbers from
  // the old one, and the bar read "Yohji Yamamoto ... 12 / 38" where 12 was
  // Helmut Lang's. expectedCount is already the NEW show's total here —
  // meta arrives before the first photograph does — which is exactly why it
  // cannot be printed beside the old show's position.
  it('names the show whose looks are on screen, not the one being fetched', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={PREVIOUS}
        filters={FILTERS}
        imagesLength={12}
        expectedCount={38}
        currentLookNumber={12}
        isStale
      />
    );
    expect(screen.getByText('Helmut Lang')).toBeInTheDocument();
    expect(screen.queryByText('Yohji Yamamoto')).not.toBeInTheDocument();
    // And no number from either show beside it: the counter slot says what
    // is happening instead.
    expect(document.querySelector('.hf2-status-look').textContent).toBe('loading');
    expect(screen.queryByText(/38/)).not.toBeInTheDocument();
  });

  // Nothing has ever been on screen, so there is no other show to name and
  // naming the one being fetched is honest — there are no numbers beside it.
  it('names the show being fetched when nothing is on screen yet', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={null}
        filters={FILTERS}
        imagesLength={0}
        expectedCount={0}
        currentLookNumber={0}
        isStale
      />
    );
    expect(screen.getByText('Yohji Yamamoto')).toBeInTheDocument();
    expect(document.querySelector('.hf2-status-look').textContent).toBe('loading');
  });

  // The defect: a look's download can fail and the stream still finishes
  // normally, having sent fewer images than it promised. Without a
  // completion signal the bar said "12 / 38 arriving" forever, on a stream
  // that ended minutes ago. Once `streamComplete` is true the denominator is
  // the real, delivered count — not the promise the stream could not keep —
  // and the word "arriving" is gone, because nothing is.
  it('once the stream is complete, counts against what actually arrived', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={COLLECTION}
        filters={FILTERS}
        imagesLength={12}
        expectedCount={38}
        currentLookNumber={12}
        streamComplete
      />
    );
    expect(document.querySelector('.hf2-status-look').textContent).toBe('12 / 12');
    expect(screen.queryByText('arriving')).not.toBeInTheDocument();
  });

  // The existing behaviour a stream mid-flight relies on, pinned explicitly
  // against the new prop: with no completion signal yet, the total is still
  // the promised one and the rest is still "arriving".
  it('mid-flight, with no completion signal, still counts against the promised total', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        imagesCollection={COLLECTION}
        filters={FILTERS}
        imagesLength={12}
        expectedCount={38}
        currentLookNumber={12}
        streamComplete={false}
      />
    );
    expect(document.querySelector('.hf2-status-look').textContent)
      .toBe('12 / 38 arriving');
  });
});

describe('ThumbStrip', () => {
  it('renders one thumbnail per image', () => {
    render(
      <ThumbStrip
        images={IMAGES}
        currentImageIndex={0}
        onSelect={noop}
        isFavourite={() => false}
        stripRef={createRef()}
        activeThumbRef={createRef()}
        extractLookNumber={extractLookNumber}
      />
    );
    expect(screen.getAllByRole('img')).toHaveLength(IMAGES.length);
    expect(screen.getByAltText('Look 1')).toBeInTheDocument();
  });

  const stripProps = {
    currentImageIndex: 0,
    onSelect: noop,
    isFavourite: () => false,
    stripRef: createRef(),
    activeThumbRef: createRef(),
    extractLookNumber,
  };
  const slots = () => document.querySelectorAll('.hf2-thumb');
  const ghosts = () => document.querySelectorAll('.hf2-thumb-ghost');

  it('draws a slot for every look the stream promised', () => {
    render(<ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={38} />);
    // Full width from the first photograph: 38 boxes, 12 of them filled.
    expect(slots()).toHaveLength(38);
    expect(ghosts()).toHaveLength(26);
    expect(screen.getAllByRole('img')).toHaveLength(12);
    // And the empty ones are at the end, where the looks that have not
    // arrived belong.
    expect(Array.from(slots()).slice(0, 12).filter(
      (el) => el.classList.contains('hf2-thumb-ghost')
    )).toHaveLength(0);
  });

  // Step 2: a ghost is the same box as a thumb, or every photograph that
  // lands nudges the strip sideways and fights the centring effect. It is the
  // same box because it wears the same class — there is no second copy of
  // 44x60 to drift.
  it('gives a ghost the thumb box by wearing the thumb class', () => {
    render(<ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={38} />);
    ghosts().forEach((ghost) => {
      expect(ghost.classList.contains('hf2-thumb')).toBe(true);
      expect(ghost.getAttribute('style')).toBeNull();
    });
  });

  // jsdom applies no stylesheet, so the sizing itself cannot be measured
  // here. What can be pinned is the thing that would break it: a width or a
  // height of its own in the ghost's rule, which is how the two boxes would
  // drift apart.
  it('sets no dimensions of its own in the stylesheet', () => {
    const css = fs.readFileSync(path.join(__dirname, 'HighFashionPage.css'), 'utf8');
    expect(css).toContain('.hf2-thumb-ghost {');
    const rule = css.slice(css.indexOf('.hf2-thumb-ghost {'));
    const body = rule.slice(0, rule.indexOf('}'));
    expect(body).not.toMatch(/width|height|padding|margin|flex/);
    // And the box it shares is declared once, on .hf2-thumb.
    expect(css).toMatch(/\.hf2-thumb \{[^}]*width: 44px;[^}]*height: 60px;/);
  });

  it('leaves a ghost inert and out of the way', () => {
    const onSelect = jest.fn();
    render(
      <ThumbStrip {...stripProps} onSelect={onSelect} images={IMAGES_12} expectedCount={38} />
    );
    ghosts().forEach((ghost) => {
      expect(ghost.getAttribute('aria-hidden')).toBe('true');
      // Not in the tab order, and nothing inside it to reach either.
      expect(ghost.tabIndex).toBe(-1);
      expect(ghost.hasAttribute('tabindex')).toBe(false);
      expect(ghost.querySelector('img')).toBeNull();
    });
    fireEvent.click(ghosts()[0]);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('draws no ghosts once every look has landed', () => {
    render(<ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={12} />);
    expect(slots()).toHaveLength(12);
    expect(ghosts()).toHaveLength(0);
  });

  it('draws no ghosts before the stream has said how many', () => {
    render(<ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={0} />);
    expect(slots()).toHaveLength(12);
    expect(ghosts()).toHaveLength(0);
  });

  // The trap. A new show has been asked for, so expectedCount is already its
  // 38, while `images` is still the previous show's 12 photographs. The
  // difference is not 26 missing looks of anything — it is two different
  // shows subtracted from each other. Clamping the arithmetic would hide the
  // negative and still stand 26 empty slots of the new show behind the old
  // show's thumbnails; the answer is to draw none until the new show's own
  // first photograph lands.
  it('draws no ghosts while the previous show is still on screen', () => {
    render(<ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={38} isStale />);
    expect(slots()).toHaveLength(12);
    expect(ghosts()).toHaveLength(0);
  });

  // The other half of the stale window, before the new show's meta has
  // landed: expectedCount is 0 and the subtraction is negative.
  it('draws no ghosts when the promised total is behind the strip', () => {
    render(<ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={0} isStale />);
    expect(slots()).toHaveLength(12);
    expect(ghosts()).toHaveLength(0);
  });

  // The defect: a look that failed to download is never coming, but a
  // ghost slot for it pulsed forever because nothing distinguished "still
  // arriving" from "finished, and this is all there is". Once the stream
  // has said it is complete, the strip shows exactly the images that
  // arrived — no ghost stands in for a look that will not land.
  it('draws no ghosts once the stream is complete, however many actually arrived', () => {
    render(<ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={38} streamComplete />);
    expect(slots()).toHaveLength(12);
    expect(ghosts()).toHaveLength(0);
    expect(screen.getAllByRole('img')).toHaveLength(12);
  });

  // The existing behaviour a stream mid-flight relies on, pinned explicitly
  // against the new prop: with no completion signal yet, the promised
  // looks that have not arrived are still drawn as ghosts.
  it('still draws ghosts mid-flight, with no completion signal', () => {
    render(
      <ThumbStrip {...stripProps} images={IMAGES_12} expectedCount={38} streamComplete={false} />
    );
    expect(slots()).toHaveLength(38);
    expect(ghosts()).toHaveLength(26);
  });
});

describe('VideoPanel', () => {
  it('renders the transport controls', () => {
    render(
      <VideoPanel
        videoHeight={320}
        isPlaying={false}
        currentTime={30}
        duration={120}
        playerContainerRef={createRef()}
        onResizeStart={noop}
        onTogglePlay={noop}
        onSeek={noop}
        formatTime={(s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`}
        getQualityLabel={() => '1080p'}
      />
    );
    expect(screen.getByText('▶')).toBeInTheDocument();
    expect(screen.getByText('0:30 / 2:00')).toBeInTheDocument();
    expect(screen.getByText('1080p')).toBeInTheDocument();
  });
});

describe('Filters', () => {
  const props = {
    searchInputRef: createRef(),
    designerIndex: {},
    query: '',
    setQuery: noop,
    searchFocused: false,
    setSearchFocused: noop,
    handleSearchKeyDown: noop,
    suggestionList: [],
    activeSuggestion: 0,
    setActiveSuggestion: noop,
    chooseSuggestion: noop,
    indexReady: true,
    designerMode: null,
    filters: FILTERS,
    setFilter: noop,
    years: ['1999', '2000'],
    designerYears: null,
    seasonsAvailable: ['Fall / Winter'],
    designerSeasons: null,
    categoriesAvailable: ['Ready-to-Wear'],
    designerCategories: null,
    designerShootTypes: null,
    facetValues: () => ['Paris'],
    facetCount: () => 0,
    clearFilters: noop,
    activeFilterCount: 0,
  };

  it('renders the search box and the facet rows', () => {
    render(<Filters {...props} />);
    expect(screen.getByPlaceholderText('Search designers and shows')).toBeInTheDocument();
    expect(screen.getByText('Year')).toBeInTheDocument();
    expect(screen.getByText('City')).toBeInTheDocument();
    // The clear button's label is driven by activeFilterCount.
    expect(screen.getByText('Whole archive')).toBeInTheDocument();
  });

  it('counts filters into the clear button label', () => {
    render(<Filters {...props} activeFilterCount={2} />);
    expect(screen.getByText('Clear 2 filters')).toBeInTheDocument();
  });
});

describe('ShowList', () => {
  const props = {
    designerMode: null,
    searchText: '',
    exitDesigner: noop,
    visibleCollections: [COLLECTION],
    indexReady: true,
    cursor: { total: 4210, hasMore: false, nextPage: null },
    designerRows: [],
    handleListScroll: noop,
    listLoading: false,
    listError: null,
    selectedCollection: null,
    handleCollectionSelect: noop,
    designerLoading: false,
    loadingMore: false,
  };

  it('renders a row per collection under the header', () => {
    render(<ShowList {...props} />);
    expect(screen.getByText('Shows')).toBeInTheDocument();
    expect(screen.getByText('Yohji Yamamoto')).toBeInTheDocument();
    expect(screen.getByText('4,210')).toBeInTheDocument();
  });

  it('renders the empty state when nothing matches', () => {
    render(<ShowList {...props} visibleCollections={[]} />);
    expect(screen.getByText('No shows match these filters')).toBeInTheDocument();
  });
});

describe('Viewer', () => {
  const props = {
    images: IMAGES,
    imagesLoading: false,
    imagesStale: false,
    imagesError: null,
    currentImageIndex: 0,
    setCurrentImageIndex: noop,
    currentLookNumber: 1,
    extractLookNumber,
    selectedCollection: COLLECTION,
    imagesCollection: COLLECTION,
    viewMode: 'single',
    setViewMode: noop,
    selectImageFromGrid: noop,
    isFavourite: () => false,
    toggleFavourite: noop,
    thumbStripRef: createRef(),
    activeThumbRef: createRef(),
    showVideo: false,
    setShowVideo: noop,
    videoData: null,
    videoState: 'idle',
    setVideoState: noop,
    videoError: null,
    setVideoError: noop,
    handleVideoSearch: noop,
    videoHeight: 320,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    playerContainerRef: createRef(),
    handleResizeStart: noop,
    togglePlay: noop,
    seekTo: noop,
    formatTime: () => '0:00',
    getQualityLabel: () => '1080p',
  };

  it('renders the single view with its controls and thumb strip', () => {
    render(<Viewer {...props} />);
    // One number under the photograph, and it is the position: 1 of 2,
    // which the reader can check against the two thumbnails below it. In
    // the same spelling the status bar uses, from the same function.
    expect(document.querySelector('.hf2-look-count').textContent)
      .toBe(lookCounter(1, 2));
    expect(screen.getByText('SINGLE')).toBeInTheDocument();
    expect(screen.getByText('VIDEO')).toBeInTheDocument();
    // ThumbStrip is rendered by Viewer in single view — this is the seam
    // between the two, and the props crossing it.
    expect(screen.getByAltText('Look 2')).toBeInTheDocument();
  });

  // The defect this replaced: `lookLabel(currentLookNumber)` and an inline
  // `{currentImageIndex + 1} / {images.length}` in the same row — two
  // different numbers about the same photograph, adjacent, both bare, one
  // zero-padded and one not. The word "LOOK" had been carrying the
  // disambiguation. There is one number in this row now.
  it('shows the position and no second bare number beside it', () => {
    // A show where the two differ: the filename says look 34, and it is the
    // second of two photographs on screen.
    render(
      <Viewer
        {...props}
        images={['shows/1234/look-33.jpg', 'shows/1234/look-34.jpg']}
        currentImageIndex={1}
        currentLookNumber={34}
      />
    );
    const row = document.querySelector('.hf2-image-info');
    expect(row.textContent).toContain(lookCounter(2, 2));
    expect(row.textContent).not.toContain('34');
  });

  it('renders the grid view', () => {
    render(<Viewer {...props} viewMode="grid" />);
    expect(screen.getByText('GRID')).toBeInTheDocument();
    expect(screen.getAllByRole('img')).toHaveLength(IMAGES.length);
  });

  it('renders the placeholder with no images', () => {
    render(<Viewer {...props} images={[]} />);
    expect(screen.getByText('No images found')).toBeInTheDocument();
  });

  // The prop contract useCollectionImages changed: a stream in flight no
  // longer means an empty pane. `imagesLoading` only reaches the placeholder
  // when there is nothing else to draw.
  it('keeps the previous looks on screen while the next show loads', () => {
    render(<Viewer {...props} imagesLoading imagesStale />);
    expect(screen.queryByText('Loading images...')).not.toBeInTheDocument();
    // Both the frame and the strip draw look 1, which is the point: the
    // whole viewer is still there.
    expect(screen.getAllByAltText('Look 1')).toHaveLength(2);
    expect(document.querySelector('.hf2-look-count').textContent)
      .toBe(lookCounter(1, 2));
    // Marked as not-what-you-asked-for-yet, not removed.
    expect(document.querySelector('.hf2-main.stale')).not.toBeNull();
  });

  it('loads into an empty pane on the first show of a session', () => {
    render(<Viewer {...props} images={[]} imagesLoading imagesStale />);
    expect(screen.getByText('Loading images...')).toBeInTheDocument();
  });

  it('says so when the stream failed and left nothing', () => {
    render(<Viewer {...props} images={[]} imagesError={new Error('nope')} />);
    expect(screen.getByText('Could not load this show')).toBeInTheDocument();
  });

  // The case the kept-previous-show feature creates, and the one that used
  // to report nothing at all: the request failed, so the pane still holds
  // the show that was open before, dimmed. Without a message the dim is
  // indistinguishable from "still loading", and it never clears.
  it('says so when the stream failed and the previous show is still up', () => {
    render(
      <Viewer
        {...props}
        imagesStale
        imagesError={new Error('nope')}
        selectedCollection={COLLECTION}
        imagesCollection={PREVIOUS}
      />
    );
    expect(screen.getByText('Could not load this show')).toBeInTheDocument();
    // The status bar is naming COLLECTION, the show that was asked for, so
    // the message has to name the one the reader is actually looking at.
    expect(screen.getByText('Helmut Lang / Spring 1998')).toBeInTheDocument();
    // And the looks are still there, under it.
    expect(screen.getAllByAltText('Look 1')).toHaveLength(2);
  });

  it('leaves the failure notice at full strength over the dimmed looks', () => {
    render(
      <Viewer
        {...props}
        imagesStale
        imagesError={new Error('nope')}
        imagesCollection={PREVIOUS}
      />
    );
    // The dim is applied to the pane's children rather than to the pane, so
    // that the notice — a child — can sit above it undimmed. A child of an
    // element with opacity can never be more opaque than its parent.
    const notice = document.querySelector('.hf2-stale-error');
    expect(notice).not.toBeNull();
    expect(notice.parentElement.classList.contains('hf2-main')).toBe(true);
  });

  it('shows no failure notice when nothing failed', () => {
    render(<Viewer {...props} imagesStale />);
    expect(document.querySelector('.hf2-stale-error')).toBeNull();
  });
});
