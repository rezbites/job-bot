"""
LinkedIn scraper + Easy Apply automation.
Uses Opera GX persistent profile (existing login session).

Key fix: uses data-occludable-job-id attribute on <li> cards to build
job URLs directly — avoids href selector failures that caused 0 applications.
Reference: GodsScion/Auto_job_applier_linkedIn
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
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


async def _click_span_text(page, *texts) -> bool:
    """Click a button that contains a span with the given text. Returns True if clicked."""
    for text in texts:
        try:
            # Try multiple selectors for LinkedIn buttons
            selectors = [
                f'button:has(span:text-is("{text}"))',
                f'[role="button"]:has(span:text-is("{text}"))',
                f'button:has-text("{text}")',
                f'[role="button"]:has-text("{text}")',
            ]
            for selector in selectors:
                btn = await page.query_selector(selector)
                if btn:
                    # Check if button is visible and enabled
                    is_visible = await btn.is_visible()
                    is_enabled = await btn.is_enabled()
                    if is_visible and is_enabled:
                        await btn.click()
                        logger.info(f"    Clicked button: '{text}'")
                        return True
                    else:
                        logger.debug(f"    Button '{text}' found but not clickable (visible={is_visible}, enabled={is_enabled})")
        except Exception as e:
            logger.debug(f"Button click error for '{text}': {e}")
    return False


class LinkedInScraper(BaseScraper):
    name = "LinkedIn"
    _logged_in = False

    def __init__(self, config):
        super().__init__(config)
        # QA handler injected by applier (set after construction)
        self.qa = None

    async def _login(self, page):
        if self._logged_in:
            return True
        try:
            await page.goto("https://www.linkedin.com/feed/", timeout=30000)
            await asyncio.sleep(3)

            current_url = page.url
            logger.debug(f"LinkedIn login check - URL: {current_url}")

            logged_in_marker = await page.query_selector(
                'a[href*="/jobs/"], '
                'a[data-test-global-nav-link="jobs"], '
                'button[aria-label*="Me"], '
                'img.global-nav__me-photo, '
                '[data-test-global-nav-link="jobs"], '
                '.global-nav__me-photo, '
                '.feed-identity-module'
            )
            logged_out_marker = await page.query_selector(
                'input[name="session_key"], '
                '#session_key, '
                'a[href*="/login"], '
                '.authwall, '
                'main:has-text("Sign in")'
            )

            logger.debug(f"LinkedIn login check - logged_in_marker: {logged_in_marker}, logged_out_marker: {logged_out_marker}")

            # If we're on a feed-like URL and have no obvious logout markers, assume logged in
            if '/feed' in current_url and not logged_out_marker:
                self._logged_in = True
                logger.info("LinkedIn: already logged in (URL check)")
                return True

            # Confirm authenticated session by UI markers, not URL alone.
            if logged_in_marker and not logged_out_marker:
                self._logged_in = True
                logger.info("LinkedIn: already logged in (existing session)")
                return True

            # Fallback: try credential login
            if not self.config.LINKEDIN_EMAIL or not self.config.LINKEDIN_PASSWORD:
                logger.warning("LinkedIn: not logged in and no credentials set.")
                return False

            logger.info("LinkedIn: logging in with credentials...")
            await page.goto("https://www.linkedin.com/login", timeout=30000)
            await asyncio.sleep(2)
            await page.fill('#username', self.config.LINKEDIN_EMAIL)
            await page.fill('#password', self.config.LINKEDIN_PASSWORD)
            await page.click('button[type="submit"]')
            await asyncio.sleep(5)

            logged_in_after = await page.query_selector(
                'a[href*="/jobs/"], '
                'a[data-test-global-nav-link="jobs"], '
                'button[aria-label*="Me"], '
                'img.global-nav__me-photo'
            )
            logged_out_after = await page.query_selector(
                'input[name="session_key"], #session_key, .authwall'
            )
            if logged_in_after and not logged_out_after:
                self._logged_in = True
                logger.info("LinkedIn: logged in via credentials")
                return True
            if "checkpoint" in page.url or "challenge" in page.url:
                logger.warning("LinkedIn: security check required — complete manually then restart")
                return False
            return False
        except Exception as e:
            logger.error(f"LinkedIn login error: {e}")
            return False

    async def scrape(self) -> List[Dict]:
        jobs = []
        page = await self.new_page()
        try:
            if not await self._login(page):
                logger.warning("LinkedIn: skipping scrape (not logged in)")
                return []

            # Bengaluru gets all queries; other locations get subset
            locations = self.config.LOCATIONS
            for loc_idx, location in enumerate(locations):
                loc_encoded = location.replace(' ', '%20')
                queries = SEARCH_QUERIES if loc_idx < 2 else SEARCH_QUERIES[:4]
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

                        # Dismiss any sign-in modal that may overlay the results
                        try:
                            dismiss = await page.query_selector(
                                'button[aria-label="Dismiss"], '
                                'button.modal__dismiss, '
                                '[data-test-modal-close-btn]'
                            )
                            if dismiss:
                                await dismiss.click()
                                await asyncio.sleep(1)
                        except Exception:
                            pass

                        # Scroll to load more cards
                        for _ in range(3):
                            await page.keyboard.press("End")
                            await asyncio.sleep(1.5)

                        # FIX 1: Use data-occludable-job-id — always present in authenticated view
                        cards = await page.query_selector_all('li[data-occludable-job-id]')
                        logger.info(f"LinkedIn '{query}' @ {location}: {len(cards)} cards | url={page.url[:80]}")

                        # Diagnostic: screenshot on 0 cards to see what LinkedIn is showing
                        if len(cards) == 0:
                            try:
                                ss_path = f"logs/linkedin_debug_{query.replace(' ','_')}.png"
                                await page.screenshot(path=ss_path)
                                page_title = await page.title()
                                logger.info(f"  0 cards — page title: '{page_title}' | screenshot: {ss_path}")
                            except Exception:
                                pass
                            continue

                        for card in cards[:20]:
                            try:
                                # Get LinkedIn job ID from attribute — guaranteed unique, never empty
                                li_job_id = await card.get_attribute('data-occludable-job-id')
                                if not li_job_id:
                                    continue

                                # Construct canonical job URL directly from ID
                                href = f"https://www.linkedin.com/jobs/view/{li_job_id}"

                                # Title
                                title_el = await card.query_selector(
                                    'a.job-card-list__title--link, '
                                    '.job-card-list__title, '
                                    'a[href*="/jobs/view/"] strong, '
                                    'strong.job-card-list__title'
                                )
                                if not title_el:
                                    continue
                                title = (await title_el.inner_text()).strip()
                                if not title:
                                    continue

                                # Company
                                company_el = await card.query_selector(
                                    '.job-card-container__company-name, '
                                    '.artdeco-entity-lockup__subtitle span, '
                                    '.job-card-container__primary-description'
                                )
                                company = (await company_el.inner_text()).strip() if company_el else "Unknown"

                                # Location
                                loc_el = await card.query_selector(
                                    '.job-card-container__metadata-item, '
                                    '.job-card__location, '
                                    'li.job-card-container__metadata-item'
                                )
                                job_location = (await loc_el.inner_text()).strip() if loc_el else location

                                # Description — click card to load detail panel
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
                                tags = self._extract_tags(title + " " + query + " " + description)
                                match = score_job(title, description, tags, self.config.TARGET_ROLES)

                                logger.info(f"  Job: {title} @ {company} | id={li_job_id} | score={match}")

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

                    await asyncio.sleep(4)  # rate-limit politely

        finally:
            await page.close()

        # Deduplicate
        seen = set()
        unique = []
        for j in jobs:
            if j["id"] not in seen:
                seen.add(j["id"])
                unique.append(j)
        logger.info(f"LinkedIn total unique jobs: {len(unique)}")
        return unique

    def _extract_tags(self, text: str) -> List[str]:
        keywords = [
            "Python", "AWS", "Docker", "Kubernetes", "FastAPI", "DevOps",
            "ML", "AI", "Gen AI", "Cloud", "Linux", "CI/CD", "Go", "Java",
            "TensorFlow", "MLOps", "Backend", "React", "LangChain",
        ]
        text_lower = text.lower()
        return [kw for kw in keywords if kw.lower() in text_lower]

    async def handle_easy_apply_modal(self, page, job: dict, resume_path: str, cover_letter: str) -> bool:
        """
        Handle LinkedIn Easy Apply modal after the button has been clicked.
        Called by applier.py after it clicks the Easy Apply button.
        """
        try:
            # Wait for modal to appear with proper selector
            modal_selectors = [
                '.jobs-easy-apply-modal',
                '.jobs-apply-modal',
                'div[data-test-modal]',
                'div[role="dialog"][aria-labelledby*="apply"]',
                'div.artdeco-modal--layer-default',
                '.artdeco-modal__content'
            ]
            
            modal = None
            for attempt in range(3):
                for sel in modal_selectors:
                    modal = await page.query_selector(sel)
                    if modal and await modal.is_visible():
                        logger.info(f"Found Easy Apply modal with selector: {sel}")
                        break
                if modal and await modal.is_visible():
                    break
                    
                # If no modal found, try clicking the Easy Apply button again
                if attempt < 2:
                    logger.info(f"Modal not found (attempt {attempt + 1}), retrying click...")
                    apply_btn = await page.query_selector(
                        'button:has-text("Easy Apply"), '
                        'button.jobs-apply-button:has-text("Easy Apply")'
                    )
                    if apply_btn:
                        await apply_btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        try:
                            await apply_btn.evaluate("el => el.click()")
                        except Exception:
                            await apply_btn.click()
                        await asyncio.sleep(2)
            
            if not modal:
                logger.warning(f"Easy Apply modal not found after multiple attempts for: {job.get('title')}")
            
            # Multi-step form loop
            max_steps = 8
            last_clicked = None
            stuck_count = 0
            
            for step in range(max_steps):
                logger.info(f"  Easy Apply step {step + 1}/{max_steps}")

                # Fill phone if empty
                phone_field = await page.query_selector('input[id*="phone"], input[name*="phone"]')
                if phone_field:
                    val = await phone_field.input_value()
                    if not val:
                        await phone_field.fill(self.config.PHONE)
                        logger.info(f"    Filled phone: {self.config.PHONE}")

                # Fill cover letter textarea
                cover_field = await page.query_selector(
                    'textarea[id*="cover"], textarea[placeholder*="cover"], '
                    'textarea[name*="cover"]'
                )
                if cover_field and cover_letter:
                    val = await cover_field.input_value()
                    if not val:
                        await cover_field.fill(cover_letter[:1000])
                        logger.info("    Filled cover letter")

                # Upload resume
                file_input = await page.query_selector('input[type="file"]')
                if file_input and resume_path and Path(resume_path).exists():
                    await file_input.set_input_files(resume_path)
                    await asyncio.sleep(1)
                    logger.info(f"    Uploaded resume: {resume_path}")

                # Handle LinkedIn radio fieldsets
                await self._fill_radio_fieldsets(page)

                # Handle text inputs with labels
                await self._fill_text_inputs(page)

                # Handle dropdowns
                await self._fill_selects(page)
                
                # Check for validation errors
                error_msgs = await page.query_selector_all('.artdeco-inline-feedback--error, [class*="error"], .fb-dash-form-element__error')
                if error_msgs:
                    for err in error_msgs[:3]:
                        try:
                            txt = (await err.inner_text()).strip()
                            if txt:
                                logger.warning(f"    Form error: {txt}")
                        except:
                            pass

                await asyncio.sleep(0.5)

                # Debug: Log available buttons in modal
                if step == 0:
                    buttons = await page.query_selector_all('button')
                    btn_texts = []
                    for b in buttons:
                        try:
                            txt = (await b.inner_text()).strip()[:50]
                            if txt:
                                btn_texts.append(txt)
                        except:
                            pass
                    logger.debug(f"Available buttons: {btn_texts[:10]}")

                # Navigate using span text — how LinkedIn actually renders buttons
                # Check for "Submit application" first
                if await _click_span_text(page, "Submit application", "Submit"):
                    await asyncio.sleep(3)
                    # Check for confirmation / "Done" button
                    if await _click_span_text(page, "Done"):
                        await asyncio.sleep(1)
                    logger.info(f"LinkedIn Easy Apply SUBMITTED: {job['title']} @ {job.get('company')}")
                    return True

                # Try Review → Next → Continue and track what we clicked
                clicked_btn = None
                if await _click_span_text(page, "Review"):
                    clicked_btn = "Review"
                    await asyncio.sleep(1.5)
                elif await _click_span_text(page, "Next", "Continue"):
                    clicked_btn = "Next"
                    await asyncio.sleep(1.5)
                
                if clicked_btn:
                    # Check if stuck clicking same button
                    if clicked_btn == last_clicked:
                        stuck_count += 1
                        if stuck_count >= 3:
                            logger.warning(f"  Stuck clicking '{clicked_btn}' {stuck_count} times - taking screenshot")
                            try:
                                Path("logs").mkdir(exist_ok=True)
                                await page.screenshot(path=f"logs/ea_stuck_{clicked_btn}_{datetime.now().strftime('%H%M%S')}.png")
                            except:
                                pass
                            break
                    else:
                        stuck_count = 0
                    last_clicked = clicked_btn
                    continue

                # No navigable button found — form may be complete or stuck
                # Debug: get all button texts
                all_btns = await page.query_selector_all('button, [role="button"]')
                btn_labels = []
                for b in all_btns:
                    try:
                        txt = (await b.inner_text()).strip().replace('\n', ' ')[:40]
                        if txt:
                            btn_labels.append(txt)
                    except:
                        pass
                logger.info(f"  No navigation button found at step {step + 1}. Buttons: {btn_labels[:8]}")
                
                # Last attempt for submit
                if await _click_span_text(page, "Submit application", "Submit"):
                    await asyncio.sleep(2)
                    return True
                
                # Take screenshot for debugging on handle_easy_apply_modal
                try:
                    Path("logs").mkdir(exist_ok=True)
                    await page.screenshot(path=f"logs/ea_modal_stuck_step{step+1}_{datetime.now().strftime('%H%M%S')}.png")
                    logger.info(f"  Screenshot saved: ea_modal_stuck_step{step+1}")
                except Exception as e:
                    logger.debug(f"  Screenshot error: {e}")
                break

            logger.info(f"Easy Apply did not reach submission for: {job['title']}")
            return False

        except Exception as e:
            logger.error(f"LinkedIn Easy Apply modal error for {job.get('title')}: {e}")
            try:
                Path("logs").mkdir(exist_ok=True)
                await page.screenshot(path=f"logs/ea_modal_error_{datetime.now().strftime('%H%M%S')}.png")
            except:
                pass
            return False

    async def easy_apply(self, page, job: dict, resume_path: str, cover_letter: str) -> bool:
        """
        Attempt LinkedIn Easy Apply. Uses span-text button navigation (how LinkedIn
        actually renders form buttons) and fieldset-based radio question handling.
        Reference: GodsScion/Auto_job_applier_linkedIn
        """
        try:
            # Only navigate if we're not already on the job page
            current_url = page.url
            job_url = job.get("url", "")
            if job_url and job_url not in current_url and "/jobs/view/" not in current_url:
                await page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(2)

            # FIX 2: Correct Easy Apply button selector. 
            # LinkedIn changes aria-labels frequently. Text-based filtering is much safer.
            # Using wait_for_selector because LinkedIn React app loads buttons asynchronously.
            apply_btn = None
            try:
                apply_btn = await page.wait_for_selector(
                    'button:has-text("Easy Apply"), '
                    'button.jobs-apply-button:has-text("Easy Apply")',
                    timeout=7000
                )
            except Exception:
                pass
            
            if not apply_btn:
                # Fallback to checking spans natively
                buttons = await page.query_selector_all('button')
                for b in buttons:
                    inner = (await b.inner_text()).strip()
                    if "Easy Apply" in inner:
                        apply_btn = b
                        break

            if not apply_btn:
                logger.info(f"No Easy Apply button for: {job['title']} @ {job.get('company')}")
                return False

            btn_text = (await apply_btn.inner_text()).strip()
            logger.info(f"Clicking Easy Apply: '{btn_text}' for {job['title']}")
            await apply_btn.click()
            await asyncio.sleep(2)

            # Multi-step form loop
            max_steps = 8
            for step in range(max_steps):
                logger.info(f"  Easy Apply step {step + 1}/{max_steps}")

                # Fill phone if empty
                phone_field = await page.query_selector('input[id*="phone"], input[name*="phone"]')
                if phone_field:
                    val = await phone_field.input_value()
                    if not val:
                        await phone_field.fill(self.config.PHONE)
                        logger.info(f"    Filled phone: {self.config.PHONE}")

                # Fill cover letter textarea
                cover_field = await page.query_selector(
                    'textarea[id*="cover"], textarea[placeholder*="cover"], '
                    'textarea[name*="cover"]'
                )
                if cover_field and cover_letter:
                    val = await cover_field.input_value()
                    if not val:
                        await cover_field.fill(cover_letter[:1000])
                        logger.info("    Filled cover letter")

                # Upload resume
                file_input = await page.query_selector('input[type="file"]')
                if file_input and resume_path and Path(resume_path).exists():
                    await file_input.set_input_files(resume_path)
                    await asyncio.sleep(1)
                    logger.info(f"    Uploaded resume: {resume_path}")

                # FIX 4: Handle LinkedIn radio fieldsets properly
                await self._fill_radio_fieldsets(page)

                # Handle text inputs with labels (years of experience, etc.)
                await self._fill_text_inputs(page)

                # Handle dropdowns
                await self._fill_selects(page)

                await asyncio.sleep(0.5)

                # FIX 3: Navigate using span text — how LinkedIn actually renders buttons
                # Check for "Submit application" first
                if await _click_span_text(page, "Submit application"):
                    await asyncio.sleep(3)
                    # Check for confirmation / "Done" button
                    if await _click_span_text(page, "Done"):
                        await asyncio.sleep(1)
                    logger.info(f"LinkedIn Easy Apply SUBMITTED: {job['title']} @ {job.get('company')}")
                    return True

                # Don't click discard/dismiss modals — skip if present

                # Try Review → Next
                if await _click_span_text(page, "Review"):
                    await asyncio.sleep(1.5)
                    continue

                if await _click_span_text(page, "Next"):
                    await asyncio.sleep(1.5)
                    continue

                # No navigable button found — form may be complete or stuck
                logger.info(f"  No navigation button found at step {step + 1} — checking for submission")
                # Last attempt for submit
                if await _click_span_text(page, "Submit application"):
                    await asyncio.sleep(2)
                    return True
                break

            logger.info(f"Easy Apply did not reach submission for: {job['title']}")
            return False

        except Exception as e:
            logger.error(f"LinkedIn Easy Apply error for {job.get('title')}: {e}")
            try:
                Path("logs").mkdir(exist_ok=True)
                await page.screenshot(path=f"logs/ea_error_{datetime.now().strftime('%H%M%S')}.png")
                logger.info("Screenshot saved to logs/ea_error_*.png for debugging")
            except Exception:
                pass
            return False

    async def _fill_radio_fieldsets(self, page):
        """Fill LinkedIn radio button questions (wrapped in fieldset elements)."""
        if not self.qa:
            return
        try:
            fieldsets = await page.query_selector_all(
                'fieldset[data-test-form-builder-radio-button-form-component="true"]'
            )
            for fieldset in fieldsets:
                try:
                    legend = await fieldset.query_selector('legend span[aria-hidden="true"], legend')
                    question = (await legend.inner_text()).strip() if legend else ""
                    if not question:
                        continue

                    answer = self.qa.get_answer(question)
                    if not answer:
                        logger.info(f"    QA miss (radio): '{question}'")
                        continue

                    options = await fieldset.query_selector_all('label')
                    for opt in options:
                        opt_text = (await opt.inner_text()).strip()
                        if answer.lower() in opt_text.lower() or opt_text.lower() in answer.lower():
                            await opt.click()
                            logger.info(f"    Radio: '{question}' → '{opt_text}'")
                            break
                except Exception:
                    pass
        except Exception:
            pass

    async def _fill_text_inputs(self, page):
        """Fill text input fields using label→input association."""
        if not self.qa:
            return
        try:
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
                    if tag not in ("input", "textarea"):
                        continue
                    input_type = await field.get_attribute("type") or "text"
                    if input_type in ("file", "checkbox", "radio", "hidden", "submit"):
                        continue
                    current_val = await field.input_value()
                    if current_val:
                        continue  # Don't overwrite existing values

                    answer = self.qa.get_answer(text)
                    if answer:
                        # Check if field expects a number but answer is non-numeric
                        if input_type == "number" or "decimal" in text.lower() or "years" in text.lower():
                            # Try to extract or convert to numeric
                            if answer.lower() in ("immediate", "immediately", "asap", "now"):
                                answer = "0"
                            elif not answer.replace(".", "").replace("-", "").isdigit():
                                # Try to extract first number from answer
                                import re
                                nums = re.findall(r'\d+\.?\d*', answer)
                                if nums:
                                    answer = nums[0]
                                else:
                                    answer = "0.5"  # Default fallback
                        await field.fill(answer)
                        logger.info(f"    Text: '{text}' → '{answer[:40]}'")
                except Exception:
                    pass
        except Exception:
            pass

    async def _fill_selects(self, page):
        """Fill dropdown selects using label→select association."""
        if not self.qa:
            return
        try:
            labels = await page.query_selector_all('label')
            for label in labels:
                try:
                    text = (await label.inner_text()).strip()
                    if not text:
                        continue
                    for_attr = await label.get_attribute("for")
                    if not for_attr:
                        continue
                    field = await page.query_selector(f'#{for_attr}')
                    if not field:
                        continue
                    tag = await field.evaluate("el => el.tagName.toLowerCase()")
                    if tag != "select":
                        continue

                    answer = self.qa.get_answer(text)
                    if not answer:
                        continue

                    options = await field.query_selector_all("option")
                    for opt in options:
                        opt_text = (await opt.inner_text()).strip().lower()
                        if answer.lower() in opt_text or opt_text in answer.lower():
                            val = await opt.get_attribute("value")
                            if val:
                                await field.select_option(val)
                                logger.info(f"    Select: '{text}' → '{opt_text}'")
                                break
                except Exception:
                    pass
        except Exception:
            pass
