#!/bin/bash

# Fashion Archive System - Modern UI Launcher
# Launches both Python backend and React frontend

echo "🎭 Fashion Archive System - Modern UI"
echo "📚 Preserving fashion history with early Mac styling"
echo "=" 

# Check if we're in the right directory
if [ ! -f "clean_api.py" ]; then
    echo "❌ Please run this script from the fashion_archive directory"
    exit 1
fi

# Check if web_ui directory exists
if [ ! -d "web_ui" ]; then
    echo "❌ web_ui directory not found"
    exit 1
fi

# Install Python dependencies if needed
echo "🔧 Setting up Python backend..."
if [ ! -f "venv/bin/activate" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r web_ui_requirements.txt

# Install Node.js dependencies if needed
echo "🔧 Setting up React frontend..."
cd web_ui
if [ ! -d "node_modules" ]; then
    npm install
fi

# Check if we need to install electron
if ! command -v electron &> /dev/null; then
    echo "Installing Electron..."
    npm install -g electron
fi

echo ""
echo "🚀 Starting Fashion Archive System..."
echo "📱 React UI with early Mac styling"
echo "🐍 Python backend maintaining all original functionality"
echo ""

# Kill ALL old Python processes first
pkill -f "python" 2>/dev/null || true
pkill -f "backend_server.py" 2>/dev/null || true
pkill -f "headless_backend.py" 2>/dev/null || true
pkill -f "api_backend.py" 2>/dev/null || true
sleep 1

# Start ONLY the clean API backend
echo "Starting CLEAN API backend (no tkinter)..."
cd ..
source venv/bin/activate
python clean_api.py &
BACKEND_PID=$!

echo "Waiting for clean backend to start..."
sleep 3

# Start React frontend (browser only)
echo "Starting React frontend (browser only)..."
cd web_ui
npm run dev-react

# Kill backend when frontend exits
kill $BACKEND_PID 2>/dev/null