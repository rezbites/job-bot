"""Base scraper with shared Playwright browser management.

Uses Opera GX with a persistent profile so all your existing logins
(Google, LinkedIn, Naukri, Indeed) carry over automatically.
"""
import asyncio
import hashlib
import logging
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict
from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger("scraper")

# CAPTCHA / challenge page indicators
CAPTCHA_INDICATORS = [
    "captcha", "challenge", "checkpoint", "unusual traffic",
    "verify you are human", "are you a robot", "security check",
    "access denied", "rate limit", "too many requests",
]

# Opera GX paths on Windows
OPERA_EXE = os.getenv(
    "OPERA_PATH",
    r"C:\Users\shash\AppData\Local\Programs\Opera GX\opera.exe"
)
# Use the REAL Opera GX profile — reuses your existing login sessions
# (LinkedIn, Naukri, Indeed, Google — everything you're logged into)
# ⚠️ Opera must be CLOSED before running the bot (Playwright locks the profile)
OPERA_PROFILE_DIR = os.getenv(
    "OPERA_PROFILE",
    r"C:\Users\shash\AppData\Roaming\Opera Software\Opera GX Stable"
)
BOT_PROFILE_DIR = OPERA_PROFILE_DIR


def make_job_id(platform: str, title: str, company: str, url: str = "") -> str:
    raw = f"{platform}:{company}:{title}:{url}"
    return hashlib.md5(raw.encode()).hexdigest()


def score_job(title: str, description: str, tags: list, target_roles: list) -> int:
    """Simple keyword match score 0-100."""
    resume_keywords = [
        "python", "aws", "docker", "kubernetes", "fastapi", "flask",
        "tensorflow", "scikit", "mlops", "devops", "ci/cd", "ecs", "fargate",
        "postgresql", "mongodb", "redis", "react", "github actions", "linux",
        "nlp", "ml", "ai", "langchain", "rag", "cloudformation", "fargate",
        "prometheus", "grafana", "go", "java", "data analyst", "data scientist",
        "full stack", "pandas", "numpy", "pytorch",
    ]
    text = (title + " " + description + " " + " ".join(tags)).lower()
    hits = sum(1 for kw in resume_keywords if kw in text)
    score = min(100, int((hits / max(len(resume_keywords), 1)) * 100))
    # Bonus if title matches target role
    for role in target_roles:
        if any(word in title.lower() for word in role.lower().split()):
            score = min(100, score + 15)
            break
    return score


# Shared browser instance — all scrapers reuse the same browser + profile
_shared_pw = None
_shared_context = None


async def get_shared_context(config) -> BrowserContext:
    """Launch Opera GX with persistent profile (shared across all scrapers).
    First run: you'll need to log into Google once. After that, sessions persist."""
    global _shared_pw, _shared_context

    if _shared_context:
        return _shared_context

    _shared_pw = await async_playwright().start()

    # Ensure profile dir exists
    Path(BOT_PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    # Use persistent context — this saves cookies, localStorage, sessions
    # between bot runs. Log in once, stays logged in forever.
    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
    ]

    _shared_context = await _shared_pw.chromium.launch_persistent_context(
        user_data_dir=BOT_PROFILE_DIR,
        executable_path=OPERA_EXE if Path(OPERA_EXE).exists() else None,
        headless=config.HEADLESS,
        slow_mo=config.SLOW_MO,
        args=launch_args,
        viewport={"width": 1366, "height": 800},
        locale="en-IN",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36 OPR/108.0.0.0"
        ),
    )

    # Block tracking/analytics
    await _shared_context.route(
        re.compile(r"(doubleclick|googlesyndication|analytics|facebook\.com/tr|hotjar)"),
        lambda route: route.abort()
    )

    logger.info(f"Browser launched: {'Opera GX' if Path(OPERA_EXE).exists() else 'Chromium'} "
                f"(profile: {BOT_PROFILE_DIR})")
    return _shared_context


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, config):
        self.config = config
        self.context: BrowserContext = None

    async def _get_context(self):
        if not self.context:
            self.context = await get_shared_context(self.config)
        return self.context

    async def new_page(self) -> Page:
        global _shared_context
        for attempt in range(2):
            try:
                ctx = await self._get_context()
                page = await ctx.new_page()
                # Anti-detection: hide webdriver flag
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = {runtime: {}};
                """)
                return page
            except Exception as e:
                if "closed" in str(e).lower() and attempt == 0:
                    logger.warning(f"Browser context was closed — reinitializing browser... ({e})")
                    _shared_context = None
                    self.context = None
                else:
                    raise

    async def safe_goto(self, page: Page, url: str, retries: int = 3,
                        timeout: int = 30000) -> bool:
        """Navigate to a URL with retry logic and CAPTCHA detection.
        Returns True if page loaded successfully, False otherwise."""
        for attempt in range(retries):
            try:
                await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                await asyncio.sleep(2)

                # Check for CAPTCHA / challenge pages
                if await self._detect_captcha(page):
                    logger.warning(f"CAPTCHA/challenge detected on {url} — "
                                   f"may need manual intervention")
                    return False

                return True
            except Exception as e:
                wait_secs = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                if attempt < retries - 1:
                    logger.warning(f"{self.name}: page load failed (attempt {attempt + 1}/{retries}), "
                                   f"retrying in {wait_secs}s — {e}")
                    await asyncio.sleep(wait_secs)
                else:
                    logger.error(f"{self.name}: page load failed after {retries} attempts — {e}")
        return False

    async def _detect_captcha(self, page: Page) -> bool:
        """Check if the current page is a CAPTCHA or challenge page."""
        try:
            url_lower = page.url.lower()
            if any(ind in url_lower for ind in ["captcha", "challenge", "checkpoint"]):
                return True

            # Check page content for CAPTCHA indicators
            body_text = await page.evaluate("document.body?.innerText?.substring(0, 2000) || ''")
            body_lower = body_text.lower()
            if any(ind in body_lower for ind in CAPTCHA_INDICATORS):
                return True
        except Exception:
            pass
        return False

    async def close(self):
        # Don't close shared context — it's reused across scrapers
        pass

    @abstractmethod
    async def scrape(self) -> List[Dict]:
        """Return list of job dicts."""
        ...
