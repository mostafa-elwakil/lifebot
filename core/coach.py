"""Hermes AI Coach: Gemini-backed with offline fallback."""
from __future__ import annotations
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

SYSTEM_PROMPT_PATH_HINT = "config/prompt.py"


def _gemini_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()


class HermesCoach:
    """Tries Gemini API; falls back to rule-based coaching offline."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model_name = model
        self.online = bool(_gemini_key())

    def _gemini_generate(self, prompt: str) -> str | None:
        key = _gemini_key()
        if not key:
            return None
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            model = genai.GenerativeModel(self.model_name)
            resp = model.generate_content(prompt)
            return (resp.text or "").strip() or None
        except Exception:
            return None

    # -- public API --
    def morning_plan(self, todos: list[dict]) -> str:
        p1 = [t["title"] for t in todos if t.get("category") in ("Deep Work", "Scripting") and not t.get("completed")]
        p2 = [t for t in todos if t.get("category") in ("Ops", "Project") and not t.get("completed")]
        p2 = [t["title"] for t in p2]
        p3 = [t["title"] for t in todos if t.get("category") in ("Admin", "Exercise") and not t.get("completed")]
        context = f"Deep:{p1}\nExec:{p2}\nAdmin:{p3}"
        ai = self._gemini_generate(
            f"You are Hermes, a strict productivity coach. Build a morning plan in Arabic/English mix "
            f"from these tasks:\n{context}\nKeep it in 3 phases, actionable, max 150 words."
        )
        if ai:
            return ai
        # offline fallback (same spirit as before, improved)
        def bullets(items, fallback):
            items = items or [fallback]
            return "\n".join(f"- [ ] {t}" for t in items)
        return (
            "### 🎯 Rakez Morning Sequence (Hermes Protocol)\n\n"
            f"**Phase 1 (Fresh Energy / High Friction):**\n{bullets(p1, 'High Cognitive Architecture')}\n\n"
            f"**Phase 2 (Moderate Energy / Execution):**\n{bullets(p2, 'Secondary Implementation')}\n\n"
            f"**Phase 3 (High Continuation Momentum):**\n{bullets(p3, 'Admin & Communications')}\n\n"
            "> **Rule:** Begin Phase 1 before 1:00 PM to avoid the 25 min/hr output decay benchmark!\n"
            "\n_(offline mode — set GEMINI_API_KEY for AI plan)_"
        )

    def resolve_snag(self, excuse: str, todos: list[dict] | None = None) -> str:
        ai = self._gemini_generate(
            f"You are Hermes, strict but empathetic coach. User excuse: '{excuse}'. "
            "Reply in Arabic with: 1) diagnosis in one line, 2) Option A (25-min pomodoro now + 5-min walk), "
            "3) Option B cost (45-60 min lost). Max 120 words."
        )
        if ai:
            return ai
        return (
            "### 🛡️ Snag Negotiation Resolution\n"
            f'**Your Statement:** "{excuse}"\n\n'
            "**Data Diagnosis:**\n"
            "- High-friction tasks suffer continuation drop if aborted.\n"
            "- Unplanned break now → ~71% dropout risk.\n\n"
            "**Your Strict 2 Options:**\n"
            "- **Option A (Data-Backed):** Complete ONE 25-minute Pomodoro right now + 5-min walk.\n"
            "- **Option B (Alternative):** Stop now, forfeit 45-60 min of deep work today.\n"
            "\n_(offline mode — set GEMINI_API_KEY for AI coaching)_"
        )

    def daily_review(self, sessions: list[dict], todos: list[dict]) -> str:
        focus = [s for s in sessions if s.get("kind", "focus") == "focus"]
        mins = sum(int(s.get("duration_min", 0)) for s in focus)
        done = sum(1 for t in todos if t.get("completed"))
        ai = self._gemini_generate(
            f"You are Hermes coach. Stats: {len(focus)} sessions, {mins} minutes, {done}/{len(todos)} tasks done. "
            "Give a 3-line Arabic retrospective: praise/blame + one concrete fix for tomorrow. Max 100 words."
        )
        if ai:
            return ai
        return (
            "### 📊 Daily Retrospective\n"
            f"- Total Focus Sessions: **{len(focus)}**\n"
            f"- Total Deep Work Time: **{mins} Minutes** ({round(mins/60, 1)} Hours)\n"
            f"- Tasks Done: **{done}/{len(todos)}**\n"
            "- Benchmark Target: **100% completion on 20-25 min blocks**.\n"
            "\n_(offline mode — set GEMINI_API_KEY for AI review)_"
        )
