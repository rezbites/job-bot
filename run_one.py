"""
Quick one-shot: find ONE cloud job on LinkedIn and apply.
No full scrape cycle — just 1 search query, 1 apply attempt.
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.base import _shared_context, _shared_pw
from applier import JobApplier
from resume_tailor import ResumeTailor
from db import JobDatabase
from config import config

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
        ),
    ],
)
logger = logging.getLogger("run_one")


async def main():
    db = JobDatabase()
    tailor = ResumeTailor()
    applier = JobApplier(db, tailor)
    scraper = LinkedInScraper(config)

    page = await scraper.new_page()
    try:
        if not await scraper._login(page):
            logger.error("Could not log in to LinkedIn — aborting")
            return

        # Search for ONE query only: Cloud Engineer, Bengaluru, Easy Apply, last 7 days
        query = "Cloud Engineer"
        location = "Bengaluru"
        url = (
            f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}"
            f"&location={location}%2C%20India"
            f"&f_TPR=r604800"
            f"&f_AL=true"
            f"&sortBy=DD"
        )
        logger.info(f"Searching: {query} @ {location}")
        if not await scraper.safe_goto(page, url):
            logger.error("Failed to load LinkedIn search page")
            return

        await asyncio.sleep(3)

        # Scroll once to load cards
        await page.keyboard.press("End")
        await asyncio.sleep(2)

        cards = await page.query_selector_all('li[data-occludable-job-id]')
        logger.info(f"Found {len(cards)} job cards")

        if not cards:
            logger.error("No job cards found — taking screenshot for debugging")
            await page.screenshot(path="logs/run_one_debug.png")
            return

        # Pick the first card that has "cloud" in its title
        target_job = None
        from scrapers.base import make_job_id, score_job

        for card in cards[:15]:
            try:
                li_job_id = await card.get_attribute('data-occludable-job-id')
                if not li_job_id:
                    continue
                href = f"https://www.linkedin.com/jobs/view/{li_job_id}"
                title_el = await card.query_selector(
                    'a.job-card-list__title--link, '
                    '.job-card-list__title, '
                    'a[href*="/jobs/view/"] strong, '
                    'strong.job-card-list__title'
                )
                if not title_el:
                    continue
                title = (await title_el.inner_text()).strip()
                company_el = await card.query_selector(
                    '.job-card-container__company-name, '
                    '.artdeco-entity-lockup__subtitle span'
                )
                company = (await company_el.inner_text()).strip() if company_el else "Unknown"

                # Click card to get description
                description = ""
                try:
                    await card.click()
                    await asyncio.sleep(1.5)
                    desc_el = await page.query_selector(
                        '.jobs-description__content, '
                        '.show-more-less-html__markup, '
                        '#job-details'
                    )
                    if desc_el:
                        description = (await desc_el.inner_text()).strip()[:3000]
                except Exception:
                    pass

                job_id = make_job_id("linkedin", title, company, href)
                tags = scraper._extract_tags(title + " Cloud " + description)
                match = score_job(title, description, tags, config.TARGET_ROLES)

                logger.info(f"  Candidate: {title} @ {company} | score={match}")

                # Verify Easy Apply button exists on the actual job page
                verify_page = await scraper.new_page()
                try:
                    await verify_page.goto(href, timeout=30000, wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                    # Check for visual text Easy Apply with wait
                    apply_btn = None
                    try:
                        apply_btn = await verify_page.wait_for_selector(
                            'button:has-text("Easy Apply"), '
                            'button.jobs-apply-button:has-text("Easy Apply")',
                            timeout=7000
                        )
                    except Exception:
                        pass
                    if not apply_btn:
                        buttons = await verify_page.query_selector_all('button')
                        for b in buttons:
                            inner = (await b.inner_text()).strip()
                            if "Easy Apply" in inner:
                                apply_btn = b
                                break
                                
                    if not apply_btn:
                        logger.info(f"  Skipping (no Easy Apply button on page): {title}")
                        continue
                    logger.info(f"  ✓ Easy Apply button confirmed for: {title}")
                except Exception as e:
                    logger.info(f"  Skipping (verify failed): {title} — {e}")
                    continue
                finally:
                    await verify_page.close()

                target_job = {
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": "Bengaluru",
                    "salary": "",
                    "platform": "LinkedIn",
                    "url": href,
                    "description": description,
                    "tags": tags,
                    "match_score": match,
                    "easy_apply": True,
                }
                logger.info(f">>> SELECTED: {title} @ {company}")
                break

            except Exception as e:
                logger.debug(f"Card parse error: {e}")

        if not target_job:
            logger.error("No cloud-related job found in the results")
            return

        # Save the job to the database
        db.filter_new([target_job])

        # Now apply to this one job
        logger.info(f"Applying to: {target_job['title']} @ {target_job['company']}")
        await applier.apply(target_job)
        logger.info("Done!")

    finally:
        await page.close()
        # Clean up browser
        from scrapers.base import _shared_context, _shared_pw
        if _shared_context:
            try:
                await _shared_context.close()
            except Exception:
                pass
        if _shared_pw:
            try:
                await _shared_pw.stop()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        import os
        os._exit(0)
