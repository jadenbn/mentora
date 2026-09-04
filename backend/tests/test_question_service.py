from __future__ import annotations

import asyncio

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import CourseRepository
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import GroundingChunk, QuestionPlan
from app.services import attribution
from app.services.question_service import (
    ContextRetrievalError,
    DocumentNotFoundError,
    QuestionService,
    serialized_context_chars,
)

VALID_SKILL = {
    "id": "chain-rule",
    "name": "Chain rule",
    "description": "Differentiate a composite function.",
    "difficulty_band": 0.5,
    "keywords": [],
    "question_forms": [],
}


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class StubQuestionWorkflow:
    def __init__(self, chunk_id="chunk_doc_1_00000", skills=None):
        self.chunk_id = chunk_id
        self.skills = skills if skills is not None else [VALID_SKILL]
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return QuestionPlan(
            prompt="Differentiate a nested function.",
            grounding_chunk_ids=[self.chunk_id],
            skills=self.skills,
        )


class StubRetriever:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or []
        self.error = error
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.chunks


def seeded_repo(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    chunks = [
        ChunkMetadata(
            chunk_id=f"chunk_doc_1_{index:05d}",
            document_id="doc_1",
            course_id="course_1",
            chunk_index=index,
            filename="lecture.txt",
            page=1,
            document_type=DocumentType.lecture,
            text=text,
        )
        for index, text in enumerate(("chain rule", "worked example"))
    ]
    repo.replace_document(
        document_id="doc_1",
        course_id="course_1",
        filename="lecture.txt",
        document_type=DocumentType.lecture,
        total_pages=1,
        chunks=chunks,
    )
    return repo


def service(repo, workflow, retriever, threshold, session):
    return QuestionService(
        repository=repo,
        workflow=workflow,
        retriever=retriever,
        full_context_max_chars=threshold,
        session=session,
    )


def test_serialized_context_counts_labels_and_text():
    chunks = [GroundingChunk(chunk_id="chunk_1", page=1, text="abc")]
    assert serialized_context_chars(chunks) == len("chunk_1") + 3 + 32


def test_small_documents_send_all_chunks_and_bypass_retrieval(tmp_path, session):
    repo = seeded_repo(tmp_path)
    workflow = StubQuestionWorkflow()
    retriever = StubRetriever(error=AssertionError("retrieval should be bypassed"))
    generated = asyncio.run(
        service(repo, workflow, retriever, 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="A conceptual question",
        )
    )
    assert generated.prompt == "Differentiate a nested function."
    assert retriever.calls == []
    assert len(workflow.calls[0]["chunks"]) == 2
    assert workflow.calls[0]["question_request"] == "A conceptual question"


def test_large_documents_retrieve_ranked_sqlite_context(tmp_path, session):
    repo = seeded_repo(tmp_path)
    selected = GroundingChunk(
        chunk_id="chunk_doc_1_00001", page=1, text="worked example"
    )
    workflow = StubQuestionWorkflow(chunk_id=selected.chunk_id)
    retriever = StubRetriever([selected])
    generated = asyncio.run(
        service(repo, workflow, retriever, 1, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="A difficult applied question",
        )
    )
    assert retriever.calls == [{
        "query": "A difficult applied question",
        "course_id": "course_1",
        "document_id": "doc_1",
        "top_k": 12,
    }]
    assert workflow.calls[0]["chunks"] == [selected]
    grounded = repo.get_grounded_problem(course_id="course_1", problem_id=generated.id)
    assert grounded is not None
    assert [chunk.chunk_id for chunk in grounded.chunks] == [selected.chunk_id]


def test_empty_or_failed_large_document_retrieval_fails_closed(tmp_path, session):
    repo = seeded_repo(tmp_path)
    for retriever in (StubRetriever(), StubRetriever(error=RuntimeError("secret"))):
        with pytest.raises(ContextRetrievalError):
            asyncio.run(
                service(repo, StubQuestionWorkflow(), retriever, 1, session).generate(
                    course_id="course_1",
                    document_id="doc_1",
                    question_request="Question",
                )
            )


def test_generation_rejects_a_document_from_another_course(tmp_path, session):
    repo = seeded_repo(tmp_path)
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(
            service(repo, StubQuestionWorkflow(), StubRetriever(), 10_000, session).generate(
                course_id="wrong_course",
                document_id="doc_1",
                question_request="Question",
            )
        )


def _existing_skill(session, skill_id, name="Existing"):
    session.add(
        Skill(id=skill_id, course_id="course_1", name=name, description="d",
              difficulty_band=0.5, origin=SkillOrigin.GENERATED)
    )
    session.commit()


def test_generation_attributes_the_problem_to_an_existing_skill(tmp_path, session):
    _existing_skill(session, "course_1.chain-rule", name="Chain rule")
    repo = seeded_repo(tmp_path)
    workflow = StubQuestionWorkflow(skills=[VALID_SKILL])
    generated = asyncio.run(
        service(repo, workflow, StubRetriever(), 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="Conceptual",
        )
    )
    assert attribution.get_problem_skills(session, generated.id) == ["course_1.chain-rule"]


def test_generation_identifies_a_new_topic_via_the_piggyback(tmp_path, session):
    """The model naming a topic the course lacks creates it, through the same
    build_taxonomy path every other topic source uses."""
    repo = seeded_repo(tmp_path)
    workflow = StubQuestionWorkflow(skills=[VALID_SKILL])
    generated = asyncio.run(
        service(repo, workflow, StubRetriever(), 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="Conceptual",
            required_skill_id=None,
        )
    )

    created = session.get(Skill, "course_1.chain-rule")
    assert created is not None
    assert created.origin == SkillOrigin.GENERATED
    assert attribution.get_problem_skills(session, generated.id) == ["course_1.chain-rule"]


def test_repeated_identification_of_the_same_topic_does_not_duplicate_it(tmp_path, session):
    repo = seeded_repo(tmp_path)
    for _ in range(3):
        asyncio.run(
            service(
                repo, StubQuestionWorkflow(skills=[VALID_SKILL]), StubRetriever(),
                10_000, session,
            ).generate(
                course_id="course_1", document_id="doc_1", question_request="Conceptual",
            )
        )

    matches = session.exec(
        select(Skill).where(Skill.course_id == "course_1", Skill.id == "course_1.chain-rule")
    ).all()
    assert len(matches) == 1


def test_a_differently_worded_name_resolves_to_the_same_topic(tmp_path, session):
    """The canonical-key check: "The Chain Rule" and "chain rule" are the
    same topic even though normalize_slug alone would treat them as two
    different ids."""
    _existing_skill(session, "course_1.chain-rule", name="Chain rule")
    repo = seeded_repo(tmp_path)
    reworded = {**VALID_SKILL, "id": "the-chain-rule", "name": "The Chain Rule"}
    generated = asyncio.run(
        service(
            repo, StubQuestionWorkflow(skills=[reworded]), StubRetriever(), 10_000, session
        ).generate(
            course_id="course_1", document_id="doc_1", question_request="Conceptual",
        )
    )
    assert attribution.get_problem_skills(session, generated.id) == ["course_1.chain-rule"]
    assert session.get(Skill, "course_1.the-chain-rule") is None


def test_generation_attributes_every_existing_skill_the_model_names(tmp_path, session):
    _existing_skill(session, "course_1.chain-rule", name="Chain rule")
    _existing_skill(session, "course_1.product-rule", name="Product rule")
    repo = seeded_repo(tmp_path)
    second = {**VALID_SKILL, "id": "product-rule", "name": "Product rule"}
    workflow = StubQuestionWorkflow(skills=[VALID_SKILL, second])
    generated = asyncio.run(
        service(repo, workflow, StubRetriever(), 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="Conceptual",
        )
    )
    assert set(attribution.get_problem_skills(session, generated.id)) == {
        "course_1.chain-rule",
        "course_1.product-rule",
    }


def test_generation_always_includes_the_required_skill_even_if_the_model_misses_it(
    tmp_path, session
):
    _existing_skill(session, "course_1.selected", name="Selected")
    repo = seeded_repo(tmp_path)
    workflow = StubQuestionWorkflow(skills=[VALID_SKILL])
    generated = asyncio.run(
        service(repo, workflow, StubRetriever(), 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="Conceptual",
            required_skill_id="course_1.selected",
        )
    )
    attributed = set(attribution.get_problem_skills(session, generated.id))
    assert "course_1.selected" in attributed
    assert "course_1.chain-rule" in attributed  # the model's own read, additive


def test_generation_offers_existing_skills_to_the_workflow(tmp_path, session):
    repo = seeded_repo(tmp_path)
    session.add(
        Skill(id="course_1.root", course_id="course_1", name="Root", description="d",
              difficulty_band=0.2, origin=SkillOrigin.SEED)
    )
    session.commit()
    workflow = StubQuestionWorkflow()
    asyncio.run(
        service(repo, workflow, StubRetriever(), 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="Conceptual",
        )
    )
    assert {"id": "course_1.root", "name": "Root"} in workflow.calls[0]["existing_skills"]


def test_generation_never_overwrites_a_seed_skill(tmp_path, session):
    repo = seeded_repo(tmp_path)
    session.add(
        Skill(id="course_1.chain-rule", course_id="course_1", name="Authored",
              description="seeded", difficulty_band=0.3, origin=SkillOrigin.SEED)
    )
    session.commit()
    workflow = StubQuestionWorkflow(skills=[VALID_SKILL])  # same id, different content
    generated = asyncio.run(
        service(repo, workflow, StubRetriever(), 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="Conceptual",
        )
    )
    # The problem is still attributed to the id, but the seed skill's own
    # fields are untouched.
    assert "course_1.chain-rule" in attribution.get_problem_skills(session, generated.id)
    untouched = session.get(Skill, "course_1.chain-rule")
    assert untouched.name == "Authored"
    assert untouched.origin == SkillOrigin.SEED


def test_a_malformed_skill_batch_does_not_fail_the_problem_request(tmp_path, session):
    """A taxonomy write is a side effect of generation, not the request.

    The student asked for a problem. A model returning a batch that fails
    validation -- here two entries that normalize to the same id -- must
    cost them the skill attribution the model proposed, not the problem.
    """
    _existing_skill(session, "course_1.seeded", name="Seeded")
    repo = seeded_repo(tmp_path)
    colliding = {**VALID_SKILL, "id": "same-name", "name": "Same Name"}
    also_colliding = {**VALID_SKILL, "id": "same-name", "name": "Same Name Again"}
    workflow = StubQuestionWorkflow(skills=[colliding, also_colliding])

    generated = asyncio.run(
        service(repo, workflow, StubRetriever(), 10_000, session).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="Conceptual",
            required_skill_id="course_1.seeded",
        )
    )

    assert generated.prompt
    assert attribution.get_problem_skills(session, generated.id) == ["course_1.seeded"]
    assert session.get(Skill, "course_1.same-name") is None
