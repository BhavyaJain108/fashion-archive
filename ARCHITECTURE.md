# Fashion Archive System Architecture

## System Overview

The Fashion Archive System is built with a modular architecture that separates concerns between data acquisition, AI verification, user interface, and content management.

## Core Architecture

```
┌─────────────────────────────────────────────────────┐
│                    User Interface                    │
│               (fashion_scraper.py)                  │
├─────────────────────────────────────────────────────┤
│  Image Gallery  │  Video Player  │  Collection List │
├─────────────────┼────────────────┼─────────────────┤
│                    Control Layer                    │
├─────────────────────────────────────────────────────┤
│  Data Acquisition  │     AI Layer    │  Organization│
│                   │                 │              │
│ image_downloader  │ claude_video_   │ collection_  │
│ fashion_video_    │ verifier        │ organizer    │
│ search            │                 │              │
├─────────────────────────────────────────────────────┤
│                 External APIs                       │
│  nowfashion.com  │  YouTube  │  Claude AI  │ yt-dlp│
└─────────────────────────────────────────────────────┘
```

## Component Details

### User Interface Layer

**File**: `fashion_scraper.py`
- **Purpose**: Main GUI application using tkinter
- **Responsibilities**:
  - Season and collection selection
  - Image gallery with zoom and navigation
  - Video player integration
  - Progress tracking and status updates
  - Error handling and user feedback

**Key Features**:
- Three-column progressive reveal interface
- Responsive image gallery with thumbnails
- Integrated OpenCV-based video player
- Keyboard shortcuts and mouse controls

### Data Acquisition Layer

#### Image Downloading
**File**: `image_downloader.py`
- **Purpose**: High-quality image acquisition and processing
- **Features**:
  - Configurable download parameters
  - Rate limiting and retry logic
  - Image format validation
  - Thumbnail generation
  - Progress tracking

#### Video Search
**File**: `fashion_video_search.py`
- **Purpose**: YouTube video discovery and metadata extraction
- **Approach**:
  - HTML parsing (no API key required)
  - Pattern matching for video data
  - Confidence scoring based on title analysis
  - Multiple search result formats

#### Video Download
**File**: `youtube_downloader.py`
- **Purpose**: Video file acquisition with metadata
- **Features**:
  - yt-dlp integration for robust downloading
  - Original title preservation
  - Quality selection (720p default)
  - Metadata and description extraction

### AI Verification Layer

**File**: `claude_video_verifier.py`
- **Purpose**: Intelligent content verification using Claude AI
- **Key Innovations**:
  - Fashion industry-specific logic
  - Semantic matching beyond keyword search
  - Temporal intelligence (year direction matching)
  - Collection type distinction (Couture vs Haute Couture)

**Verification Process**:
1. **Content Analysis**: Parse search query for designer, year, season, type
2. **Video Evaluation**: Extract metadata from each video result
3. **Semantic Matching**: Use Claude AI to verify relevance
4. **Quality Control**: Reject reviews, reactions, unrelated content
5. **Best Match Selection**: Return highest confidence authentic match

### Organization Layer

**File**: `collection_organizer.py`
- **Purpose**: Intelligent file and folder management
- **Features**:
  - Automatic folder structure creation
  - Collection-based organization
  - Metadata preservation
  - Cleanup and maintenance

## Data Flow Architecture

### Collection Selection Flow
```
User Click → Parse Collection Info → Parallel Processing:
├── Image Download Thread
│   ├── Fetch high-res images
│   ├── Generate thumbnails  
│   └── Update UI gallery
└── Video Download Thread
    ├── Search YouTube
    ├── Claude AI verification
    ├── Download verified video
    └── Enable video player
```

### AI Verification Flow
```
Video Search Results → Claude AI Analysis:
├── Extract: Designer, Year, Season, Type
├── Match Logic:
│   ├── Year Direction: 2018 ≠ 2017-2018 ✗
│   ├── Collection Type: Couture ≠ Haute Couture ✗
│   └── Semantic Context: Runway Show ≠ Interview ✗
├── Confidence Scoring
└── Best Match Selection
```

## Threading Model

The application uses a sophisticated threading model to maintain UI responsiveness:

### Main Thread
- GUI updates and user interaction
- Image display and gallery management
- Video player controls

### Background Threads
- **Image Download Thread**: Downloads and processes images
- **Video Download Thread**: Searches, verifies, and downloads videos
- **Organization Thread**: File management and cleanup

### Thread Communication
- `root.after()` for safe GUI updates from background threads
- Shared state variables with proper synchronization
- Progress callbacks for status updates

## Error Handling Strategy

### Graceful Degradation
- **No Claude API Key**: Disables AI verification, falls back to basic search
- **No OpenCV**: Shows error message, disables video player
- **Network Issues**: Retry logic with exponential backoff
- **Invalid Videos**: Logs error, continues with next result

### User Feedback
- Console logging for detailed progress tracking
- GUI status updates for user awareness
- Error messages with actionable solutions
- Progress indicators for long-running operations

## Security Considerations

### API Security
- Environment variable storage for API keys
- No hardcoded credentials in source code
- Secure HTTPS communications

### Content Safety
- Public domain content only
- No personal data collection
- Respect for robots.txt and rate limiting
- Original source attribution

## Performance Optimizations

### Memory Management
- Lazy loading of images and videos
- Proper resource cleanup (video capture objects)
- Thumbnail caching to reduce memory usage
- Garbage collection of unused objects

### Network Efficiency
- Parallel downloads for images and videos
- Rate limiting to respect server resources
- Connection pooling and keep-alive
- Retry logic with intelligent backoff

### UI Responsiveness
- Background threading for all I/O operations
- Progressive loading and rendering
- Efficient image scaling and display
- Minimal blocking operations in main thread

## Extensibility

### Plugin Architecture
The system is designed for easy extension:
- **New Data Sources**: Add new fashion archive sites
- **Enhanced AI Models**: Integrate additional verification models  
- **Export Formats**: Add new output formats and destinations
- **UI Enhancements**: Extend gallery and player capabilities

### Configuration System
- JSON-based configuration files
- Environment variable overrides
- Runtime parameter adjustment
- User preference persistence

## Future Architecture Considerations

### Scalability
- Database backend for metadata storage
- Caching layer for frequently accessed content
- Microservices architecture for large deployments
- Load balancing for multiple concurrent users

### Integration
- REST API for programmatic access
- Webhook support for external systems
- Export plugins for research databases
- Mobile app companion architecture