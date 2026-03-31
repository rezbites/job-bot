# Job Auto-Apply Bot

Automated job search + apply bot targeting Cloud, DevOps, ML, AI, and Software Engineer roles.
Covers **Indeed, LinkedIn, Naukri, and company career pages**.
Includes a **local dashboard** at `http://localhost:8080` to track every application.

---

## Features

| Feature | Details |
|---|---|
| **Multi-platform search** | Indeed, LinkedIn (Easy Apply), Naukri, 7+ company career pages |
| **AI resume tailoring** | Claude rewrites your resume per job for ATS optimization |
| **Cover letter generation** | Auto-generated, role-specific cover letters |
| **Smart filtering** | Blocks scam jobs, low-match roles, and experience mismatches |
| **Local dashboard** | Track applied / replied / interview / accepted / rejected |
| **Daily logs** | Saved to `logs/bot_YYYYMMDD.log`, rotated daily |
| **Start/stop control** | `./start.sh` and `./stop.sh` — no daemons or cron needed |
| **Safety-first** | Anti-bot detection evasion, rate limiting, blocklist filtering |

---

## Quick Start

### 1. Clone / place the project folder

```bash
cd ~/job-bot
```

### 2. Run setup (one time)

```bash
chmod +x setup.sh start.sh stop.sh
./setup.sh
```

### 3. Copy your resume

```bash
cp /path/to/your_resume.pdf resume/your_resume.pdf
```

### 4. Install Ollama (free, runs locally — no API key needed)

```bash
# Install Ollama from https://ollama.com, then pull a model:
ollama pull mistral        # recommended — fast, good quality (~4GB)
# alternatives: ollama pull llama3   /  ollama pull phi3  /  ollama pull deepseek-r1
```

Ollama runs on `http://localhost:11434` by default. The bot uses it automatically.

To change the model, set an env var:
```bash
export OLLAMA_MODEL="llama3"   # default is mistral
```

### 5. Fill in your credentials in `.env`

Open the `.env` file (already created in the folder) and fill in your details:

```
LINKEDIN_EMAIL=your.email@example.com
LINKEDIN_PASSWORD=yourpassword

NAUKRI_EMAIL=your@naukri.com
NAUKRI_PASSWORD=yourpassword

OLLAMA_MODEL=mistral
```

The bot loads `.env` automatically on startup — no `export` commands, no editing `~/.zshrc`.
The `.env` file is in `.gitignore` so it will never be accidentally committed anywhere.

### 5. Start the bot

```bash
./start.sh
```

### 6. Open dashboard

```
http://localhost:8080
```

### 7. Stop the bot

```bash
./stop.sh
# or just Ctrl+C in the terminal running start.sh
```

---

## Dashboard

| Tab | What it shows |
|---|---|
| **All Jobs** | Every job found, filterable by platform/status/search |
| **Applied** | Jobs the bot applied to, with dates |
| **Interviews** | Jobs you marked as "interview scheduled" |
| **Accepted** | Offers received |
| **Rejected** | Rejections |
| **Skipped** | Jobs skipped (low match, safety filter, no auto-apply path) |
| **Logs** | Live log tail — last 100 lines from today's log file |

To update a job's outcome (e.g., you got a reply), click **Update** on any row and select the outcome.

---

## Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `MAX_APPLIES_PER_CYCLE` | 15 | Max applies per search cycle |
| `MAX_APPLIES_PER_DAY` | 50 | Daily cap |
| `APPLY_DELAY_SECONDS` | 8 | Pause between applies (human-like) |
| `CYCLE_INTERVAL_MINUTES` | 60 | How often to search for new jobs |
| `HEADLESS` | True | Set False to watch the browser |
| `MIN_SALARY_LPA` | 4.0 | Skip jobs below this salary (if listed) |
| `COMPANY_CAREER_PAGES` | 7 companies | Edit to add/remove company pages |

---

## Platform Coverage

### Indeed
- Searches 8 role categories in Bengaluru + Remote
- Logs jobs found; most Indeed jobs require visiting the listing

### LinkedIn
- Logs in with your credentials
- Uses **Easy Apply** only (safer, faster)
- Handles multi-step forms, phone fields, resume upload, cover letter

### Naukri
- Logs in with your credentials
- Clicks Apply button on job listings
- Handles modal confirmation dialogs

### Company Career Pages
Configured in `config.py → COMPANY_CAREER_PAGES`:
- Google, Microsoft, Amazon, Flipkart, Razorpay, Zepto, Meesho
- Add any company by adding `{"name": "...", "url": "...careers page..."}`

### ATS Platforms (via company pages)
- **Greenhouse**: auto-fills name, email, phone, resume, cover letter
- **Lever**: auto-fills name, email, phone, resume
- **Workday**: logs for manual apply (requires account)

---

## Safety

- **Anti-detection**: hides `navigator.webdriver`, uses realistic user-agent, slow_mo delays
- **Scam filter**: blocks jobs with suspicious patterns in title/description
- **Rate limiting**: configurable delays between applies and cycle intervals
- **Daily cap**: stops applying after `MAX_APPLIES_PER_DAY`
- **No credential storage**: all secrets via env vars only

---

## Log Files

```
logs/
  bot_20260321.log   ← today's log
  bot_20260320.log   ← yesterday's
  ...
```

Logs rotate daily automatically. View the last 100 lines live in the dashboard → **Logs** tab.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| LinkedIn requires CAPTCHA | Run with `HEADLESS=False` in config, complete manually, then set back to True |
| Playwright not found | Re-run `./setup.sh` |
| `ANTHROPIC_API_KEY` missing | Export the env var before running `./start.sh` |
| Bot stops immediately | Check `logs/bot_YYYYMMDD.log` for error details |
| Dashboard not loading | Make sure bot is running; port 8080 must be free |

---

## File Structure

```
job-bot/
├── bot.py                  # Main orchestrator — start here
├── config.py               # All settings + your profile
├── db.py                   # SQLite job tracking database
├── applier.py              # Apply logic for all platforms
├── resume_tailor.py        # Claude API resume/cover letter generation
├── scrapers/
│   ├── base.py             # Playwright browser base class
│   ├── indeed_scraper.py   # Indeed search
│   ├── linkedin_scraper.py # LinkedIn search + Easy Apply
│   ├── naukri_scraper.py   # Naukri search + apply
│   └── company_scraper.py  # Company career pages
├── dashboard/
│   ├── server.py           # aiohttp API server
│   └── index.html          # Dashboard UI
├── resume/
│   └── your_resume.pdf # ← copy your resume here
├── logs/                   # Daily rotating log files
├── data/
│   └── jobs.db             # SQLite database (auto-created)
├── requirements.txt
├── setup.sh                # One-time setup
├── start.sh                # Start bot
└── stop.sh                 # Stop bot
```
