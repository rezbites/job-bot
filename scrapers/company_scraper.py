"""
Company career pages scraper.
Visits configured company career pages and finds relevant openings.
"""
import asyncio
import logging
import re
from typing import List, Dict
from .base import BaseScraper, make_job_id, score_job

logger = logging.getLogger("company")

ROLE_KEYWORDS = [
    "machine learning", "ml engineer", "ai engineer", "devops", "cloud engineer",
    "software engineer", "backend engineer", "data engineer", "platform engineer",
    "site reliability", "infrastructure", "mlops", "gen ai", "llm",
    "data analyst", "data scientist", "full stack", "python developer",
    "business analyst", "sre",
]


class CompanyScraper(BaseScraper):
    name = "CompanyPages"

    async def scrape(self) -> List[Dict]:
        jobs = []
        page = await self.new_page()
        try:
            for company_cfg in self.config.COMPANY_CAREER_PAGES:
                name = company_cfg["name"]
                url = company_cfg["url"]
                try:
                    if not await self.safe_goto(page, url, timeout=35000):
                        continue

                    # Generic approach: find all job-title links on the page
                    links = await page.query_selector_all('a')
                    for link in links:
                        try:
                            text = (await link.inner_text()).strip()
                            if not text or len(text) < 5 or len(text) > 120:
                                continue
                            text_lower = text.lower()
                            if not any(kw in text_lower for kw in ROLE_KEYWORDS):
                                continue

                            href = await link.get_attribute("href") or ""
                            if not href:
                                continue
                            if href.startswith("/"):
                                # Make absolute
                                from urllib.parse import urlparse
                                parsed = urlparse(url)
                                href = f"{parsed.scheme}://{parsed.netloc}{href}"

                            job_id = make_job_id(f"company_{name}", text, name, href)
                            tags = self._extract_tags(text)
                            match = score_job(text, "", tags, self.config.TARGET_ROLES)

                            jobs.append({
                                "id": job_id,
                                "title": text,
                                "company": name,
                                "location": "Bengaluru / India",
                                "salary": "",
                                "platform": f"Company ({name})",
                                "url": href,
                                "description": "",
                                "tags": tags,
                                "match_score": match,
                            })
                        except Exception:
                            pass

                    logger.info(f"Company '{name}': found {len([j for j in jobs if j['company'] == name])} matching jobs")

                except Exception as e:
                    logger.warning(f"Company '{name}' error: {e}")

                await asyncio.sleep(3)

        finally:
            await page.close()

        # Deduplicate
        seen = set()
        unique = []
        for j in jobs:
            if j["id"] not in seen:
                seen.add(j["id"])
                unique.append(j)
        return unique

    def _extract_tags(self, text: str) -> List[str]:
        keywords = [
            "Python", "AWS", "Docker", "Kubernetes", "ML", "AI", "Gen AI",
            "DevOps", "Cloud", "Backend", "Data", "Platform", "MLOps", "SRE",
            "Infrastructure", "Linux", "Go", "Java",
        ]
        text_lower = text.lower()
        return [kw for kw in keywords if kw.lower() in text_lower]
