# Fashion Archive System 🎭

An intelligent fashion show archiving system with AI-powered video verification and modern web interface.

## Features

### 🎬 AI-Powered Video Search & Verification
- **Google Video Search**: Finds fashion shows across YouTube and video platforms
- **Claude AI Verification**: 5-attempt verification system with strict matching rules
- **Industry Logic**: Distinguishes RTW vs Couture, handles fashion year ranges (2014 vs 2013/14)
- **Source Filtering**: Rejects Style.com, Elle, and other clip-only sources

### 🖼️ High-Quality Image Downloads
- **Batch Processing**: Downloads all runway images from collections
- **Smart Organization**: Auto-creates folders by designer/season/year
- **Progress Tracking**: Real-time download progress with image previews

### 🌐 Modern Web Interface
- **React Frontend**: Clean, responsive web UI
- **Flask Backend**: RESTful API bridging React to Python functionality
- **Real-time Updates**: Live progress tracking and status updates
- **Image Gallery**: Grid view with zoom and navigation

### 🗂️ Intelligent Organization
- **Auto-Detection**: Parses designer, season, year, and city from collection names
- **Clean Structure**: Organizes downloads into logical folder hierarchies
- **Metadata Preservation**: Keeps original titles and source information

## Installation

### Prerequisites
- Python 3.8+
- Node.js 16+ (for web UI)
- Claude AI API key

### Backend Setup
```bash
git clone https://github.com/BhavyaJain108/fashion-archive.git
cd fashion-archive

# Python environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r web_ui_requirements.txt

# Environment configuration
echo "CLAUDE_API_KEY=your_api_key_here" > .env
```

### Frontend Setup
```bash
cd web_ui
npm install
npm run build
```

### Quick Start
```bash
# Terminal 1: Start backend
python backend_server.py

# Terminal 2: Start frontend (development)
cd web_ui && npm start

# Or use the convenience script
./run_modern_ui.sh
```

Access the application at `http://localhost:3000`

## Usage

1. **Load Seasons**: Click to load available fashion weeks
2. **Select Season**: Choose a season to browse collections
3. **Download Content**: Click any collection to automatically download:
   - All runway images (high resolution)
   - Verified video content (if available)
4. **View Results**: Browse downloaded content in the organized folder structure

## Architecture

### Core Components
```
backend_server.py           # Flask API server
fashion_scraper.py          # Core scraping logic
google_video_search.py      # AI-powered video search
claude_video_verifier.py    # Video download & verification
image_downloader.py         # Image processing
collection_organizer.py     # File organization
```

### Web Interface
```
web_ui/
├── src/
│   ├── components/         # React components
│   ├── services/          # API communication
│   └── styles/           # CSS styling
└── public/               # Static assets
```

### AI Verification Process
The system uses a sophisticated 5-attempt verification loop:

1. **Google Search**: Query for fashion show videos
2. **Claude Analysis**: AI selects best matching video from results
3. **Title Verification**: Fetch actual video title from YouTube
4. **Strict Validation**: Check brand, year, season, collection type, and source
5. **Retry Logic**: If validation fails, try next best option (up to 5 attempts)

### Example Verification
```
Query: "Givenchy Ready To Wear Fall Winter 2014 Paris"

Attempt 1: ❌ "Givenchy Fall 2014 - Style.com" (banned source)
Attempt 2: ❌ "Givenchy Fall 2012 Ready-to-Wear" (wrong year) 
Attempt 3: ✅ "GIVENCHY Fall Winter 2014" (passes all checks)
```

## Configuration

### Environment Variables
```bash
CLAUDE_API_KEY=your_claude_api_key
```

### Folder Structure
Downloads organize automatically:
```
downloads/
├── Givenchy-Ready-To-Wear-Fall-Winter-2014-Paris/
│   ├── image_001.jpg
│   ├── image_002.jpg
│   └── ...
videos/
└── GIVENCHY-Fall-Winter-2014.mp4
```

## License

MIT License - See LICENSE file for details.