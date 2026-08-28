"""How many hints a student has taken on one problem, counted by the server.

Exists because hints are worth 0.4 of an outcome score and the browser used
to be the one reporting them: POST /work took `hints_used` as a form field,
so a client that posted 0 after three hints inflated every score it earned.
The server already sees each hint request -- this is where it remembers them
until the mark arrives.

Not folded into Attempt: hints happen before there is an attempt to hold
them.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class HintUsage(SQLModel, table=True):
    student_id: str = Field(primary_key=True)
    problem_id: str = Field(primary_key=True)
    count: int = Field(default=0)
