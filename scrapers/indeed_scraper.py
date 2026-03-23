"""Indeed India scraper."""
import asyncio
import logging
from typing import List, Dict
from .base import BaseScraper, make_job_id, score_job

logger = logging.getLogger("indeed")

SEARCH_QUERIES = [
    "Machine Learning Engineer",
    "DevOps Engineer AWS",
    "Cloud Engineer Kubernetes",
    "Software Engineer Python",
    "Gen AI Engineer",
    "MLOps Engineer",
    "Backend Engineer FastAPI",
    "Data Engineer",
    "Data Analyst",
    "Data Scientist",
    "Full Stack Developer Python",
    "Python Developer",
    "Site Reliability Engineer",
]


class IndeedScraper(BaseScraper):
    name = "Indeed"
    _logged_in = False

    async def _login(self, page):
        """Login to Indeed. Checks for existing session first (Opera cookies)."""
        if self._logged_in:
            return True
        try:
            # First: check if already logged in via existing Opera cookies
            await page.goto("https://in.indeed.com/", timeout=30000)
            await asyncio.sleep(3)

            # If we're on the main page (not auth/login), we're logged in
            if "secure.indeed.com/auth" not in page.url and "indeed.com" in page.url:
                self._logged_in = True
                logger.info("Indeed: already logged in (existing session)")
                return True

            # Not logged in — try credential login
            if not self.config.INDEED_EMAIL:
                logger.warning("Indeed: not logged in and no credentials set.")
                return False

            logger.info("Indeed: not logged in, attempting credential login...")
            await page.goto("https://secure.indeed.com/auth", timeout=30000)
            await asyncio.sleep(2)

            # Try Google sign-in button
            google_btn = await page.query_selector(
                'button[data-tn-element="google-login"], '
                '[id*="google"], '
                'a[href*="accounts.google.com"], '
                'button:has-text("Google"), '
                'button:has-text("Continue with Google")'
            )
            if google_btn:
                await google_btn.click()
                await asyncio.sleep(3)

                email_el = await page.query_selector(
                    f'div[data-email="{self.config.INDEED_EMAIL}"], '
                    f'div:has-text("{self.config.INDEED_EMAIL}")'
                )
                if email_el:
                    await email_el.click()
                    await asyncio.sleep(3)

            # Check if we landed on Indeed logged-in page
            if "secure.indeed.com/auth" not in page.url:
                self._logged_in = True
                logger.info("Indeed: logged in successfully")
                return True

            logger.warning("Indeed: login did not complete — may need manual Google auth first run")
            return False
        except Exception as e:
            logger.error(f"Indeed login error: {e}")
            return False

    async def scrape(self) -> List[Dict]:
        jobs = []
        page = await self.new_page()
        try:
            # Attempt login for better results (not strictly required for scraping)
            await self._login(page)

            locations = [loc.replace(' ', '+') for loc in self.config.LOCATIONS]
            for query in SEARCH_QUERIES:
                for location in locations:
                    url = (
                        f"https://in.indeed.com/jobs?q={query.replace(' ', '+')}"
                        f"&l={location}%2C+India&fromage=7&sort=date"
                    )
                    try:
                        if not await self.safe_goto(page, url):
                            continue

                        cards = await page.query_selector_all('[data-testid="slider_item"], .job_seen_beacon')
                        logger.debug(f"Indeed '{query}': {len(cards)} cards")

                        for card in cards[:10]:
                            try:
                                title_el = await card.query_selector('[data-testid="jobTitle"], .jobTitle')
                                company_el = await card.query_selector('[data-testid="company-name"], .companyName')
                                loc_el = await card.query_selector('[data-testid="text-location"], .companyLocation')
                                salary_el = await card.query_selector('.metadata.salary-snippet-container, [data-testid="attribute_snippet_testid"]')
                                link_el = await card.query_selector('a[data-testid="job-title-link"], a.jcs-JobTitle')

                                if not title_el:
                                    continue

                                title = (await title_el.inner_text()).strip()
                                company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                                job_location = (await loc_el.inner_text()).strip() if loc_el else location
                                salary = (await salary_el.inner_text()).strip() if salary_el else ""
                                href = await link_el.get_attribute("href") if link_el else ""
                                if href and not href.startswith("http"):
                                    href = "https://in.indeed.com" + href

                                # Try to get description by clicking card
                                description = ""
                                try:
                                    await card.click()
                                    await asyncio.sleep(1)
                                    desc_el = await page.query_selector('#jobDescriptionText, .jobsearch-JobComponent-description')
                                    if desc_el:
                                        description = (await desc_el.inner_text()).strip()[:3000]
                                except Exception:
                                    pass

                                job_id = make_job_id("indeed", title, company, href)
                                tags = self._extract_tags(title + " " + query + " " + description)
                                match = score_job(title, description, tags, self.config.TARGET_ROLES)

                                jobs.append({
                                    "id": job_id,
                                    "title": title,
                                    "company": company,
                                    "location": job_location,
                                    "salary": salary,
                                    "platform": "Indeed",
                                    "url": href,
                                    "description": description,
                                    "tags": tags,
                                    "match_score": match,
                                })
                            except Exception as e:
                                logger.debug(f"Card parse error: {e}")
                    except Exception as e:
                        logger.warning(f"Indeed query '{query}' error: {e}")

                    await asyncio.sleep(3)  # polite delay
        finally:
            await page.close()

        # Deduplicate by id
        seen = set()
        unique = []
        for j in jobs:
            if j["id"] not in seen:
                seen.add(j["id"])
                unique.append(j)
        return unique

    def _extract_tags(self, text: str) -> List[str]:
        keywords = [
            "Python", "AWS", "Docker", "Kubernetes", "FastAPI", "Flask",
            "TensorFlow", "Scikit-learn", "MLOps", "DevOps", "CI/CD",
            "PostgreSQL", "MongoDB", "Redis", "React", "Linux", "NLP",
            "ML", "AI", "Gen AI", "LangChain", "RAG", "Go", "Java",
            "Cloud", "ECS", "Fargate", "GitHub Actions", "Prometheus",
        ]
        text_lower = text.lower()
        return [kw for kw in keywords if kw.lower() in text_lower]
