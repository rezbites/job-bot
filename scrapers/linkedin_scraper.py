"""
LinkedIn scraper + Easy Apply automation.
Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD env vars.
"""
import asyncio
import logging
from typing import List, Dict
from .base import BaseScraper, make_job_id, score_job

logger = logging.getLogger("linkedin")

SEARCH_QUERIES = [
    "Machine Learning Engineer",
    "DevOps Engineer",
    "Cloud Engineer",
    "Software Engineer Python",
    "Gen AI Engineer",
    "MLOps",
    "Backend Engineer",
    "Data Engineer",
    "Data Analyst",
    "Data Scientist",
    "Full Stack Developer",
    "Python Developer",
    "Site Reliability Engineer",
]


class LinkedInScraper(BaseScraper):
    name = "LinkedIn"
    _logged_in = False

    async def _login(self, page):
        if self._logged_in:
            return True
        try:
            # First: check if already logged in via existing Opera cookies
            await page.goto("https://www.linkedin.com/feed/", timeout=30000)
            await asyncio.sleep(3)

            if "feed" in page.url or "mynetwork" in page.url:
                self._logged_in = True
                logger.info("LinkedIn: already logged in (existing session)")
                return True

            # Not logged in — try credential login
            if not self.config.LINKEDIN_EMAIL:
                logger.warning("LinkedIn: not logged in and no credentials set.")
                return False

            logger.info("LinkedIn: not logged in, attempting credential login...")
            await page.goto("https://www.linkedin.com/login", timeout=30000)
            await asyncio.sleep(2)

            if self.config.LINKEDIN_PASSWORD:
                await page.fill('#username', self.config.LINKEDIN_EMAIL)
                await page.fill('#password', self.config.LINKEDIN_PASSWORD)
                await page.click('button[type="submit"]')
                await asyncio.sleep(4)

            if "feed" in page.url or "mynetwork" in page.url:
                self._logged_in = True
                logger.info("LinkedIn: logged in via credentials")
                return True
            if "checkpoint" in page.url or "challenge" in page.url:
                logger.warning("LinkedIn: security check required — complete it manually then restart bot")
                return False
            return False
        except Exception as e:
            logger.error(f"LinkedIn login error: {e}")
            return False

    async def _handle_google_auth(self, page) -> bool:
        """Handle Google OAuth flow — pick account or enter credentials."""
        try:
            await asyncio.sleep(2)
            # If account chooser shows, pick the right email
            email_el = await page.query_selector(
                f'div[data-email="{self.config.LINKEDIN_EMAIL}"], '
                f'div:has-text("{self.config.LINKEDIN_EMAIL}")'
            )
            if email_el:
                await email_el.click()
                await asyncio.sleep(4)
            else:
                # Type email if input shown
                email_input = await page.query_selector('input[type="email"]')
                if email_input:
                    await email_input.fill(self.config.LINKEDIN_EMAIL)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(3)
                    # Type password if prompted
                    pw_input = await page.query_selector('input[type="password"]')
                    if pw_input and self.config.LINKEDIN_PASSWORD:
                        await pw_input.fill(self.config.LINKEDIN_PASSWORD)
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(4)

            # Check if we're back on LinkedIn logged in
            await asyncio.sleep(3)
            if "linkedin.com" in page.url and "login" not in page.url:
                return True
            return False
        except Exception as e:
            logger.debug(f"Google auth error: {e}")
            return False

    async def scrape(self) -> List[Dict]:
        jobs = []
        page = await self.new_page()
        try:
            if not await self._login(page):
                logger.warning("LinkedIn: skipping scrape (not logged in)")
                return []

            # Bangalore gets all queries; other cities get a subset to avoid rate limits
            locations = self.config.LOCATIONS
            for loc_idx, location in enumerate(locations):
              loc_encoded = location.replace(' ', '%20')
              queries = SEARCH_QUERIES if loc_idx < 2 else SEARCH_QUERIES[:6]
              for query in queries:
                url = (
                    f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}"
                    f"&location={loc_encoded}%2C%20India"
                    f"&f_TPR=r604800"   # last 7 days
                    f"&f_AL=true"        # Easy Apply only
                    f"&sortBy=DD"
                )
                try:
                    if not await self.safe_goto(page, url):
                        continue

                    # Scroll to load more
                    for _ in range(3):
                        await page.keyboard.press("End")
                        await asyncio.sleep(1.5)

                    cards = await page.query_selector_all('.base-card, .job-search-card')
                    logger.debug(f"LinkedIn '{query}': {len(cards)} cards")

                    for card in cards[:15]:
                        try:
                            title_el = await card.query_selector('.base-search-card__title, h3.base-search-card__title')
                            company_el = await card.query_selector('.base-search-card__subtitle, h4.base-search-card__subtitle')
                            loc_el = await card.query_selector('.job-search-card__location')
                            link_el = await card.query_selector('a.base-card__full-link, a.job-search-card__list-date')

                            if not title_el:
                                continue

                            title = (await title_el.inner_text()).strip()
                            company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                            job_location = (await loc_el.inner_text()).strip() if loc_el else location
                            href = await link_el.get_attribute("href") if link_el else ""

                            # Try to get description by clicking the card
                            description = ""
                            try:
                                await card.click()
                                await asyncio.sleep(1.5)
                                desc_el = await page.query_selector('.jobs-description__content, .show-more-less-html__markup')
                                if desc_el:
                                    description = (await desc_el.inner_text()).strip()[:3000]
                            except Exception:
                                pass

                            job_id = make_job_id("linkedin", title, company, href)
                            tags = self._extract_tags(title + " " + query + " " + description)
                            match = score_job(title, description, tags, self.config.TARGET_ROLES)

                            jobs.append({
                                "id": job_id,
                                "title": title,
                                "company": company,
                                "location": job_location,
                                "salary": "",
                                "platform": "LinkedIn",
                                "url": href,
                                "description": description,
                                "tags": tags,
                                "match_score": match,
                                "easy_apply": True,
                            })
                        except Exception as e:
                            logger.debug(f"LinkedIn card parse error: {e}")

                except Exception as e:
                    logger.warning(f"LinkedIn query '{query}' error: {e}")

                await asyncio.sleep(4)  # polite — LinkedIn rate-limits aggressively

        finally:
            await page.close()

        seen = set()
        unique = []
        for j in jobs:
            if j["id"] not in seen:
                seen.add(j["id"])
                unique.append(j)
        return unique

    def _extract_tags(self, text: str) -> List[str]:
        keywords = [
            "Python", "AWS", "Docker", "Kubernetes", "FastAPI", "DevOps",
            "ML", "AI", "Gen AI", "Cloud", "Linux", "CI/CD", "Go", "Java",
            "TensorFlow", "MLOps", "Backend", "React", "LangChain",
        ]
        text_lower = text.lower()
        return [kw for kw in keywords if kw.lower() in text_lower]

    async def easy_apply(self, page, job: dict, resume_path: str, cover_letter: str) -> bool:
        """
        Attempt LinkedIn Easy Apply for a job.
        Returns True if successfully submitted.
        """
        try:
            await page.goto(job["url"], timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # Click Easy Apply button
            apply_btn = await page.query_selector('button.jobs-apply-button, .jobs-s-apply button')
            if not apply_btn:
                logger.info(f"No Easy Apply button for: {job['title']}")
                return False

            await apply_btn.click()
            await asyncio.sleep(2)

            # Handle multi-step form
            max_steps = 6
            for step in range(max_steps):
                # Fill phone if asked
                phone_field = await page.query_selector('input[id*="phone"], input[name*="phone"]')
                if phone_field:
                    val = await phone_field.input_value()
                    if not val:
                        await phone_field.fill(self.config.PHONE)

                # Fill cover letter textarea if present
                cover_field = await page.query_selector('textarea[id*="cover"], textarea[placeholder*="cover"]')
                if cover_field and cover_letter:
                    await cover_field.fill(cover_letter[:1000])

                # Upload resume if file input present
                file_input = await page.query_selector('input[type="file"]')
                if file_input and resume_path:
                    await file_input.set_input_files(resume_path)
                    await asyncio.sleep(1)

                # Handle "Yes/No" radio questions conservatively
                radio_yes = await page.query_selector('input[type="radio"][value="Yes"], label:has-text("Yes")')
                if radio_yes:
                    await radio_yes.click()

                # Try to advance / submit
                next_btn = await page.query_selector('button[aria-label="Continue to next step"], button[aria-label="Submit application"]')
                review_btn = await page.query_selector('button[aria-label="Review your application"]')
                submit_btn = await page.query_selector('button[aria-label="Submit application"]')

                if submit_btn:
                    await submit_btn.click()
                    await asyncio.sleep(2)
                    logger.info(f"LinkedIn Easy Apply submitted: {job['title']} @ {job['company']}")
                    return True
                elif review_btn:
                    await review_btn.click()
                elif next_btn:
                    await next_btn.click()
                else:
                    break

                await asyncio.sleep(1.5)

            return False

        except Exception as e:
            logger.error(f"LinkedIn Easy Apply error for {job.get('title')}: {e}")
            return False
