"""
Q&A handler for job application forms.

Maintains a local database of question → answer mappings.
When a new question is encountered, it logs it for the user to answer
via the dashboard. Uses fuzzy matching to reuse answers for similar questions.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional
from db import JobDatabase

logger = logging.getLogger("qa")

# Pre-seeded answers file — user fills this in once, bot uses forever
QA_FILE = Path("data/qa_answers.json")

# Common patterns and their normalized keys (regex-based, checked first)
QUESTION_PATTERNS = {
    # Experience
    r"(years?|yrs?)\s*(of)?\s*(total\s*)?(work\s*)?(experience|exp)": "years_of_experience",
    r"how\s*(many|much)\s*(years?|yrs?)?\s*(of)?\s*(experience|exp)": "years_of_experience",
    r"total\s*(work)?\s*(experience|exp)": "years_of_experience",
    r"relevant\s*(work)?\s*(experience|exp)": "years_of_experience",
    r"professional\s*experience": "years_of_experience",
    # Salary / CTC
    r"current\s*(ctc|salary|compensation|package|pay)": "current_ctc",
    r"(present|existing)\s*(ctc|salary|compensation)": "current_ctc",
    r"(expected|desired|asking)\s*(ctc|salary|compensation|package|pay)": "expected_ctc",
    r"salary\s*(expectation|requirement)": "expected_ctc",
    r"what\s*(ctc|salary|compensation).*expect": "expected_ctc",
    r"what\s*(ctc|salary|compensation).*current": "current_ctc",
    # Notice period
    r"notice\s*period": "notice_period",
    r"(how\s*(soon|quickly)|when)\s*(can\s*(you|u)\s*)?(join|start|available)": "earliest_start_date",
    r"(earliest|available)\s*(start|join|joining)\s*(date)?": "earliest_start_date",
    r"date\s*of\s*(joining|availability)": "earliest_start_date",
    # Relocation
    r"(willing|open|ready)\s*(to)?\s*relocat": "willing_to_relocate",
    r"relocat(e|ion)": "willing_to_relocate",
    # Work auth
    r"(work|employment)\s*(authorization|authorisation|permit|eligibility)": "work_authorization",
    r"(legally|authorized|authorised)\s*(to)?\s*(work|employed)": "work_authorization",
    r"(right|eligible)\s*to\s*work": "work_authorization",
    # Visa
    r"(require|need)\s*(visa|sponsorship|work\s*permit)": "visa_sponsorship",
    r"(visa|sponsorship)\s*(require|need|status)": "visa_sponsorship",
    # Gender
    r"gender|sex\b|pronoun": "gender",
    # URLs
    r"linked\s*in\s*(url|profile|link|handle)?": "linkedin_url",
    r"github\s*(url|profile|link|handle|username)?": "github_url",
    r"portfolio\s*(url|website|link|site)?": "portfolio_url",
    r"personal\s*(website|site|url|page)": "portfolio_url",
    # Education
    r"(highest|latest|recent|last)\s*(degree|education|qualification)": "highest_education",
    r"(educational|academic)\s*(background|qualification)": "highest_education",
    r"(college|university|institute|institution|school)\s*(name)?": "college_name",
    r"(where|which)\s*(did\s*(you|u)\s*)?(study|graduate|attend)": "college_name",
    r"(graduation|grad|passing)\s*(year|date|batch)": "graduation_year",
    r"(year|batch)\s*(of)?\s*(graduation|passing|completion)": "graduation_year",
    # Location
    r"(current|present)\s*(city|location|address|place)": "current_location",
    r"(where|city|location).*based": "current_location",
    r"(residing|reside|live|living)\s*(in|at)?": "current_location",
    # Phone
    r"(phone|mobile|cell|contact|telephone)\s*(number|no\.?)?": "phone_number",
    # Work mode
    r"(willing|open|prefer)\s*(to)?\s*(work\s*)?(from\s*)?(office|home|remote|hybrid|onsite|on-site|wfh|wfo)": "work_mode_preference",
    r"(remote|hybrid|onsite|on-site|wfh|wfo)\s*(work|preference|ok|okay|fine)": "work_mode_preference",
    # Cover letter
    r"cover\s*letter": "cover_letter",
    # Motivation
    r"why\s*(do\s*(you|u)\s*)?(want|interested|apply|join|this|choose)": "why_this_role",
    r"what\s*(attract|interest|excite|motivat)": "why_this_role",
    # About
    r"(describe|tell|about)\s*(yourself|you|us about|me about)": "about_yourself",
    r"(brief|short)\s*(introduction|intro|summary|about)": "about_yourself",
    # Skills
    r"(key\s*)?(strengths|skills|competenc|expertise)": "key_strengths",
    r"(technical|core)\s*(skills|expertise|proficienc)": "key_strengths",
    # Current company / role
    r"(current|present|latest)\s*(company|employer|organization|organisation)": "current_company",
    r"(which|what)\s*(company|org).*?(currently|presently|now|working)": "current_company",
    r"(where|which)\s*(are\s*(you|u)\s*)?(working|employed)": "current_company",
    r"(current|present|latest)\s*(designation|role|title|position|job\s*title)": "current_designation",
    r"(previous|last|former)\s*(company|employer)": "previous_company",
    r"(how\s*many|number\s*of)\s*(companies|employers|organizations)": "number_of_companies",
}

# Secondary fuzzy matching: keyword sets mapped to answer keys
# If regex fails, we check word overlap with these keyword bags
_FUZZY_MAP = {
    "years_of_experience": {"experience", "years", "yrs", "total", "work", "professional", "exp"},
    "current_ctc": {"current", "ctc", "salary", "present", "compensation", "existing", "package"},
    "expected_ctc": {"expected", "desired", "ctc", "salary", "expectation", "asking", "package"},
    "notice_period": {"notice", "period", "serving"},
    "earliest_start_date": {"start", "join", "joining", "available", "availability", "earliest", "date", "when"},
    "willing_to_relocate": {"relocate", "relocation", "willing", "move", "shift"},
    "work_authorization": {"authorized", "authorization", "legally", "eligible", "right", "work", "permit"},
    "visa_sponsorship": {"visa", "sponsorship", "sponsor", "permit", "require"},
    "gender": {"gender", "sex"},
    "linkedin_url": {"linkedin", "profile", "url", "link"},
    "github_url": {"github", "profile", "url", "link", "repo"},
    "portfolio_url": {"portfolio", "website", "personal", "site"},
    "highest_education": {"education", "degree", "qualification", "highest", "academic"},
    "college_name": {"college", "university", "institute", "school", "institution"},
    "graduation_year": {"graduation", "year", "batch", "passing", "grad"},
    "current_location": {"city", "location", "current", "based", "residing", "live"},
    "phone_number": {"phone", "mobile", "contact", "number", "cell"},
    "work_mode_preference": {"remote", "hybrid", "onsite", "office", "home", "wfh", "wfo"},
    "why_this_role": {"why", "interested", "motivation", "apply", "join", "attract"},
    "about_yourself": {"yourself", "about", "tell", "describe", "introduction", "summary"},
    "key_strengths": {"strengths", "skills", "expertise", "technical", "competencies"},
    "current_company": {"current", "present", "company", "employer", "organization"},
    "current_designation": {"current", "present", "designation", "role", "title", "position"},
    "previous_company": {"previous", "last", "former", "company", "employer"},
    "number_of_companies": {"how", "many", "number", "companies", "employers", "worked"},
    "about_yourself": {"yourself", "about", "tell", "describe", "introduction", "summary", "brief"},
    "why_this_role": {"why", "interested", "motivation", "apply", "join", "attract", "want", "role"},
}


def _normalize_question(question: str) -> str:
    """Match a question to a known answer key using regex + fuzzy word overlap."""
    q_lower = question.lower().strip()

    # 1. Try exact regex patterns first
    for pattern, key in QUESTION_PATTERNS.items():
        if re.search(pattern, q_lower):
            return key

    # 2. Fuzzy word-overlap matching
    q_words = set(re.findall(r'[a-z]+', q_lower))
    best_key = None
    best_score = 0
    for key, keywords in _FUZZY_MAP.items():
        overlap = len(q_words & keywords)
        if overlap > best_score and overlap >= 2:  # need at least 2 keyword matches
            best_score = overlap
            best_key = key
    if best_key:
        return best_key

    # 3. Fallback: slugify the question
    slug = re.sub(r'[^a-z0-9]+', '_', q_lower)[:80].strip('_')
    return slug


class QAHandler:
    def __init__(self, db: JobDatabase):
        self.db = db
        self._load_from_file()

    def _load_from_file(self):
        """Load pre-seeded answers from JSON file if it exists."""
        if QA_FILE.exists():
            try:
                data = json.loads(QA_FILE.read_text(encoding="utf-8"))
                for key, val in data.items():
                    if isinstance(val, dict):
                        self.db.save_answer(key, val.get("question", key), val.get("answer", ""))
                    else:
                        self.db.save_answer(key, key, str(val))
                logger.info(f"Loaded {len(data)} pre-seeded QA answers from {QA_FILE}")
            except Exception as e:
                logger.error(f"Error loading QA file: {e}")

    def get_answer(self, question: str) -> Optional[str]:
        """Look up an answer for a given question. Returns None if unknown."""
        key = _normalize_question(question)
        answer = self.db.get_answer(key)
        if answer:
            logger.debug(f"QA hit: '{question}' -> key '{key}'")
            return answer

        # Try LLM fallback — give it all known answers + resume and ask it to answer
        llm_answer = self._ask_llm(question)
        if llm_answer:
            # Save for future reuse so we don't call LLM again for the same question
            self.db.save_answer(key, question, llm_answer)
            self._persist_to_file()
            logger.info(f"QA LLM answered: '{question}' -> '{llm_answer[:60]}...'")
            return llm_answer

        # Log as unanswered for user to fill in
        logger.info(f"QA miss — unknown question: '{question}' (key: {key})")
        self.db.log("QA_UNANSWERED", json.dumps({"key": key, "question": question}))
        return None

    def _ask_llm(self, question: str) -> Optional[str]:
        """Use Ollama (local LLM) to answer a form question using resume + known answers."""
        try:
            from resume_tailor import RESUME_TEXT, _llm
        except ImportError:
            return None

        # Build context from all known answers
        known = self.db.get_all_answers()
        qa_context = "\n".join(f"Q: {a['question']} -> A: {a['answer']}" for a in known if a['answer'])

        prompt = f"""You are filling out a job application form for Shashank Choudhary.
Answer the following question concisely and accurately using ONLY the information below.
If the information is not available, respond with exactly: UNKNOWN

Candidate resume:
{RESUME_TEXT}

Known answers:
{qa_context}

Question: {question}

Rules:
- Answer in 1-2 sentences max, or a single value if it's a simple field
- Be factual — NEVER fabricate information not present in the resume or known answers
- For yes/no questions, answer Yes or No
- For numeric questions, answer with just the number
- Plain text only, no markdown

Answer:"""

        try:
            answer = _llm(prompt, max_tokens=150).strip()
            # Reject if LLM says it doesn't know
            if not answer or "UNKNOWN" in answer.upper() or "not available" in answer.lower() or "not mentioned" in answer.lower():
                return None
            return answer
        except Exception as e:
            logger.debug(f"QA LLM error: {e}")
            return None

    def save_answer(self, question: str, answer: str):
        """Save a new answer (from user input via dashboard)."""
        key = _normalize_question(question)
        self.db.save_answer(key, question, answer)
        logger.info(f"QA saved: '{key}' = '{answer[:50]}...'")
        self._persist_to_file()

    def _persist_to_file(self):
        """Write all answers back to the JSON file for backup."""
        QA_FILE.parent.mkdir(parents=True, exist_ok=True)
        all_answers = self.db.get_all_answers()
        data = {a["question_key"]: {"question": a["question"], "answer": a["answer"]}
                for a in all_answers}
        QA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
