"""Server-side hint counting.

A hint costs 0.4 of an outcome score, so whoever counts hints decides part
of the grade. That used to be the browser, on a form field POST /work
accepted at face value. It is the server now: every hint request against a
problem increments the count here, and grading reads it back.
"""

from __future__ import annotations

from sqlmodel import Session

from app.models.hint_usage import HintUsage


def record_hint(session: Session, student_id: str, problem_id: str) -> int:
    """Count one hint request. Returns the new total."""
    usage = session.get(HintUsage, (student_id, problem_id))
    if usage is None:
        usage = HintUsage(student_id=student_id, problem_id=problem_id, count=0)
    usage.count += 1
    session.add(usage)
    session.commit()
    return usage.count


def hints_taken(session: Session, student_id: str, problem_id: str) -> int:
    usage = session.get(HintUsage, (student_id, problem_id))
    return usage.count if usage else 0
