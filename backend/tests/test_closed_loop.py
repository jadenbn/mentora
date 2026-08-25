"""The loop, end to end at the service layer, with no provider call.

select_next -> render request -> generate (stubbed workflow) -> tag with
problem_skills -> grade -> record_attempt, asserting that mastery for the
skill selection actually chose moves in the right direction, and that the
skills came from the server, not the client payload.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.api.learning import _render_question_request
from app.database import CourseRepository
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import QuestionPlan
from app.services import selection, student_model_service
from app.services.attempt_grading import to_attempt_grading
from app.schemas.learning import AttemptCreate
from app.schemas.tutor import WorkStatus
from app.services.question_service import QuestionService


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class _StubWorkflow:
    def __init__(self, chunk_id: str) -> None:
        self._chunk_id = chunk_id

    async def run(
        self, *, chunks, question_request: str, existing_skills=None
    ) -> QuestionPlan:
        assert chunks  # generate handed us grounding context
        # No skill is proposed here — the test proves attribution comes from
        # required_skill_id (what selection chose), not from the model.
        return QuestionPlan(
            prompt=f"Generated from request: {question_request}",
            grounding_chunk_ids=[self._chunk_id],
            skills=[
                {
                    "id": "unrelated-skill",
                    "name": "Unrelated",
                    "description": "Not the selected skill.",
                    "difficulty_band": 0.5,
                }
            ],
        )


def _seed_document(repo: CourseRepository) -> str:
    chunk = ChunkMetadata(
        chunk_id="chunk_doc_1_00000",
        course_id="calc1",
        document_id="doc_1",
        chunk_index=0,
        filename="book.pdf",
        page=1,
        document_type=DocumentType.lecture,
        text="The chain rule differentiates a composite function f(g(x)).",
    )
    repo.replace_document(
        document_id="doc_1",
        course_id="calc1",
        filename="book.pdf",
        document_type=DocumentType.lecture,
        total_pages=1,
        chunks=[chunk],
    )
    return chunk.chunk_id


@pytest.mark.asyncio
async def test_select_generate_tag_grade_record_moves_the_selected_skill(
    session, tmp_path
):
    session.add(
        Skill(
            id="calc1.derivatives.chain-rule",
            course_id="calc1",
            name="Chain rule",
            description="Differentiating a composition f(g(x)).",
            difficulty_band=0.5,
            prereqs=[],
            keywords=["composite function", "outer derivative"],
            question_forms=["differentiate a nested expression"],
        )
    )
    session.commit()

    repo = CourseRepository(tmp_path / "mentora.db")
    chunk_id = _seed_document(repo)

    # 1. Select.
    spec = selection.select_next(session, "calc1", "stu1")
    assert spec is not None
    assert spec.skill_id == "calc1.derivatives.chain-rule"
    assert spec.retrieval_query  # assembled from name/description/keywords

    # 2 + 3. Generate against the course document with a request from the spec.
    #    The stub workflow proposes an unrelated skill of its own, to prove
    #    required_skill_id still forces the selected skill's inclusion.
    service = QuestionService(
        repository=repo,
        workflow=_StubWorkflow(chunk_id),
        retriever=None,  # small context -> full, retriever unused
        full_context_max_chars=10_000,
        session=session,
    )
    problem = await service.generate(
        course_id="calc1",
        document_id="doc_1",
        question_request=_render_question_request(spec),
        required_skill_id=spec.skill_id,
    )

    # 4. Attribution already happened inside generate(), server-side.
    attributed = repo.get_problem_skills(problem.id)
    assert "calc1.derivatives.chain-rule" in attributed
    assert "calc1.unrelated-skill" in attributed

    # 5. Grade a correct attempt. The client lies about which skill it was;
    #    the server must ignore that and use problem_skills.
    grading = to_attempt_grading(WorkStatus.correct, repo.get_problem_skills(problem.id))
    assert grading is not None
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id=problem.id,
        expected_skills=["calc1.some.other.skill"],  # a lie
        difficulty=spec.target_difficulty,
        correct=grading.correct,
        partial=grading.partial,
        errors=grading.errors,
    )
    result = student_model_service.record_attempt(
        session, "calc1", payload, repository=repo
    )

    # Mastery moved for the *selected* skill, not the one the client named.
    assert "calc1.derivatives.chain-rule" in result.updated_skills
    state = session.get(SkillState, ("stu1", "calc1.derivatives.chain-rule"))
    assert state is not None
    assert state.mastery > 0.5  # a correct attempt raised it from the cold-start seed
