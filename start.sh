#!/bin/bash

# Configuration
URL="http://127.0.0.1:8000"
BROWSER_CMD="/usr/bin/firefox"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
SERVER_SCRIPT="$SCRIPT_DIR/server.py"
PROFILE_DIR="$SCRIPT_DIR/browser-profile"

# Ensure profile directory exists
mkdir -p "$PROFILE_DIR"

# Clean up any existing media center processes
echo "Cleaning up any existing media center processes..."
pkill -f "python3 $SERVER_SCRIPT" 2>/dev/null
fuser -k 8000/tcp 2>/dev/null

# Start Server
echo "Starting Media Center Server..."
python3 "$SERVER_SCRIPT" > "$SCRIPT_DIR/server.log" 2>&1 &
SERVER_PID=$!

# Wait for server to respond
echo "Waiting for server to be ready..."
for i in {1..20}; do
    if curl -s --head "$URL" > /dev/null; then
        echo "Server is UP!"
        break
    fi
    sleep 0.5
    if [ $i -eq 20 ]; then
        echo "Error: Server failed to start. Check $SCRIPT_DIR/server.log"
        exit 1
    fi
done

# Start Browser with isolated profile and kiosk mode
echo "Launching Browser in Kiosk mode..."
# --profile ensures we don't conflict with any already-running Firefox
# --kiosk starts it full screen
# --new-instance can also help but --profile is more reliable
"$BROWSER_CMD" --profile "$PROFILE_DIR" --kiosk "$URL" > /dev/null 2>&1 &
BROWSER_PID=$!

echo "=========================================="
echo "   MEDIA CENTER IS RUNNING"
echo "   Press Ctrl+C here to stop everything"
echo "=========================================="

# Cleanup logic
cleanup() {
    echo -e "\nShutting down..."
    kill $BROWSER_PID $SERVER_PID 2>/dev/null
    pkill -f "python3 $SERVER_SCRIPT" 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM

wait

