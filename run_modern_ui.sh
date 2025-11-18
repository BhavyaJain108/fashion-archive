#!/bin/bash

# Fashion Archive System - Modern UI Launcher
# Launches both Python backend and React frontend

echo "🎭 Fashion Archive System - Modern UI"
echo "📚 Preserving fashion history with early Mac styling"
echo "="

# Check if we're in the right directory
if [ ! -d "backend" ]; then
    echo "❌ Please run this script from the fashion_archive directory"
    exit 1
fi

# Check if web_ui directory exists
if [ ! -d "web_ui" ]; then
    echo "❌ web_ui directory not found"
    exit 1
fi

# Graceful shutdown function
cleanup() {
    echo ""
    echo "🛑 Shutting down gracefully..."

    # Kill frontend (port 3000)
    if [ ! -z "$FRONTEND_PID" ]; then
        echo "Stopping React frontend..."
        kill -TERM $FRONTEND_PID 2>/dev/null
        wait $FRONTEND_PID 2>/dev/null
    fi
    lsof -ti:3000 | xargs kill -9 2>/dev/null

    # Kill backend (port 8081)
    if [ ! -z "$BACKEND_PID" ]; then
        echo "Stopping Python backend..."
        kill -TERM $BACKEND_PID 2>/dev/null
        wait $BACKEND_PID 2>/dev/null
    fi
    lsof -ti:8081 | xargs kill -9 2>/dev/null

    echo "✅ All processes stopped"
    exit 0
}

# Trap signals for graceful shutdown
trap cleanup SIGINT SIGTERM EXIT

# Install Python dependencies if needed
echo "🔧 Setting up Python backend..."
if [ ! -f "venv/bin/activate" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r web_ui_requirements.txt > /dev/null 2>&1

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

# Kill old processes on ports
echo "Cleaning up old processes..."
lsof -ti:3000 | xargs kill -9 2>/dev/null
lsof -ti:8081 | xargs kill -9 2>/dev/null
sleep 1

# Start unified backend (all APIs)
echo "Starting Unified Backend API on port 8081..."
cd ..
source venv/bin/activate
python backend/app.py &
BACKEND_PID=$!

echo "Waiting for backend to start..."
sleep 3

# Start React frontend (browser only)
echo "Starting React frontend on port 3000..."
cd web_ui
npm run dev-react &
FRONTEND_PID=$!

# Wait for processes (will be interrupted by Ctrl+C)
wait