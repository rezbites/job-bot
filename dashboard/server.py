"""
Local dashboard server — open http://localhost:8080 in your browser.
Shows live job stats, applied jobs, pipeline status.
"""
import asyncio
import json
import logging
from pathlib import Path
from aiohttp import web
from db import JobDatabase
from config import config

logger = logging.getLogger("dashboard")

DASHBOARD_HTML = Path(__file__).parent / "index.html"


class DashboardServer:
    def __init__(self, db: JobDatabase):
        self.db = db
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self._serve_dashboard)
        self.app.router.add_get("/api/stats", self._api_stats)
        self.app.router.add_get("/api/jobs", self._api_jobs)
        self.app.router.add_get("/api/logs", self._api_logs)
        self.app.router.add_post("/api/outcome", self._api_set_outcome)
        self.app.router.add_get("/api/qa", self._api_get_qa)
        self.app.router.add_post("/api/qa", self._api_save_qa)
        self.app.router.add_get("/api/qa/unanswered", self._api_unanswered_qa)
        self.app.router.add_post("/api/qa/delete", self._api_delete_qa)
        self.app.router.add_get("/api/resume/{job_id}", self._api_view_resume)
        self.app.router.add_post("/api/stop", self._api_stop)

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", config.DASHBOARD_PORT)
        await site.start()
        logger.info(f"Dashboard running at http://localhost:{config.DASHBOARD_PORT}")

    async def _serve_dashboard(self, request):
        html = DASHBOARD_HTML.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _api_stats(self, request):
        stats = self.db.get_stats()
        return web.json_response(stats)

    async def _api_jobs(self, request):
        status = request.query.get("status")
        jobs = self.db.get_all(status=status, limit=300)
        for j in jobs:
            if isinstance(j.get("tags"), str):
                try:
                    import json as _json
                    j["tags"] = _json.loads(j["tags"])
                except Exception:
                    j["tags"] = []
        return web.json_response(jobs)

    async def _api_logs(self, request):
        from pathlib import Path
        from datetime import datetime
        log_file = Path("logs") / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
        lines = []
        if log_file.exists():
            text = log_file.read_text(encoding="utf-8", errors="replace")
            lines = text.strip().split("\n")[-100:]  # last 100 lines
        return web.json_response({"lines": lines})

    async def _api_get_qa(self, request):
        answers = self.db.get_all_answers()
        return web.json_response(answers)

    async def _api_save_qa(self, request):
        data = await request.json()
        question = data.get("question", "")
        answer = data.get("answer", "")
        explicit_key = data.get("key", "")
        if question:
            if explicit_key:
                key = explicit_key
            else:
                from qa_handler import _normalize_question
                key = _normalize_question(question)
            self.db.save_answer(key, question, answer)
            # Also persist to JSON file so it survives restarts
            self._persist_qa_to_file()
        return web.json_response({"ok": True})

    async def _api_delete_qa(self, request):
        data = await request.json()
        key = data.get("key", "")
        if key:
            self.db.conn.execute("DELETE FROM qa_answers WHERE question_key=?", (key,))
            self.db.conn.commit()
            self._persist_qa_to_file()
        return web.json_response({"ok": True})

    def _persist_qa_to_file(self):
        """Write all QA answers to JSON file so edits survive bot restarts."""
        import json as _json
        from pathlib import Path
        qa_file = Path("data/qa_answers.json")
        qa_file.parent.mkdir(parents=True, exist_ok=True)
        all_answers = self.db.get_all_answers()
        data = {a["question_key"]: {"question": a["question"], "answer": a["answer"]}
                for a in all_answers}
        qa_file.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    async def _api_unanswered_qa(self, request):
        """Return questions the bot encountered but couldn't answer."""
        rows = self.db.conn.execute(
            "SELECT message FROM logs WHERE level='QA_UNANSWERED' ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        import json as _json
        questions = []
        for r in rows:
            try:
                q = _json.loads(r["message"])
                questions.append(q)
            except Exception:
                pass
        return web.json_response(questions)

    async def _api_view_resume(self, request):
        """Return tailored resume text + PDF path for a specific job."""
        job_id = request.match_info.get("job_id", "")
        if not job_id:
            return web.json_response({"error": "No job_id"}, status=400)
        row = self.db.conn.execute(
            "SELECT title, company, tailored_resume FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not row:
            return web.json_response({"error": "Job not found"}, status=404)
        # Check if a tailored PDF exists
        from pathlib import Path
        safe_name = (row["company"] or "unknown") + "_" + job_id[:8]
        safe_name = safe_name.replace(" ", "_")
        pdf_path = Path("data/tailored_resumes") / f"{safe_name}.pdf"
        return web.json_response({
            "title": row["title"],
            "company": row["company"],
            "resume_text": row["tailored_resume"] or "",
            "pdf_exists": pdf_path.exists(),
            "pdf_path": str(pdf_path) if pdf_path.exists() else "",
        })

    async def _api_stop(self, request):
        """Stop the bot from the dashboard."""
        logger.info("Stop requested from dashboard")
        # Use the global bot instance to stop gracefully
        try:
            from bot import _bot_instance
            if _bot_instance:
                _bot_instance.stop()
        except ImportError:
            pass
        return web.json_response({"ok": True})

    async def _api_set_outcome(self, request):
        data = await request.json()
        job_id = data.get("job_id")
        outcome = data.get("outcome")  # accepted, rejected, interview, ghosted
        notes = data.get("notes", "")
        if job_id and outcome:
            self.db.mark_outcome(job_id, outcome, notes)
        return web.json_response({"ok": True})
