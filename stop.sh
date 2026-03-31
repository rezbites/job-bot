#!/usr/bin/env bash
# Stop the job bot (Windows + Linux)
PID_FILE=".bot.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "No PID file. Trying to kill python bot.py directly..."
  # Windows: kill by process name
  taskkill //F //IM python.exe //FI "WINDOWTITLE eq bot*" 2>/dev/null || true
  # Also try pkill
  pkill -f "python bot.py" 2>/dev/null || pkill -f "python.exe bot.py" 2>/dev/null || true
  echo "Done."
  exit 0
fi

PID=$(cat "$PID_FILE")
echo "Stopping bot (PID $PID)..."

# Try graceful kill
kill "$PID" 2>/dev/null || taskkill //PID "$PID" //F 2>/dev/null || true
sleep 2

# Force kill if still running
if kill -0 "$PID" 2>/dev/null; then
  kill -9 "$PID" 2>/dev/null || taskkill //PID "$PID" //F 2>/dev/null || true
  echo "Force-killed."
else
  echo "Bot stopped."
fi

rm -f "$PID_FILE"
