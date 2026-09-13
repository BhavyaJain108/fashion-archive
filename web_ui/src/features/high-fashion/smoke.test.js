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
import React, { createRef } from 'react';
import { render, screen } from '@testing-library/react';

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

const FILTERS = {
  gender: 'Women', year: '', season: '', category: '',
  shootType: '', city: '', letter: '',
};

const IMAGES = ['shows/1234/look-01.jpg', 'shows/1234/look-02.jpg'];

const extractLookNumber = (path, idx) => idx + 1;

describe('StatusBar', () => {
  it('renders the look readout for a selected show', () => {
    render(
      <StatusBar
        selectedCollection={COLLECTION}
        filters={FILTERS}
        imagesLength={12}
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
    currentImageIndex: 0,
    setCurrentImageIndex: noop,
    currentLookNumber: 1,
    extractLookNumber,
    selectedCollection: COLLECTION,
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
    expect(screen.getByText('LOOK 01')).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    expect(screen.getByText('SINGLE')).toBeInTheDocument();
    expect(screen.getByText('VIDEO')).toBeInTheDocument();
    // ThumbStrip is rendered by Viewer in single view — this is the seam
    // between the two, and the props crossing it.
    expect(screen.getByAltText('Look 2')).toBeInTheDocument();
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
});
