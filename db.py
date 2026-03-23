"""
Job tracking database — SQLite, stored locally.
"""
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("db")

DB_PATH = Path("data/jobs.db")
DB_PATH.parent.mkdir(exist_ok=True)


class JobDatabase:
    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.info(f"Database initialized at {DB_PATH}")

    def _init_schema(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            company     TEXT NOT NULL,
            location    TEXT,
            salary      TEXT,
            platform    TEXT,
            url         TEXT,
            description TEXT,
            tags        TEXT,
            match_score INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'found',
            applied_at  TEXT,
            replied_at  TEXT,
            outcome     TEXT,
            notes       TEXT,
            tailored_resume TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date        TEXT PRIMARY KEY,
            found       INTEGER DEFAULT 0,
            applied     INTEGER DEFAULT 0,
            replied     INTEGER DEFAULT 0,
            accepted    INTEGER DEFAULT 0,
            rejected    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            level       TEXT,
            message     TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS discovered_careers (
            company     TEXT PRIMARY KEY,
            url         TEXT NOT NULL,
            source      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS qa_answers (
            question_key TEXT PRIMARY KEY,
            question     TEXT NOT NULL,
            answer       TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        """)
        self.conn.commit()

    # ── Job CRUD ──────────────────────────────────────────────────────────────

    def upsert_job(self, job: dict) -> bool:
        """Insert or update job. Returns True if new."""
        existing = self.conn.execute(
            "SELECT id, status FROM jobs WHERE id = ?", (job["id"],)
        ).fetchone()

        if existing:
            return False

        self.conn.execute("""
            INSERT INTO jobs (id, title, company, location, salary, platform, url,
                              description, tags, match_score, status)
            VALUES (:id, :title, :company, :location, :salary, :platform, :url,
                    :description, :tags, :match_score, 'found')
        """, {
            "id": job["id"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "salary": job.get("salary", ""),
            "platform": job.get("platform", ""),
            "url": job.get("url", ""),
            "description": job.get("description", "")[:5000],  # cap size
            "tags": json.dumps(job.get("tags", [])),
            "match_score": job.get("match_score", 0),
        })
        self.conn.commit()
        self._bump_stat("found")
        return True

    def mark_applied(self, job_id: str, tailored_resume: str = ""):
        self.conn.execute("""
            UPDATE jobs SET status='applied', applied_at=datetime('now'),
                            tailored_resume=? WHERE id=?
        """, (tailored_resume, job_id))
        self.conn.commit()
        self._bump_stat("applied")
        logger.info(f"Marked applied: {job_id}")

    def mark_replied(self, job_id: str, outcome: str = ""):
        self.conn.execute("""
            UPDATE jobs SET status='replied', replied_at=datetime('now'),
                            outcome=? WHERE id=?
        """, (outcome, job_id))
        self.conn.commit()
        self._bump_stat("replied")

    def mark_outcome(self, job_id: str, outcome: str, notes: str = ""):
        """outcome: 'accepted' | 'rejected' | 'interview' | 'ghosted'"""
        self.conn.execute("""
            UPDATE jobs SET status=?, outcome=?, notes=? WHERE id=?
        """, (outcome, outcome, notes, job_id))
        self.conn.commit()
        if outcome in ("accepted", "rejected"):
            self._bump_stat(outcome)

    def filter_new(self, jobs: List[dict]) -> List[dict]:
        """Return only jobs not yet in DB."""
        new = []
        for j in jobs:
            if self.upsert_job(j):
                new.append(j)
        return new

    # ── Query helpers ──────────────────────────────────────────────────────────

    def get_all(self, status: Optional[str] = None, limit: int = 200) -> List[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT * FROM daily_stats WHERE date=?", (today,)
        ).fetchone()
        totals = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='applied' THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN status='replied' THEN 1 ELSE 0 END) as replied,
                SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN status='interview' THEN 1 ELSE 0 END) as interview
            FROM jobs
        """).fetchone()
        return {
            "today": dict(row) if row else {},
            "all_time": dict(totals) if totals else {},
        }

    def _bump_stat(self, col: str):
        today = datetime.now().strftime("%Y-%m-%d")
        self.conn.execute(f"""
            INSERT INTO daily_stats (date, {col}) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET {col} = {col} + 1
        """, (today,))
        self.conn.commit()

    # ── Discovered career pages ─────────────────────────────────────────────

    def add_career_page(self, company: str, url: str, source: str = ""):
        """Add a newly discovered company career page."""
        self.conn.execute("""
            INSERT OR IGNORE INTO discovered_careers (company, url, source)
            VALUES (?, ?, ?)
        """, (company, url, source))
        self.conn.commit()

    def get_career_pages(self) -> List[dict]:
        rows = self.conn.execute("SELECT company, url FROM discovered_careers").fetchall()
        return [{"name": r["company"], "url": r["url"]} for r in rows]

    # ── Q&A answers for application forms ──────────────────────────────────

    def save_answer(self, question_key: str, question: str, answer: str):
        """Save an answer for a common application question."""
        self.conn.execute("""
            INSERT INTO qa_answers (question_key, question, answer)
            VALUES (?, ?, ?)
            ON CONFLICT(question_key) DO UPDATE SET answer=?, question=?
        """, (question_key, question, answer, answer, question))
        self.conn.commit()

    def get_answer(self, question_key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT answer FROM qa_answers WHERE question_key=?", (question_key,)
        ).fetchone()
        return row["answer"] if row else None

    def get_all_answers(self) -> List[dict]:
        rows = self.conn.execute("SELECT question_key, question, answer FROM qa_answers").fetchall()
        return [dict(r) for r in rows]

    def log(self, level: str, message: str):
        self.conn.execute(
            "INSERT INTO logs (level, message) VALUES (?, ?)", (level, message)
        )
        self.conn.commit()
