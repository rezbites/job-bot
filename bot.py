"""
Job Auto-Apply Bot — Shashank Choudhary
Targets: Cloud, DevOps, Software Engineer, AI/ML roles
Platforms: Indeed, LinkedIn, Naukri, company career pages
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from scrapers.indeed_scraper import IndeedScraper
from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.naukri_scraper import NaukriScraper
from scrapers.company_scraper import CompanyScraper
from applier import JobApplier
from resume_tailor import ResumeTailor
from db import JobDatabase
from dashboard.server import DashboardServer
from config import config

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

log_file = LOG_DIR / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)),
    ],
)
logger = logging.getLogger("bot")


class JobBot:
    def __init__(self):
        self.db = JobDatabase()
        self.tailor = ResumeTailor()
        self.applier = JobApplier(self.db, self.tailor)
        self.scrapers = [
            LinkedInScraper(config),   # Easy Apply — highest chance of success
            NaukriScraper(config),
            IndeedScraper(config),     # Slow (many pages) — runs last
            CompanyScraper(config),
        ]
        self.dashboard = DashboardServer(self.db)
        self.running = False

    async def run(self):
        self.running = True

        logger.info("Job bot started (bot uses its own browser profile — Opera GX can stay open)")
        logger.info(f"Targeting roles: {', '.join(config.TARGET_ROLES)}")
        logger.info(f"Location: {config.LOCATION}")

        # Start dashboard in background
        asyncio.create_task(self.dashboard.start())

        cycle = 0
        while self.running:
            cycle += 1
            logger.info(f"── Cycle {cycle} ──────────────────────────────")
            try:
                await self._run_cycle()
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)

            if self.running:
                wait = config.CYCLE_INTERVAL_MINUTES * 60
                logger.info(f"Waiting {config.CYCLE_INTERVAL_MINUTES}min before next cycle...")
                # Sleep in short chunks so Ctrl+C exits quickly
                for _ in range(wait):
                    if not self.running:
                        break
                    await asyncio.sleep(1)

        logger.info("Bot stopped.")

    async def _run_cycle(self):
        all_jobs = []

        # 0. Add any discovered career pages to the company scraper config
        discovered = self.db.get_career_pages()
        if discovered:
            known_names = {c["name"].lower() for c in config.COMPANY_CAREER_PAGES}
            for cp in discovered:
                if cp["name"].lower() not in known_names:
                    config.COMPANY_CAREER_PAGES.append(cp)
                    known_names.add(cp["name"].lower())
            logger.info(f"Total company career pages: {len(config.COMPANY_CAREER_PAGES)} ({len(discovered)} discovered)")

        # 1. Scrape jobs from all platforms
        for scraper in self.scrapers:
            try:
                jobs = await scraper.scrape()
                logger.info(f"{scraper.name}: found {len(jobs)} jobs")
                all_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"{scraper.name} scrape error: {e}")

        # 2. Deduplicate and filter already-applied
        new_jobs = self.db.filter_new(all_jobs)
        logger.info(f"New jobs to process: {len(new_jobs)}")

        # 3. Apply to each
        for job in new_jobs:
            if not self.running:
                break
            try:
                await self.applier.apply(job)
                await asyncio.sleep(config.APPLY_DELAY_SECONDS)
            except Exception as e:
                logger.error(f"Apply error for {job.get('title')} at {job.get('company')}: {e}")

    def stop(self):
        self.running = False
        logger.info("Stop signal received.")


_bot_instance = None  # global ref so dashboard can stop the bot


async def main():
    global _bot_instance
    bot = JobBot()
    _bot_instance = bot

    # Windows-compatible signal handling for clean shutdown
    import signal

    def _handle_stop(sig, frame):
        logger.info(f"Received signal {sig} — stopping bot...")
        bot.stop()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    try:
        await bot.run()
    finally:
        # Clean up Playwright browser on exit
        from scrapers.base import _shared_context, _shared_pw
        if _shared_context:
            try:
                await _shared_context.close()
                logger.info("Browser context closed.")
            except Exception:
                pass
        if _shared_pw:
            try:
                await _shared_pw.stop()
                logger.info("Playwright stopped.")
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting.")
    except SystemExit:
        pass
    finally:
        logger.info("Bot process exiting.")
        import os
        os._exit(0)
