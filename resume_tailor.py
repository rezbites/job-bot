"""
Resume tailoring via Ollama (local, free) or Anthropic API (optional).

Default: Ollama with mistral or llama3 — runs 100% on your machine, no API key needed.
Fallback: Anthropic API if ANTHROPIC_API_KEY is set and USE_ANTHROPIC=true in env.

Install Ollama: https://ollama.com
Then run:  ollama pull mistral   (or llama3, deepseek-r1, etc.)
"""
import logging
import os
import urllib.request
import json
from pathlib import Path

logger = logging.getLogger("tailor")

# ── Config ────────────────────────────────────────────────────────────────────
from config import config

USE_ANTHROPIC = os.getenv("USE_ANTHROPIC", "false").lower() == "true"
ANTHROPIC_API_KEY = config.ANTHROPIC_API_KEY
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")  # or llama3, deepseek-r1, phi3, etc.

RESUME_TEXT = f"""
{config.FULL_NAME} | {config.LOCATION} | {config.PHONE}
{config.EMAIL} | {config.LINKEDIN_URL} | {config.GITHUB_URL}

PROFILE
Software engineering intern with hands-on experience building scalable ML solutions in Python
and cloud-native infrastructure on AWS. Practical exposure to ML model deployment, CI/CD pipelines,
and full-stack development. Strong foundation in managing cloud infrastructure and backend services.

EDUCATION
B.Tech, CSE (AI & Machine Learning) — JSSATE Bangalore (2022–2026)

EXPERIENCE
AI Product Developer Intern — Rooman Technologies (Jan 2026–Present)
• Architected production-grade AWS system using CloudFormation (VPC, ALB, ECS Fargate, RDS PostgreSQL 16,
  ECR, S3, IAM, Secrets Manager, CloudWatch) — one-command environment teardown and recreation.
• Engineered sidecar container architecture on ECS Fargate (REST API + LLM service + NSFW classifier),
  cutting ML microservice latency 60–70% and saving $30–50/month by consolidating 3 tasks into 1.
• Built fully automated CI/CD pipeline (GitHub Actions, 5 sequential jobs): infra validation, testing,
  parallel Docker builds, ECR pushes tagged with git SHA, zero-downtime ECS rolling deployments.
• Implemented self-healing IaC: pipeline auto-creates CloudFormation stack if absent, detects diffs, handles
  in-progress states — no human intervention required.
• Secured secrets via AWS Secrets Manager with least-privilege IAM roles per ECS task; resolved production
  issues across ECS startup, ALB routing, RDS connectivity, and container health via CloudWatch.

Machine Learning Intern — CodexIntern (Jul 2025)
• Built and deployed ML-based backend APIs using Python, Scikit-learn, Flask/FastAPI with automated
  preprocessing pipelines.

PROJECTS
Smart Product Pricing | Python, TensorFlow/Keras, PyTorch, LightGBM (Oct 2025)
• End-to-end pricing intelligence system using multimodal stacking ensemble (structured + text + image).
• Scalable ML pipeline with EfficientNetB0 and DistilBERT; resolved GPU OOM issues.

AI-Powered Wealth Assistant (RAG) | Streamlit, LangChain, Google Gemini API, FAISS (Aug 2025)
• RAG app delivering personalized financial insights using FAISS vector search + LangChain + Gemini API.

Claudus — Goal Roadmap App | React.js, Flask (Jun 2025)
• AI-powered full-stack app for group accountability, roadmap generation, and progress tracking.

TECHNICAL SKILLS
Languages: Python, Go, Java, C
Frameworks: FastAPI, Flask, React (Vite), Streamlit
Databases: PostgreSQL, MongoDB, Redis, SQL
ML/AI: TensorFlow, Scikit-learn, PyTorch, Pandas, NumPy, NLP, LangChain, FAISS
Cloud/DevOps: AWS (ECS, EC2, ECR, IAM, RDS, S3, ALB, CloudFormation, Secrets Manager, CloudWatch),
              Docker, Kubernetes, GitHub Actions, CI/CD, Linux
Monitoring: CloudWatch, Prometheus, Grafana
Tools: Git, GitHub, Postman, Power BI

ACHIEVEMENTS
Amazon ML Challenge 2024 — Top 0.1% nationwide (score: 0.098)
"""


def _call_ollama(prompt: str, max_tokens: int = 1500) -> str:
    """Call local Ollama API. No API key, runs on your machine."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result.get("response", "").strip()


def _call_anthropic(prompt: str, max_tokens: int = 1500) -> str:
    """Call Anthropic API — only used if USE_ANTHROPIC=true."""
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _llm(prompt: str, max_tokens: int = 1500) -> str:
    """Route to Ollama (default) or Anthropic based on env config."""
    if USE_ANTHROPIC and ANTHROPIC_API_KEY:
        logger.debug("Using Anthropic API")
        return _call_anthropic(prompt, max_tokens)
    else:
        logger.debug(f"Using Ollama ({OLLAMA_MODEL})")
        return _call_ollama(prompt, max_tokens)


class ResumeTailor:
    def __init__(self):
        self._cache: dict[str, str] = {}
        backend = "Anthropic API" if (USE_ANTHROPIC and ANTHROPIC_API_KEY) else f"Ollama ({OLLAMA_MODEL})"
        logger.info(f"Resume tailor using: {backend}")

    def tailor(self, job: dict) -> str:
        """Return ATS-optimized resume text for this specific job."""
        cache_key = job.get("id", "")
        if cache_key in self._cache:
            return self._cache[cache_key]

        title = job.get("title", "")
        company = job.get("company", "")
        tags = ", ".join(job.get("tags", []))
        jd = job.get("description", "")

        prompt = f"""You are an expert ATS resume optimizer.

Job Title: {title}
Company: {company}
Key Skills/Tags: {tags}
Job Description:
{jd[:2000]}

Candidate resume:
{RESUME_TEXT}

Task: Rewrite the resume to be maximally ATS-optimized for this specific role.
Rules:
- Mirror keywords from the job description naturally
- Quantify achievements where possible
- Keep ALL facts truthful — do not fabricate anything. Keep the same 2 companies, same projects, same education.
- Use EXACTLY these section headers on their own line in ALL CAPS: PROFILE, EDUCATION, EXPERIENCE, PROJECTS, TECHNICAL SKILLS, ACHIEVEMENTS
- First line must be: {config.FULL_NAME}
- Second line: {config.LOCATION} | {config.PHONE} | {config.EMAIL} | {config.LINKEDIN_URL} | {config.GITHUB_URL}
- Bullet points start with - (dash)
- For Experience: company name and role on separate lines, then bullet points
- For Skills: use format like "Languages: Python, C, Java, Go"
- Output plain text only, no markdown, no asterisks, no bold markers
- Keep it concise — must fit 1 page
"""
        try:
            tailored = _llm(prompt, max_tokens=1500)
            self._cache[cache_key] = tailored
            logger.info(f"Resume tailored for: {title} @ {company}")
            return tailored
        except Exception as e:
            logger.error(f"Resume tailor error: {e}")
            return RESUME_TEXT  # fallback to original

    def tailor_to_pdf(self, job: dict) -> str:
        """Generate a tailored resume as a professional 1-page PDF matching original style.
        Original resume in resume/ is NEVER modified."""
        from fpdf import FPDF

        tailored_text = self.tailor(job)
        out_dir = Path("data/tailored_resumes")
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = (job.get("company", "unknown") + "_" + job.get("id", "x")[:8]).replace(" ", "_")
        pdf_path = out_dir / f"{safe_name}.pdf"

        # Section headers to detect (match original resume structure)
        SECTION_HEADERS = {"PROFILE", "EDUCATION", "EXPERIENCE", "PROJECTS",
                           "TECHNICAL SKILLS", "SKILLS", "ACHIEVEMENTS", "CERTIFICATIONS"}

        def _is_section_header(line: str) -> bool:
            return line.strip().upper() in SECTION_HEADERS

        def _is_bullet(line: str) -> bool:
            s = line.strip()
            return s.startswith("-") or s.startswith("--") or s.startswith("*")

        def _build_pdf(text: str, scale: float = 1.0) -> FPDF:
            # Font sizes scaled to fit
            NAME_SZ = max(6, 18 * scale)
            SUBTITLE_SZ = max(5, 9 * scale)
            SECTION_SZ = max(5.5, 10.5 * scale)
            BODY_SZ = max(5, 9.5 * scale)
            BOLD_SZ = max(5, 9.5 * scale)
            LINE_H = max(3, 4.2 * scale)
            MARGIN = 15

            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=False)
            pdf.set_left_margin(MARGIN)
            pdf.set_right_margin(MARGIN)
            pdf.set_top_margin(12)
            usable = 210 - 2 * MARGIN

            lines = text.split("\n")
            i = 0

            # --- Header: Name (large, centered) ---
            # First non-empty line is the name
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                name = lines[i].strip()
                pdf.set_font("Helvetica", "B", NAME_SZ)
                pdf.cell(0, NAME_SZ * 0.5, name.upper(), align="C",
                         new_x="LMARGIN", new_y="NEXT")
                # Draw a thin line under name
                y = pdf.get_y() + 1
                pdf.line(MARGIN, y, 210 - MARGIN, y)
                pdf.set_y(y + 1.5)
                i += 1

            # --- Contact line(s): small, centered ---
            pdf.set_font("Helvetica", size=SUBTITLE_SZ)
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue
                # Contact info lines (contain email, phone, github, linkedin)
                if any(kw in line.lower() for kw in ["@", "+91", "github", "linkedin", "bengaluru", "karnataka"]):
                    pdf.cell(0, LINE_H, line, align="C",
                             new_x="LMARGIN", new_y="NEXT")
                    i += 1
                else:
                    break

            pdf.ln(1)

            # --- Body sections ---
            while i < len(lines):
                line = lines[i].strip()
                i += 1

                if not line:
                    pdf.ln(1)
                    continue

                # Section header (PROFILE, EXPERIENCE, etc.)
                if _is_section_header(line):
                    pdf.ln(1.5)
                    pdf.set_font("Helvetica", "B", SECTION_SZ)
                    pdf.cell(0, LINE_H + 1, line.upper(),
                             new_x="LMARGIN", new_y="NEXT")
                    # Draw underline
                    y = pdf.get_y()
                    pdf.line(MARGIN, y, 210 - MARGIN, y)
                    pdf.set_y(y + 1.5)
                    pdf.set_font("Helvetica", size=BODY_SZ)
                    continue

                # Bullet points (start with - or *)
                if _is_bullet(line):
                    bullet_text = line.lstrip("-*").strip()
                    pdf.set_font("Helvetica", size=BODY_SZ)
                    # Use dash prefix like original resume
                    pdf.set_x(MARGIN + 3)
                    pdf.multi_cell(usable - 3, LINE_H,
                                   "-- " + bullet_text)
                    continue

                # Bold lines: company names, project names, job titles
                # Detect: lines with dates (20XX) or lines that are short and capitalized
                has_date = any(f"20{y}" in line for y in range(20, 30))
                # Skills lines with colons (Languages: ..., Tools: ...)
                if ":" in line and not has_date:
                    parts = line.split(":", 1)
                    pdf.set_font("Helvetica", "B", BOLD_SZ)
                    label_w = pdf.get_string_width(parts[0] + ":") + 2
                    pdf.cell(label_w, LINE_H, parts[0] + ":")
                    pdf.set_font("Helvetica", size=BODY_SZ)
                    pdf.multi_cell(0, LINE_H, parts[1].strip())
                    continue

                if has_date or (len(line) < 80 and not line.endswith(".")):
                    # Likely a company/project/title line — bold it
                    pdf.set_font("Helvetica", "B", BOLD_SZ)
                    pdf.multi_cell(0, LINE_H, line)
                    pdf.set_font("Helvetica", size=BODY_SZ)
                    continue

                # Regular text
                pdf.set_font("Helvetica", size=BODY_SZ)
                pdf.multi_cell(0, LINE_H, line)

            return pdf

        # Try progressively smaller scales to fit one page
        final_pdf = None
        for scale in [1.0, 0.93, 0.87, 0.82, 0.77, 0.72]:
            pdf = _build_pdf(tailored_text, scale)
            if pdf.page_no() == 1:
                final_pdf = pdf
                break
            final_pdf = pdf  # keep last attempt

        if final_pdf is None:
            final_pdf = _build_pdf(tailored_text, 0.72)

        # Last resort: if still multi-page, remove Claudus project
        if final_pdf.page_no() > 1 and ("claudus" in tailored_text.lower()):
            lines = tailored_text.split("\n")
            filtered = []
            skip = False
            for ln in lines:
                if "claudus" in ln.lower():
                    skip = True
                    continue
                if skip and (ln.strip() == "" or _is_bullet(ln)):
                    continue
                skip = False
                filtered.append(ln)
            final_pdf = _build_pdf("\n".join(filtered), 0.77)

        final_pdf.output(str(pdf_path))
        logger.info(f"Tailored 1-page PDF saved: {pdf_path}")
        return str(pdf_path)

    def generate_cover_letter(self, job: dict) -> str:
        """Generate a short, compelling cover letter."""
        prompt = f"""Write a concise 3-paragraph cover letter for this job application.

Role: {job.get('title')} at {job.get('company')}
Location: {job.get('location', 'Bengaluru')}
Skills required: {', '.join(job.get('tags', []))}

Applicant: {config.FULL_NAME}
LinkedIn: {config.LINKEDIN_URL}
Background: B.Tech CSE (AI/ML) at JSSATE Bangalore (graduating 2026)
Key experience: AWS ECS/Fargate, CI/CD pipelines, ML model deployment, Python, DevOps
Achievement: Amazon ML Challenge Top 0.1% nationwide

Rules:
- Keep it under 200 words
- Be specific and genuine — no generic fluff
- Plain text only, no markdown
"""
        try:
            return _llm(prompt, max_tokens=400)
        except Exception as e:
            logger.error(f"Cover letter error: {e}")
            return ""
