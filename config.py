"""
Configuration — edit this file to customize the bot.
"""
from dataclasses import dataclass, field
from typing import List
import os
from pathlib import Path


def _load_dotenv():
    """Load .env file into environment variables (no external libs needed)."""
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:  # don't override real env vars
                os.environ[key] = val

_load_dotenv()


@dataclass
class Config:
    # ── Your profile ──────────────────────────────────────────────────────────
    FULL_NAME: str = "Shashank Choudhary"
    EMAIL: str = "shashank.30choudhary@gmail.com"
    PHONE: str = "+91-8050522728"
    LOCATION: str = "Bengaluru, Karnataka, India"
    LINKEDIN_URL: str = "https://www.linkedin.com/in/itsshashank/"
    GITHUB_URL: str = "https://github.com/rezbites"
    PORTFOLIO_URL: str = ""  # add if you have one

    # ── Target roles ──────────────────────────────────────────────────────────
    TARGET_ROLES: List[str] = field(default_factory=lambda: [
        "Software Engineer",
        "Backend Engineer",
        "Full Stack Engineer",
        "Full Stack Developer",
        "Python Developer",
        "Cloud Engineer",
        "DevOps Engineer",
        "AWS Engineer",
        "MLOps Engineer",
        "ML Engineer",
        "Machine Learning Engineer",
        "AI Engineer",
        "Gen AI Engineer",
        "Data Engineer",
        "Data Analyst",
        "Data Scientist",
        "Business Analyst",
        "Platform Engineer",
        "Site Reliability Engineer",
        "Infrastructure Engineer",
    ])

    LOCATIONS: List[str] = field(default_factory=lambda: [
        "Bengaluru",
        "Bangalore",
        "Remote",
        "Hyderabad",
        "Pune",
        "Mumbai",
        "Gurgaon",
        "Gurugram",
        "Noida",
    ])

    # ── Experience level ──────────────────────────────────────────────────────
    EXPERIENCE_YEARS: int = 1           # fresher / intern level
    JOB_TYPES: List[str] = field(default_factory=lambda: [
        "fulltime", "internship", "contract"
    ])

    # ── Platform credentials (set via env vars — never hardcode) ──────────────
    # Export these in your terminal before running:
    #   export LINKEDIN_EMAIL="you@email.com"
    #   export LINKEDIN_PASSWORD="yourpassword"
    LINKEDIN_EMAIL: str = field(default_factory=lambda: os.getenv("LINKEDIN_EMAIL", ""))
    LINKEDIN_PASSWORD: str = field(default_factory=lambda: os.getenv("LINKEDIN_PASSWORD", ""))
    NAUKRI_EMAIL: str = field(default_factory=lambda: os.getenv("NAUKRI_EMAIL", ""))
    NAUKRI_PASSWORD: str = field(default_factory=lambda: os.getenv("NAUKRI_PASSWORD", ""))
    INDEED_EMAIL: str = field(default_factory=lambda: os.getenv("INDEED_EMAIL", ""))
    INDEED_PASSWORD: str = field(default_factory=lambda: os.getenv("INDEED_PASSWORD", ""))

    # ── Anthropic API for resume tailoring ────────────────────────────────────
    ANTHROPIC_API_KEY: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # ── Safety settings ───────────────────────────────────────────────────────
    MAX_APPLIES_PER_CYCLE: int = 15      # cap to avoid bans
    MAX_APPLIES_PER_DAY: int = 50
    APPLY_DELAY_SECONDS: int = 8         # human-like pause between applies
    CYCLE_INTERVAL_MINUTES: int = 60     # how often to search for new jobs
    HEADLESS: bool = False               # False = see the browser (needed for first-run login)
    SLOW_MO: int = 150                   # ms between browser actions (human-like)

    # ── Filters ───────────────────────────────────────────────────────────────
    MIN_SALARY_LPA: float = 4.0          # skip if salary listed and below this
    SKIP_KEYWORDS: List[str] = field(default_factory=lambda: [
        "5+ years", "10+ years", "senior only", "principal only",
        "director", "VP", "C-level",
    ])

    # ── Paths ─────────────────────────────────────────────────────────────────
    RESUME_PDF: str = "resume/shashanks_resume.pdf"
    DATA_DIR: str = "data"
    LOGS_DIR: str = "logs"
    DASHBOARD_PORT: int = 8080

    # ── Company career page targets ───────────────────────────────────────────
    COMPANY_CAREER_PAGES: List[dict] = field(default_factory=lambda: [
        {"name": "Google", "url": "https://careers.google.com/jobs/results/?q=software+engineer+ml&location=Bangalore"},
        {"name": "Microsoft", "url": "https://jobs.careers.microsoft.com/global/en/search?q=devops+cloud&l=en_us&pg=1&pgSz=20"},
        {"name": "Amazon", "url": "https://www.amazon.jobs/en/search?base_query=cloud+devops+ml&loc_query=Bangalore"},
        {"name": "Flipkart", "url": "https://www.flipkartcareers.com/#!/joblist"},
        {"name": "Razorpay", "url": "https://razorpay.com/jobs/"},
        {"name": "Zepto", "url": "https://www.zepto.team/careers"},
        {"name": "Meesho", "url": "https://meesho.io/jobs"},
        {"name": "PhonePe", "url": "https://www.phonepe.com/careers/"},
        {"name": "Swiggy", "url": "https://careers.swiggy.com/"},
        {"name": "CRED", "url": "https://careers.cred.club/"},
        {"name": "Atlassian", "url": "https://www.atlassian.com/company/careers/all-jobs?team=Engineering&location=India"},
        {"name": "Uber", "url": "https://www.uber.com/in/en/careers/list/?query=engineer&location=IND-Bangalore"},
        {"name": "Zomato", "url": "https://www.zomato.com/careers"},
        {"name": "Ola", "url": "https://www.olacabs.com/careers"},
        {"name": "Juspay", "url": "https://juspay.in/careers"},
        {"name": "Groww", "url": "https://groww.in/careers"},
    ])

    # File to persist dynamically discovered company career pages
    DISCOVERED_CAREERS_FILE: str = "data/discovered_careers.json"


config = Config()


def __repr__(self):
    """Prevent accidental credential leaks in logs/tracebacks."""
    safe = {k: ("***" if any(s in k.lower() for s in ("password", "key", "secret", "token")) else v)
            for k, v in self.__dict__.items()}
    return f"Config({safe})"


Config.__repr__ = __repr__
