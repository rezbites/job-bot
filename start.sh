#!/usr/bin/env bash
# Start the job bot (works on Windows Git Bash / WSL)
set -e

# Activate venv (Windows or Linux)
if [ -f ".venv/Scripts/activate" ]; then
  source .venv/Scripts/activate
elif [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

PID_FILE=".bot.pid"

# Stop existing if running
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping existing bot (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 2
  fi
  rm -f "$PID_FILE"
fi

echo ""
echo "Starting Job Bot..."
echo "   Dashboard: http://localhost:8080"
echo "   Logs:      logs/bot_$(date +%Y%m%d).log"
echo "   Stop:      Ctrl+C  or  ./stop.sh"
echo ""

# Run in foreground so Ctrl+C works
python bot.py &
BOT_PID=$!
echo $BOT_PID > "$PID_FILE"
echo "Bot PID: $BOT_PID"

wait $BOT_PID
rm -f "$PID_FILE"
echo "Bot stopped."
