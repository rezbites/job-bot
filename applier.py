"""
Job applier — decides how to apply based on platform and applies.
"""
import asyncio
import logging
from datetime import date
from pathlib import Path
from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.naukri_scraper import NaukriScraper
from db import JobDatabase
from resume_tailor import ResumeTailor
from qa_handler import QAHandler
from config import config

logger = logging.getLogger("applier")

RESUME_PDF = Path(config.RESUME_PDF)

# Safety: skip jobs with these patterns in description
BLOCKLIST_PATTERNS = [
    "nigerian prince", "wire transfer", "work from home $5000",
    "whatsapp only", "no experience no problem earn",
]


def is_safe(job: dict) -> bool:
    """Basic safety check to avoid scam/injection jobs."""
    combined = (job.get("title", "") + job.get("description", "") + job.get("company", "")).lower()
    for pattern in BLOCKLIST_PATTERNS:
        if pattern in combined:
            logger.warning(f"Blocked suspicious job: {job.get('title')} — matched '{pattern}'")
            return False
    # Skip if URL is non-http or file:// etc.
    url = job.get("url", "")
    if url and not url.startswith("http"):
        return False
    return True


class JobApplier:
    def __init__(self, db: JobDatabase, tailor: ResumeTailor):
        self.db = db
        self.tailor = tailor
        self.qa = QAHandler(db)
        self._linkedin_scraper: LinkedInScraper = None
        self._naukri_scraper: NaukriScraper = None

    def _get_today_count(self) -> int:
        """Get today's apply count from the database (survives restarts)."""
        from datetime import date as _date
        today = _date.today().strftime("%Y-%m-%d")
        row = self.db.conn.execute(
            "SELECT applied FROM daily_stats WHERE date=?", (today,)
        ).fetchone()
        return row["applied"] if row else 0

    async def apply(self, job: dict):
        if self._get_today_count() >= config.MAX_APPLIES_PER_DAY:
            logger.info("Daily apply cap reached — stopping for today.")
            return

        if not is_safe(job):
            self.db.mark_outcome(job["id"], "skipped", "Safety filter")
            return

        # Skip low match score (threshold lowered since scoring starts at 0)
        if job.get("match_score", 0) < 5:
            logger.debug(f"Skipping low-match job: {job.get('title')} (score={job.get('match_score')})")
            return

        # Always use original resume (tailoring disabled for now)
        original_pdf = str(RESUME_PDF)
        tailored = ""
        tailored_pdf = original_pdf
        cover = ""

        # Discover career page for future scraping
        self._discover_career_page(job)

        platform = job.get("platform", "").lower()
        success = False

        try:
            if "linkedin" in platform:
                success = await self._apply_linkedin(job, tailored_pdf, cover)
            elif "naukri" in platform:
                success = await self._apply_naukri(job)
            elif "indeed" in platform:
                success = await self._apply_indeed(job)
            elif "company" in platform:
                success = await self._apply_company_page(job, tailored_pdf, cover)
            else:
                # Generic: open URL and log for manual
                logger.info(f"Unknown platform for {job.get('title')} — logging for manual apply")
                success = False

            if success:
                resume_note = tailored[:500] if tailored else "[Original resume used]"
                self.db.mark_applied(job["id"], resume_note)
                logger.info(f"[APPLIED] {job['title']} @ {job['company']} [{platform}]")
            else:
                self.db.mark_outcome(job["id"], "skipped", "Could not auto-apply")
                logger.info(f"[SKIPPED] No auto-apply path: {job['title']} @ {job['company']}")

        except Exception as e:
            logger.error(f"Apply exception for {job.get('title')}: {e}")
            self.db.mark_outcome(job["id"], "error", str(e))

    async def _fill_form_questions(self, page) -> int:
        """Try to answer text/select questions on a form page. Returns count of fields filled."""
        filled = 0
        # Text inputs with labels
        labels = await page.query_selector_all('label')
        for label in labels:
            try:
                text = (await label.inner_text()).strip()
                if not text or len(text) < 3:
                    continue
                for_attr = await label.get_attribute("for")
                if not for_attr:
                    continue
                field = await page.query_selector(f'#{for_attr}')
                if not field:
                    continue

                tag = await field.evaluate("el => el.tagName.toLowerCase()")
                answer = self.qa.get_answer(text)
                if not answer:
                    continue

                if tag == "input":
                    input_type = await field.get_attribute("type") or "text"
                    current_val = await field.input_value()
                    if input_type in ("text", "tel", "email", "url", "number") and not current_val:
                        await field.fill(answer)
                        filled += 1
                elif tag == "textarea":
                    current_val = await field.input_value()
                    if not current_val:
                        await field.fill(answer)
                        filled += 1
                elif tag == "select":
                    # Try to select option matching answer
                    options = await field.query_selector_all("option")
                    for opt in options:
                        opt_text = (await opt.inner_text()).strip().lower()
                        if answer.lower() in opt_text or opt_text in answer.lower():
                            val = await opt.get_attribute("value")
                            if val:
                                await field.select_option(val)
                                filled += 1
                            break
            except Exception:
                continue

        if filled:
            logger.info(f"Auto-filled {filled} form questions")
        return filled

    def _discover_career_page(self, job: dict):
        """If a job URL points to a company career page, save it for future scraping."""
        url = job.get("url", "")
        company = job.get("company", "")
        if not url or not company:
            return
        # Detect common career page patterns
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        career_indicators = ["career", "jobs", "greenhouse", "lever", "workday",
                             "recruitee", "bamboohr", "ashbyhq", "breezy"]
        if any(ind in domain or ind in parsed.path.lower() for ind in career_indicators):
            # Only save if not already in static config
            known = {c["name"].lower() for c in config.COMPANY_CAREER_PAGES}
            if company.lower() not in known:
                self.db.add_career_page(company, url, job.get("platform", ""))
                logger.info(f"Discovered career page: {company} -> {url}")

    async def _apply_linkedin(self, job: dict, resume_pdf: str, cover: str) -> bool:
        if not self._linkedin_scraper:
            self._linkedin_scraper = LinkedInScraper(config)
        page = await self._linkedin_scraper.new_page()
        try:
            if not await self._linkedin_scraper._login(page):
                return False
            return await self._linkedin_scraper.easy_apply(page, job, resume_pdf, cover)
        finally:
            await page.close()

    async def _apply_naukri(self, job: dict) -> bool:
        if not self._naukri_scraper:
            self._naukri_scraper = NaukriScraper(config)
        page = await self._naukri_scraper.new_page()
        try:
            if not await self._naukri_scraper._login(page):
                return False
            return await self._naukri_scraper.apply_naukri(page, job)
        finally:
            await page.close()

    async def _apply_indeed(self, job: dict) -> bool:
        """Indeed apply — attempts to use the Indeed Apply button if available."""
        from scrapers.indeed_scraper import IndeedScraper
        scraper = IndeedScraper(config)
        page = await scraper.new_page()
        try:
            if not await scraper._login(page):
                logger.info(f"Indeed: not logged in, skipping apply for {job['title']}")
                return False

            await page.goto(job["url"], timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # Look for Indeed's own Apply button
            apply_btn = await page.query_selector(
                '#indeedApplyButton, '
                'button[id*="indeedApply"], '
                'button:has-text("Apply now"), '
                'button:has-text("Apply on company site")'
            )
            if not apply_btn:
                logger.info(f"Indeed: no apply button found for {job['title']}")
                return False

            btn_text = (await apply_btn.inner_text()).strip().lower()

            # If it's "apply on company site", it redirects externally — skip
            if "company site" in btn_text:
                logger.info(f"Indeed: external redirect for {job['title']} — skipping")
                return False

            await apply_btn.click()
            await asyncio.sleep(3)

            # Handle Indeed's multi-step apply form
            for _ in range(5):
                # Fill phone if empty
                phone = await page.query_selector('input[id*="phone"], input[name*="phone"]')
                if phone:
                    val = await phone.input_value()
                    if not val:
                        await phone.fill(config.PHONE)

                # Upload resume if file input present
                file_input = await page.query_selector('input[type="file"]')
                if file_input:
                    resume_path = str(RESUME_PDF) if RESUME_PDF.exists() else ""
                    if resume_path:
                        await file_input.set_input_files(resume_path)
                        await asyncio.sleep(1)

                # Try continue/submit
                submit = await page.query_selector(
                    'button:has-text("Submit"), '
                    'button:has-text("Apply"), '
                    'button[type="submit"]'
                )
                cont = await page.query_selector(
                    'button:has-text("Continue"), '
                    'button:has-text("Next")'
                )

                if submit and "submit" in (await submit.inner_text()).strip().lower():
                    await submit.click()
                    await asyncio.sleep(2)
                    logger.info(f"Indeed applied: {job['title']} @ {job['company']}")
                    return True
                elif cont:
                    await cont.click()
                    await asyncio.sleep(2)
                else:
                    break

            return False
        except Exception as e:
            logger.error(f"Indeed apply error for {job.get('title')}: {e}")
            return False
        finally:
            await page.close()

    async def _apply_company_page(self, job: dict, resume_pdf: str, cover: str) -> bool:
        """
        Generic company ATS apply.
        Detects Workday, Greenhouse, Lever, and fills known field patterns.
        """
        from scrapers.company_scraper import CompanyScraper
        if not hasattr(self, '_company_scraper') or not self._company_scraper:
            self._company_scraper = CompanyScraper(config)
        page = await self._company_scraper.new_page()
        try:
            await page.goto(job["url"], timeout=35000, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            url = page.url.lower()
            if "greenhouse" in url:
                return await self._fill_greenhouse(page, resume_pdf, cover)
            elif "lever" in url:
                return await self._fill_lever(page, resume_pdf, cover)
            elif "workday" in url:
                return await self._fill_workday(page)
            else:
                return False
        finally:
            await page.close()

    async def _fill_greenhouse(self, page, resume_pdf: str, cover: str) -> bool:
        try:
            await page.fill('input[id="first_name"], input[name="first_name"]', config.FULL_NAME.split()[0])
            await page.fill('input[id="last_name"], input[name="last_name"]', config.FULL_NAME.split()[-1])
            await page.fill('input[id="email"], input[name="email"]', config.EMAIL)
            await page.fill('input[id="phone"], input[name="phone"]', config.PHONE)

            file_input = await page.query_selector('input[type="file"]')
            if file_input and Path(resume_pdf).exists():
                await file_input.set_input_files(resume_pdf)
                await asyncio.sleep(2)

            cover_field = await page.query_selector('textarea[name="cover_letter"]')
            if cover_field and cover:
                await cover_field.fill(cover[:1500])

            # Answer any extra form questions
            await self._fill_form_questions(page)

            submit = await page.query_selector('input[type="submit"], button[type="submit"]')
            if submit:
                await submit.click()
                await asyncio.sleep(3)
                return True
        except Exception as e:
            logger.error(f"Greenhouse fill error: {e}")
        return False

    async def _fill_lever(self, page, resume_pdf: str, cover: str) -> bool:
        try:
            await page.fill('input[name="name"]', config.FULL_NAME)
            await page.fill('input[name="email"]', config.EMAIL)
            await page.fill('input[name="phone"]', config.PHONE)

            file_input = await page.query_selector('input[type="file"]')
            if file_input and Path(resume_pdf).exists():
                await file_input.set_input_files(resume_pdf)
                await asyncio.sleep(2)

            # Answer any extra form questions
            await self._fill_form_questions(page)

            submit = await page.query_selector('button[type="submit"], input[type="submit"]')
            if submit:
                await submit.click()
                await asyncio.sleep(3)
                return True
        except Exception as e:
            logger.error(f"Lever fill error: {e}")
        return False

    async def _fill_workday(self, page) -> bool:
        logger.info("Workday detected — requires account login, logging for manual apply")
        return False
