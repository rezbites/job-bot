"""
Batch job application: Apply to multiple job categories.
- 10 Cloud/DevOps jobs
- 10 AI/ML jobs  
- 10 Software Engineering jobs
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
import time
import random

from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.base import _shared_context, _shared_pw, make_job_id, score_job
from applier import JobApplier
from resume_tailor import ResumeTailor
from db import JobDatabase
from config import config

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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
logger = logging.getLogger("batch")

# Job categories with search queries
JOB_CATEGORIES = {
    "cloud_devops": {
        "queries": ["Cloud Engineer", "DevOps Engineer", "AWS Engineer", "Azure DevOps", "Site Reliability Engineer"],
        "target": 10,
        "applied": 0,
    },
    "aiml": {
        "queries": ["Machine Learning Engineer", "AI Engineer", "Data Scientist", "MLOps Engineer", "Deep Learning Engineer"],
        "target": 10,
        "applied": 0,
    },
    "software_engineering": {
        "queries": ["Software Engineer", "Backend Engineer", "Python Developer", "Full Stack Developer", "Software Developer"],
        "target": 10,
        "applied": 0,
    },
}

LOCATION = "Bengaluru"
applied_job_ids = set()  # Track applied jobs to avoid duplicates


async def search_and_apply(scraper, applier, db, page, query: str, category: str, max_apply: int) -> int:
    """Search for jobs and apply to up to max_apply positions. Returns count of successful applications."""
    applied_count = 0
    
    url = (
        f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}"
        f"&location={LOCATION}%2C%20India"
        f"&f_TPR=r604800"  # Last 7 days
        f"&f_AL=true"       # Easy Apply
        f"&sortBy=DD"       # Most recent
    )
    
    logger.info(f"[{category.upper()}] Searching: {query} @ {LOCATION}")
    if not await scraper.safe_goto(page, url):
        logger.error(f"Failed to load search page for: {query}")
        return 0
    
    await asyncio.sleep(3)
    
    # Scroll to load more cards
    for _ in range(2):
        await page.keyboard.press("End")
        await asyncio.sleep(1.5)
    
    cards = await page.query_selector_all('li[data-occludable-job-id], li.jobs-search-results__list-item')
    logger.info(f"Found {len(cards)} job cards for '{query}'")
    
    if not cards:
        return 0
    
    for idx, card in enumerate(cards[:15]):  # Check up to 15 cards per query
        if applied_count >= max_apply:
            break
            
        try:
            # Try multiple ways to get job ID
            li_job_id = await card.get_attribute('data-occludable-job-id')
            if not li_job_id:
                # Try finding the link inside the card
                link_el = await card.query_selector('a[href*="/jobs/view/"]')
                if link_el:
                    href_attr = await link_el.get_attribute('href')
                    if href_attr and '/jobs/view/' in href_attr:
                        import re
                        match = re.search(r'/jobs/view/(\d+)', href_attr)
                        if match:
                            li_job_id = match.group(1)
            
            if not li_job_id:
                # Log only first few missing IDs
                if idx < 3:
                    logger.info(f"  Card {idx}: no job ID found, skipping")
                continue
            
            href = f"https://www.linkedin.com/jobs/view/{li_job_id}"
            
            # Skip if already applied
            if li_job_id in applied_job_ids:
                continue
            
            title_el = await card.query_selector(
                'a.job-card-list__title--link, '
                '.job-card-list__title, '
                'a[href*="/jobs/view/"] strong, '
                'strong.job-card-list__title'
            )
            if not title_el:
                # Try additional selectors
                title_el = await card.query_selector(
                    '.artdeco-entity-lockup__title strong, '
                    '.job-card-container__link strong, '
                    'span.job-card-list__title, '
                    '.job-card-list__entity-lockup strong'
                )
            if not title_el:
                if idx < 3:
                    logger.info(f"  Card {idx} (job {li_job_id}): no title element found, skipping")
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
            
            tags = scraper._extract_tags(title + " " + description)
            match = score_job(title, description, tags, config.TARGET_ROLES)
            
            logger.info(f"  [{category}] Candidate: {title} @ {company} | score={match}")
            
            # Since we're filtering by Easy Apply in the URL, skip individual verification
            # The apply logic will handle any edge cases
            logger.info(f"  ✓ Proceeding with: {title}")
            
            # Create job dict
            job = {
                "id": job_id,
                "title": title,
                "company": company,
                "location": LOCATION,
                "salary": "",
                "platform": "LinkedIn",
                "url": href,
                "description": description,
                "tags": tags,
                "match_score": match,
                "easy_apply": True,
            }
            
            # Save to database
            db.filter_new([job])
            
            # Apply!
            logger.info(f">>> APPLYING: {title} @ {company}")
            success, msg = await applier.apply(job)
            
            if success:
                applied_count += 1
                applied_job_ids.add(li_job_id)
                logger.info(f"✅ APPLIED [{applied_count}]: {title} @ {company}")
                
                # Random delay between applications (5-10 seconds) to avoid rate limits
                delay = random.uniform(5, 10)
                logger.info(f"  Waiting {delay:.1f}s before next application...")
                await asyncio.sleep(delay)
            else:
                logger.warning(f"❌ Failed to apply: {title} - {msg}")
                # Still delay a bit on failure
                await asyncio.sleep(2)
                
        except Exception as e:
            logger.warning(f"Card processing error on card {idx}: {e}")
            continue
    
    return applied_count


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
        
        total_applied = 0
        
        # Process each category
        for cat_name, cat_data in JOB_CATEGORIES.items():
            target = cat_data["target"]
            applied = cat_data["applied"]
            queries = cat_data["queries"]
            
            logger.info(f"\n{'='*60}")
            logger.info(f"CATEGORY: {cat_name.upper()} (target: {target})")
            logger.info(f"{'='*60}")
            
            query_idx = 0
            while applied < target and query_idx < len(queries):
                remaining = target - applied
                query = queries[query_idx]
                
                count = await search_and_apply(
                    scraper, applier, db, page, 
                    query, cat_name, 
                    max_apply=min(remaining, 5)  # Apply up to 5 per query
                )
                
                applied += count
                cat_data["applied"] = applied
                total_applied += count
                
                logger.info(f"[{cat_name}] Progress: {applied}/{target} applied")
                
                query_idx += 1
                
                # Delay between queries (longer to avoid rate limits)
                if applied < target and query_idx < len(queries):
                    delay = random.uniform(10, 15)
                    logger.info(f"Switching to next query in {delay:.1f}s...")
                    await asyncio.sleep(delay)
            
            if applied < target:
                logger.warning(f"[{cat_name}] Only applied to {applied}/{target} jobs (ran out of results)")
        
        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("BATCH COMPLETE - SUMMARY")
        logger.info(f"{'='*60}")
        for cat_name, cat_data in JOB_CATEGORIES.items():
            logger.info(f"  {cat_name}: {cat_data['applied']}/{cat_data['target']}")
        logger.info(f"  TOTAL: {total_applied}/30")
        logger.info(f"{'='*60}")
        
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
        logger.info("Interrupted by user")
    finally:
        import os
        os._exit(0)
