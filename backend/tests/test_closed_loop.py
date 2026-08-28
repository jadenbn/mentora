"""The loop, end to end at the service layer, with no provider call.

pick_topic -> generate (stubbed workflow) -> tag with ProblemSkill rows ->
grade -> record_attempt, asserting that accuracy for the topic selection
actually chose moves in the right direction, and that the skills came from
the server, not the client payload.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.database import CourseRepository
from app.models.skill import Skill
from app.engine.models.skill_state import SkillState
from app.schemas.documents import ChunkMetadata, DocumentType
from app.engine.schemas import AttemptCreate
from app.schemas.problems import QuestionPlan
from app.services import attribution
from app.engine import selection, student_model_service
from app.engine.accuracy import observed_accuracy
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
        # The model names a skill the course doesn't have. This proves two
        # things at once: required_skill_id still forces the selected topic's
        # inclusion, and the model's own read is additive, not a replacement.
        return QuestionPlan(
            prompt=f"Generated from request: {question_request}",
            grounding_chunk_ids=[self._chunk_id],
            skills=[
                {
                    "id": "unrelated-skill",
                    "name": "Unrelated",
                    "description": "Not the selected topic.",
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
async def test_pick_generate_tag_grade_record_moves_the_selected_topic(
    session, tmp_path
):
    session.add(
        Skill(
            id="calc1.derivatives.chain-rule",
            course_id="calc1",
            name="Chain rule",
            description="Differentiating a composition f(g(x)).",
            difficulty_band=0.5,
            keywords=["composite function", "outer derivative"],
            question_forms=["differentiate a nested expression"],
        )
    )
    session.commit()

    repo = CourseRepository(tmp_path / "mentora.db")
    chunk_id = _seed_document(repo)

    # 1. Pick a topic.
    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic is not None
    assert topic.skill_id == "calc1.derivatives.chain-rule"

    # 2 + 3. Generate against the course document with a request built from
    #    the topic. The stub workflow names an unrelated skill of its own, to
    #    prove required_skill_id still forces the selected topic's inclusion.
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
        question_request=f"Write a question on {topic.skill_name}: {topic.skill_description}",
        required_skill_id=topic.skill_id,
    )

    # 4. Attribution already happened inside generate(), server-side. The
    #    stub's own topic is genuinely new, so it was created via the same
    #    piggyback path a real model call takes -- both topics are attributed.
    attributed = set(attribution.get_problem_skills(session, problem.id))
    assert attributed == {"calc1.derivatives.chain-rule", "calc1.unrelated-skill"}
    assert session.get(Skill, "calc1.unrelated-skill") is not None

    # 5. Grade a correct attempt. The client lies about which skill it was;
    #    the server must ignore that and use the server-side attribution.
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id=problem.id,
        expected_skills=["calc1.some.other.skill"],  # a lie
        difficulty=topic.target_difficulty,
        correct=True,
    )
    result = student_model_service.record_attempt(session, "calc1", payload)

    # Accuracy moved for the *selected* topic, not the one the client named.
    assert "calc1.derivatives.chain-rule" in result.updated_skills
    state = session.get(SkillState, ("stu1", "calc1.derivatives.chain-rule"))
    assert state is not None
    assert observed_accuracy(state.recent_outcomes) == pytest.approx(1.0)
