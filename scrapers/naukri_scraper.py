"""
Naukri.com scraper + apply automation.
Requires NAUKRI_EMAIL and NAUKRI_PASSWORD env vars.
"""
import asyncio
import logging
from typing import List, Dict
from .base import BaseScraper, make_job_id, score_job

logger = logging.getLogger("naukri")

SEARCH_KEYWORDS = [
    "machine learning engineer",
    "devops engineer aws",
    "cloud engineer",
    "software engineer python",
    "gen ai engineer",
    "mlops engineer",
    "backend engineer fastapi",
    "data engineer",
    "data analyst",
    "data scientist",
    "full stack developer",
    "python developer",
    "site reliability engineer",
]


class NaukriScraper(BaseScraper):
    name = "Naukri"
    _logged_in = False

    async def _login(self, page):
        if self._logged_in:
            return True
        try:
            # First: check if already logged in via existing Opera cookies
            await page.goto("https://www.naukri.com/mnjuser/homepage", timeout=30000)
            await asyncio.sleep(3)

            if "naukri.com" in page.url and "login" not in page.url and "nlogin" not in page.url:
                self._logged_in = True
                logger.info("Naukri: already logged in (existing session)")
                return True

            # Not logged in — try credential login
            if not self.config.NAUKRI_EMAIL:
                logger.warning("Naukri: not logged in and no credentials set.")
                return False

            logger.info("Naukri: not logged in, attempting credential login...")
            await page.goto("https://www.naukri.com/nlogin/login", timeout=30000)
            await asyncio.sleep(2)

            if self.config.NAUKRI_PASSWORD:
                await page.fill('#usernameField', self.config.NAUKRI_EMAIL)
                await page.fill('#passwordField', self.config.NAUKRI_PASSWORD)
                await page.click('button[type="submit"]')
                await asyncio.sleep(4)

            if "naukri.com" in page.url and "login" not in page.url:
                self._logged_in = True
                logger.info("Naukri: logged in via credentials")
                return True
            return False
        except Exception as e:
            logger.error(f"Naukri login error: {e}")
            return False

    async def _handle_google_auth(self, page) -> bool:
        """Handle Google OAuth flow — pick account or enter credentials."""
        try:
            await asyncio.sleep(2)
            email_el = await page.query_selector(
                f'div[data-email="{self.config.NAUKRI_EMAIL}"], '
                f'div:has-text("{self.config.NAUKRI_EMAIL}")'
            )
            if email_el:
                await email_el.click()
                await asyncio.sleep(4)
            else:
                email_input = await page.query_selector('input[type="email"]')
                if email_input:
                    await email_input.fill(self.config.NAUKRI_EMAIL)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(3)
                    pw_input = await page.query_selector('input[type="password"]')
                    if pw_input and self.config.NAUKRI_PASSWORD:
                        await pw_input.fill(self.config.NAUKRI_PASSWORD)
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(4)

            await asyncio.sleep(3)
            if "naukri.com" in page.url and "login" not in page.url:
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
                logger.warning("Naukri: skipping scrape (not logged in)")
                return []

            locations = self.config.LOCATIONS
            for loc_idx, loc in enumerate(locations):
              # Bangalore gets all queries; other cities get a subset
              keywords = SEARCH_KEYWORDS if loc_idx < 2 else SEARCH_KEYWORDS[:6]
              for query in keywords:
                q = query.replace(" ", "-")
                loc_slug = loc.lower().replace(" ", "-")
                url = f"https://www.naukri.com/{q}-jobs-in-{loc_slug}?jobAge=7&sort=1"
                try:
                    if not await self.safe_goto(page, url):
                        continue

                    cards = await page.query_selector_all('.jobTuple, article.jobTupleHeader, .cust-job-tuple')
                    logger.debug(f"Naukri '{query}': {len(cards)} cards")

                    for card in cards[:12]:
                        try:
                            title_el = await card.query_selector('a.title, .title a, h2.title')
                            company_el = await card.query_selector('.companyInfo a, .comp-name')
                            loc_el = await card.query_selector('.location span, .locWdth')
                            salary_el = await card.query_selector('.salary, .sal')
                            link_el = await card.query_selector('a.title, a[href*="naukri.com"]')

                            if not title_el:
                                continue

                            title = (await title_el.inner_text()).strip()
                            company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                            job_location = (await loc_el.inner_text()).strip() if loc_el else loc
                            salary = (await salary_el.inner_text()).strip() if salary_el else ""
                            href = await link_el.get_attribute("href") if link_el else ""

                            # Grab description snippet if available on card
                            description = ""
                            try:
                                desc_el = await card.query_selector('.job-desc, .jobDescription')
                                if desc_el:
                                    description = (await desc_el.inner_text()).strip()[:3000]
                            except Exception:
                                pass

                            job_id = make_job_id("naukri", title, company, href)
                            tags = self._extract_tags(title + " " + query + " " + description)
                            match = score_job(title, description, tags, self.config.TARGET_ROLES)

                            jobs.append({
                                "id": job_id,
                                "title": title,
                                "company": company,
                                "location": job_location,
                                "salary": salary,
                                "platform": "Naukri",
                                "url": href,
                                "description": description,
                                "tags": tags,
                                "match_score": match,
                            })
                        except Exception as e:
                            logger.debug(f"Naukri card parse error: {e}")

                except Exception as e:
                    logger.warning(f"Naukri query '{query}' error: {e}")

                await asyncio.sleep(4)

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
            "TensorFlow", "MLOps", "Backend", "React",
        ]
        text_lower = text.lower()
        return [kw for kw in keywords if kw.lower() in text_lower]

    async def apply_naukri(self, page, job: dict) -> bool:
        """Apply to a Naukri job using the Apply button."""
        try:
            await page.goto(job["url"], timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            apply_btn = await page.query_selector('button#apply-button, .apply-button, button:has-text("Apply")')
            if not apply_btn:
                return False

            await apply_btn.click()
            await asyncio.sleep(2)

            # Handle modal if any
            submit = await page.query_selector('button:has-text("Submit"), button:has-text("Apply Now")')
            if submit:
                await submit.click()
                await asyncio.sleep(2)
                logger.info(f"Naukri applied: {job['title']} @ {job['company']}")
                return True
            return False

        except Exception as e:
            logger.error(f"Naukri apply error for {job.get('title')}: {e}")
            return False
