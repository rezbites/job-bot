"""
Quick test: find 1 LinkedIn Easy Apply job and attempt to apply.
Runs headless=False so you can watch it happen.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Setup logging to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(
        open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
    )]
)
logger = logging.getLogger("test")

from config import config
from scrapers.base import get_shared_context
from scrapers.linkedin_scraper import LinkedInScraper
from db import JobDatabase
from qa_handler import QAHandler

# Force visible browser
config.HEADLESS = False
config.SLOW_MO = 200

RESUME_PDF = str(Path(config.RESUME_PDF))


async def main():
    db = JobDatabase()
    qa = QAHandler(db)

    scraper = LinkedInScraper(config)
    scraper.qa = qa

    page = await scraper.new_page()

    logger.info("=== Step 1: Login ===")
    logged_in = await scraper._login(page)
    if not logged_in:
        logger.error("Not logged in — aborting")
        await page.close()
        return

    logger.info("=== Step 2: Find 1 Easy Apply job ===")
    url = (
        "https://www.linkedin.com/jobs/search/"
        "?keywords=Python+Developer"
        "&location=Bengaluru%2C+India"
        "&f_AL=true"      # Easy Apply only
        "&f_TPR=r604800"  # last 7 days
        "&sortBy=DD"
    )
    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # Scroll once to trigger card load
    await page.keyboard.press("End")
    await asyncio.sleep(2)

    cards = await page.query_selector_all('li[data-occludable-job-id]')
    logger.info(f"Found {len(cards)} cards")

    if not cards:
        logger.error("No cards found — taking screenshot")
        await page.screenshot(path="logs/test_no_cards.png")
        await page.close()
        return

    # Scan cards, find first one that actually has Easy Apply button
    target_job = None
    logger.info(f"Scanning up to {min(len(cards), 15)} cards for Easy Apply jobs...")

    for i, card in enumerate(cards[:15]):
        li_job_id = await card.get_attribute('data-occludable-job-id')
        if not li_job_id:
            continue
        href = f"https://www.linkedin.com/jobs/view/{li_job_id}"

        title_el = await card.query_selector('a.job-card-list__title--link, .job-card-list__title')
        company_el = await card.query_selector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle span')

        # Clean up multi-line titles (LinkedIn adds "verified" badge text)
        raw_title = (await title_el.inner_text()).strip() if title_el else "Unknown"
        title = raw_title.split('\n')[0].strip()
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        # Quick check: click job card to load detail pane, look for Easy Apply button
        try:
            await card.click()
            await asyncio.sleep(2)
            apply_btn = await page.query_selector(
                'button.jobs-apply-button[aria-label*="Easy Apply"], '
                'button[aria-label*="Easy Apply"]'
            )
            if apply_btn:
                logger.info(f"  ✅ Card {i+1}: {title} @ {company} — HAS Easy Apply | {href}")
                target_job = {"title": title, "company": company, "url": href}
                break
            else:
                logger.info(f"  ⏭  Card {i+1}: {title} @ {company} — no Easy Apply, skipping")
        except Exception as e:
            logger.debug(f"  Card {i+1} click error: {e}")

    if not target_job:
        logger.error("No Easy Apply jobs found in first 15 cards — try a different query")
        await page.close()
        return

    await page.close()

    logger.info(f"=== Step 3: Attempting Easy Apply for: {target_job['title']} @ {target_job['company']} ===")
    logger.info(f"URL: {target_job['url']}")

    apply_page = await scraper.new_page()
    try:
        success = await scraper.easy_apply(apply_page, target_job, RESUME_PDF, "")
        if success:
            logger.info(f"✅ APPLIED SUCCESSFULLY: {target_job['title']} @ {target_job['company']}")
        else:
            logger.info(f"❌ Apply did not complete — check screenshot in logs/ea_error_*.png")
    finally:
        logger.info("Pausing 8 seconds so you can review the browser...")
        await asyncio.sleep(8)
        await apply_page.close()

    # Close browser
    from scrapers.base import _shared_context, _shared_pw
    if _shared_context:
        await _shared_context.close()
    if _shared_pw:
        await _shared_pw.stop()

asyncio.run(main())
