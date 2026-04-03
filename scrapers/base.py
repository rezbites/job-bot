"""Base scraper with shared Playwright browser management.

Uses Chromium/Chrome persistent profile so existing logins carry over automatically.
The browser using that profile must be CLOSED before running the bot (OS profile lock).
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

CHROMIUM_EXE = os.getenv("CHROMIUM_PATH", "")
CHROME_EXE = os.getenv(
    "CHROME_PATH",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)
CHROME_PROFILE_NAME = os.getenv("CHROME_PROFILE_NAME", "Default")
CHROME_CDP_URL = os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222")
# Use bot-local profile for remote debugging compatibility
BOT_PROFILE_DIR = os.getenv(
    "CHROME_PROFILE",
    str(Path(__file__).parent.parent / "data" / "chrome_profile")
)


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


import subprocess
import signal

def _kill_chrome_processes():
    """Kill all Chrome processes to release profile lock."""
    try:
        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="ignore")
        pids = []
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if parts and parts[0].lower() == 'chrome.exe':
                try:
                    pids.append(int(parts[1]))
                except:
                    pass
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        return len(pids)
    except:
        return 0

def _launch_chrome_with_cdp(port: int = 9222):
    """Launch Chrome with remote debugging enabled and return the CDP URL."""
    import time
    import urllib.request
    
    chrome_path = CHROME_EXE
    profile = BOT_PROFILE_DIR
    profile_name = CHROME_PROFILE_NAME
    
    # Launch Chrome with debugging port
    cmd = [
        chrome_path,
        f"--user-data-dir={profile}",
        f"--profile-directory={profile_name}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ]
    
    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    
    # Wait for Chrome to start and CDP to be available
    cdp_url = f"http://127.0.0.1:{port}"
    for _ in range(10):  # 10 second timeout
        time.sleep(1)
        try:
            urllib.request.urlopen(f"{cdp_url}/json/version", timeout=2)
            return cdp_url
        except:
            pass
    return None


async def get_shared_context(config) -> BrowserContext:
    """Launch Chromium/Chrome with existing profile (all existing logins intact)."""
    global _shared_pw, _shared_context

    if _shared_context:
        return _shared_context

    _shared_pw = await async_playwright().start()

    # Strategy: Kill Chrome, relaunch with CDP, connect via CDP
    # This preserves DPAPI-encrypted cookies that Playwright's Chromium can't decrypt
    cdp_url = CHROME_CDP_URL
    if not cdp_url:
        logger.info("Preparing Chrome with remote debugging...")
        killed = _kill_chrome_processes()
        if killed > 0:
            logger.info(f"Killed {killed} Chrome processes to release profile lock")
            import time
            time.sleep(2)  # Wait for profile to be fully released
        
        cdp_url = _launch_chrome_with_cdp(port=9222)
        if cdp_url:
            logger.info(f"Chrome launched with CDP at {cdp_url}")
        else:
            logger.warning("Failed to launch Chrome with CDP - falling back to direct launch")
            cdp_url = None

    if cdp_url:
        try:
            browser = await _shared_pw.chromium.connect_over_cdp(cdp_url)
            if browser.contexts:
                _shared_context = browser.contexts[0]
            else:
                _shared_context = await browser.new_context(
                    viewport={"width": 1366, "height": 800},
                    locale="en-IN",
                )
            logger.info(f"Browser connected over CDP: {cdp_url}")
            return _shared_context
        except Exception as e:
            logger.warning(f"CDP connect failed ({cdp_url}); falling back to persistent launch: {e}")
        except Exception as e:
            logger.warning(f"CDP connect failed ({CHROME_CDP_URL}); falling back to persistent launch: {e}")

    Path(BOT_PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        f"--profile-directory={CHROME_PROFILE_NAME}",
    ]

    # Use actual Chrome to preserve DPAPI-encrypted cookies
    browser_exe = None
    browser_name = "Chromium"
    if CHROMIUM_EXE and Path(CHROMIUM_EXE).exists():
        browser_exe = CHROMIUM_EXE
    elif CHROME_EXE and Path(CHROME_EXE).exists():
        browser_exe = CHROME_EXE
        browser_name = "Chrome"

    _shared_context = await _shared_pw.chromium.launch_persistent_context(
        user_data_dir=BOT_PROFILE_DIR,
        executable_path=browser_exe,
        headless=config.HEADLESS,
        slow_mo=config.SLOW_MO,
        args=launch_args,
        viewport={"width": 1366, "height": 800},
        locale="en-IN",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    )

    await _shared_context.route(
        re.compile(r"(doubleclick|googlesyndication|analytics|facebook\.com/tr|hotjar)"),
        lambda route: route.abort()
    )

    logger.info(f"Browser launched: {browser_name} "
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
                await asyncio.sleep(3)  # Increased delay to be more human-like

                # Check for CAPTCHA / challenge pages
                if await self._detect_captcha(page):
                    logger.warning(f"CAPTCHA/challenge detected on {url} — "
                                   f"may need manual intervention")
                    # Save screenshot for debugging
                    try:
                        from datetime import datetime
                        ts = datetime.now().strftime("%H%M%S")
                        await page.screenshot(path=f"logs/captcha_detected_{ts}.png")
                        logger.info(f"  Captcha screenshot saved: captcha_detected_{ts}.png")
                    except Exception:
                        pass
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
