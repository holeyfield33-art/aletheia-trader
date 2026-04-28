#!/bin/bash
# Aletheia Trader - Full System Startup

set -e

echo "======================================"
echo "🎯 Aletheia Trader - Operational System"
echo "======================================"
echo ""

# Kill any existing processes
echo "Cleaning up old processes..."
pkill -f "uvicorn api.server" 2>/dev/null || true
pkill -f "streamlit run" 2>/dev/null || true
sleep 1

# Create data directory if it doesn't exist
mkdir -p data

# Start API server in background
echo "▶ Starting FastAPI server (port 8000)..."
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 > /tmp/api.log 2>&1 &
API_PID=$!
echo "  API Server PID: $API_PID"
sleep 3

# Check if API is running
if ! curl -s http://127.0.0.1:8000/health > /dev/null; then
    echo "❌ API Server failed to start"
    cat /tmp/api.log
    exit 1
fi

echo "✅ API Server running"
echo ""

# Start Streamlit dashboard
echo "▶ Starting Streamlit Dashboard (port 8501)..."
python -m streamlit run dashboard/app_enhanced.py --server.port 8501 --logger.level=error &
DASH_PID=$!
echo "  Dashboard PID: $DASH_PID"
sleep 3

echo "✅ Dashboard running"
echo ""
echo "======================================"
echo "🎯 SYSTEM READY"
echo "======================================"
echo ""
echo "📊 Dashboard:  http://localhost:8501"
echo "🔌 API Docs:   http://localhost:8000/docs"
echo "❤️  API Health: http://localhost:8000/health"
echo ""
echo "Press CTRL+C to stop all services"
echo ""

# Trap to clean up on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $API_PID 2>/dev/null || true
    kill $DASH_PID 2>/dev/null || true
    echo "✅ Services stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for any process to finish
wait
