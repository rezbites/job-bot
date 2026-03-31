#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Job Bot — Setup & Run Script
# Run this once to install, then use start.sh / stop.sh to control the bot.
# ─────────────────────────────────────────────────────────────────────────────
set -e

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                    JOB BOT SETUP                     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 1. Create virtual environment
if [ ! -d "venv" ]; then
  echo "→ Creating Python virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate

# 2. Install dependencies
echo "→ Installing Python packages..."
pip install -q -r requirements.txt

# 3. Install Playwright browsers (Chromium only)
echo "→ Installing Playwright Chromium..."
playwright install chromium
playwright install-deps chromium 2>/dev/null || true

# 4. Create dirs
mkdir -p logs data resume

# 5. Copy resume if not present
if [ ! -f "resume/your_resume.pdf" ]; then
  echo ""
  echo "⚠️  ACTION REQUIRED: Copy your resume PDF to:"
  echo "     $(pwd)/resume/your_resume.pdf"
  echo ""
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "═══════════════════════════════════════════════════════"
echo " Before running, export your credentials:"
echo ""
echo "   export ANTHROPIC_API_KEY='sk-ant-...'    # required"
echo "   export LINKEDIN_EMAIL='you@email.com'    # for LinkedIn"
echo "   export LINKEDIN_PASSWORD='yourpassword'  # for LinkedIn"
echo "   export NAUKRI_EMAIL='you@email.com'      # for Naukri"
echo "   export NAUKRI_PASSWORD='yourpassword'    # for Naukri"
echo ""
echo " Then run:   ./start.sh"
echo " Dashboard:  http://localhost:8080"
echo " Stop:       ./stop.sh   (or Ctrl+C)"
echo "═══════════════════════════════════════════════════════"
