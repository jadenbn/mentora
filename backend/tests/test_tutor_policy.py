"""The deterministic safety policy.

Model output is untrusted. Everything the tutor draws passes through one pure
function first: plan in, plan out, no I/O and no request context. Keeping it
pure is what makes these rules cheap to state and impossible to bypass.
"""

from __future__ import annotations

from app.schemas.tutor import WorkStatus
from app.services.tutor_policy import MAX_ACTIONS, apply_safety_policy
from tests import factories as f


class TestUncertainWork:
    """When the canvas cannot be read, the tutor must not grade it."""

    def test_uncertain_work_is_never_marked_correct_or_incorrect(self):
        plan = f.plan(
            status=WorkStatus.uncertain,
            actions=[f.check_action(), f.cross_action(), f.text_action()],
        )
        result = apply_safety_policy(plan)
        assert f.action_types(result.canvas_actions) == ["text"]

    def test_uncertain_work_still_gets_a_way_forward(self):
        # Stripping the marks must not leave the student staring at nothing.
        plan = f.plan(status=WorkStatus.uncertain, actions=[f.check_action()])
        result = apply_safety_policy(plan)
        assert f.action_types(result.canvas_actions) == ["text"]
        assert result.canvas_actions[0].text

    def test_the_clarification_request_lands_on_the_canvas(self):
        plan = f.plan(status=WorkStatus.uncertain, actions=[])
        action = apply_safety_policy(plan).canvas_actions[0]
        assert 0 <= action.position.x <= 1
        assert 0 <= action.position.y <= 1

    def test_a_clarification_is_not_added_when_the_tutor_already_spoke(self):
        plan = f.plan(
            status=WorkStatus.uncertain,
            actions=[f.text_action(text="Which step did you mean?")],
        )
        result = apply_safety_policy(plan)
        assert len(result.canvas_actions) == 1
        assert result.canvas_actions[0].text == "Which step did you mean?"


class TestConfidentWork:
    def test_a_confident_plan_passes_through_untouched(self):
        plan = f.plan(
            status=WorkStatus.incorrect,
            actions=[f.cross_action(), f.text_action()],
        )
        result = apply_safety_policy(plan)
        assert f.action_types(result.canvas_actions) == ["cross", "text"]

    def test_marks_survive_on_every_non_uncertain_status(self):
        for status in (WorkStatus.correct, WorkStatus.incorrect, WorkStatus.partial):
            result = apply_safety_policy(f.plan(status=status, actions=[f.check_action()]))
            assert f.action_types(result.canvas_actions) == ["check"], status


class TestActionBudget:
    """A whiteboard covered in annotations is worse than no feedback."""

    def test_an_over_eager_plan_is_truncated_rather_than_rejected(self):
        # Truncating costs nothing; rejecting would spend a whole repair round
        # trip on an otherwise usable answer.
        plan = f.plan(actions=[f.circle_action() for _ in range(MAX_ACTIONS + 5)])
        result = apply_safety_policy(plan)
        assert len(result.canvas_actions) == MAX_ACTIONS

    def test_truncation_keeps_the_earliest_actions(self):
        actions = [f.text_action(text=f"step {i}") for i in range(MAX_ACTIONS + 3)]
        result = apply_safety_policy(f.plan(actions=actions))
        assert result.canvas_actions[0].text == "step 0"
        assert result.canvas_actions[-1].text == f"step {MAX_ACTIONS - 1}"

    def test_a_plan_within_budget_is_not_padded(self):
        result = apply_safety_policy(f.plan(actions=[f.text_action()]))
        assert len(result.canvas_actions) == 1


class TestPurity:
    def test_the_policy_does_not_mutate_the_plan_it_was_given(self):
        plan = f.plan(status=WorkStatus.uncertain, actions=[f.check_action()])
        before = f.action_types(plan.canvas_actions)
        apply_safety_policy(plan)
        assert f.action_types(plan.canvas_actions) == before

    def test_the_policy_preserves_the_summary(self):
        plan = f.plan(summary="You dropped the coefficient.")
        assert apply_safety_policy(plan).summary == "You dropped the coefficient."
