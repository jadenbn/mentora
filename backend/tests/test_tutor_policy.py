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
            actions=[f.check_action(), f.cross_action(), f.highlight_action()],
        )
        result = apply_safety_policy(plan)
        assert f.action_types(result.canvas_actions) == ["highlight"]
        assert "rewrite" in result.summary

    def test_uncertain_work_still_gets_a_way_forward(self):
        # Stripping the marks must not leave the student staring at nothing.
        plan = f.plan(status=WorkStatus.uncertain, actions=[f.check_action()])
        result = apply_safety_policy(plan)
        assert result.canvas_actions == []
        assert result.summary

    def test_the_clarification_request_lands_in_the_summary(self):
        plan = f.plan(status=WorkStatus.uncertain, actions=[])
        assert "rewrite" in apply_safety_policy(plan).summary

    def test_uncertainty_always_uses_a_safe_summary(self):
        plan = f.plan(
            status=WorkStatus.uncertain,
            actions=[f.highlight_action()],
            summary="Which step did you mean?",
        )
        result = apply_safety_policy(plan)
        assert len(result.canvas_actions) == 1
        assert "rewrite" in result.summary


class TestConfidentWork:
    def test_a_confident_plan_passes_through_untouched(self):
        plan = f.plan(
            status=WorkStatus.incorrect,
            actions=[f.cross_action(), f.highlight_action()],
        )
        result = apply_safety_policy(plan)
        assert f.action_types(result.canvas_actions) == ["cross", "highlight"]

    def test_marks_survive_where_the_tutor_is_still_grading(self):
        for status in (WorkStatus.incorrect, WorkStatus.partial):
            result = apply_safety_policy(f.plan(status=status, actions=[f.check_action()]))
            assert f.action_types(result.canvas_actions) == ["check"], status


class TestNamedUncertainty:
    """A named symbol beats a shrug: the tutor asks about the step it could
    not read, where it sits, instead of about the whole canvas."""

    def test_a_named_uncertainty_forces_the_uncertain_verdict(self):
        # The model cannot have graded a step it just said it could not read.
        plan = f.plan(status=WorkStatus.correct, uncertainties=[f.uncertainty()])
        assert apply_safety_policy(plan).status is WorkStatus.uncertain

    def test_the_summary_names_the_symbol_it_is_about(self):
        plan = f.plan(
            status=WorkStatus.partial,
            actions=[],
            uncertainties=[f.uncertainty(x=0.7, y=0.2)],
        )
        assert "rewrite" in apply_safety_policy(plan).summary

    def test_the_question_names_the_symbol(self):
        plan = f.plan(
            status=WorkStatus.partial,
            actions=[],
            uncertainties=[f.uncertainty(description="The exponent is unclear.")],
        )
        assert "exponent" in apply_safety_policy(plan).summary

    def test_marks_are_still_stripped_when_a_symbol_is_unreadable(self):
        plan = f.plan(
            status=WorkStatus.correct,
            actions=[f.check_action()],
            uncertainties=[f.uncertainty()],
        )
        assert "check" not in f.action_types(apply_safety_policy(plan).canvas_actions)

    def test_an_unnamed_uncertainty_still_asks_something(self):
        plan = f.plan(status=WorkStatus.uncertain, actions=[])
        assert apply_safety_policy(plan).summary


class TestCompletedWork:
    """Finished work must not be argued with."""

    def test_a_correct_verdict_keeps_at_most_one_check(self):
        plan = f.plan(status=WorkStatus.correct, actions=[f.check_action(), f.check_action()])
        result = apply_safety_policy(plan)
        assert f.action_types(result.canvas_actions).count("check") == 1

    def test_a_correct_verdict_drops_corrective_marks(self):
        # A contradictory planner must not turn a finished solution back into
        # an error, or the student is told they are wrong for being right.
        plan = f.plan(status=WorkStatus.correct, actions=[f.cross_action(), f.circle_action()])
        types = f.action_types(apply_safety_policy(plan).canvas_actions)
        assert "cross" not in types and "circle" not in types

    def test_completed_work_is_confirmed_in_words(self):
        plan = f.plan(status=WorkStatus.correct, actions=[], summary="Nicely done.")
        result = apply_safety_policy(plan)
        assert result.summary == "Nicely done."

    def test_a_correct_verdict_survives_as_correct(self):
        assert apply_safety_policy(f.plan(status=WorkStatus.correct)).status is WorkStatus.correct


class TestActionBudget:
    """A whiteboard covered in annotations is worse than no feedback."""

    def test_an_over_eager_plan_is_truncated_rather_than_rejected(self):
        # Truncating costs nothing; rejecting would spend a whole repair round
        # trip on an otherwise usable answer.
        plan = f.plan(actions=[f.circle_action() for _ in range(MAX_ACTIONS + 5)])
        result = apply_safety_policy(plan)
        assert len(result.canvas_actions) == MAX_ACTIONS

    def test_truncation_keeps_the_earliest_actions(self):
        actions = [f.circle_action() for _ in range(MAX_ACTIONS + 3)]
        result = apply_safety_policy(f.plan(actions=actions))
        assert len(result.canvas_actions) == MAX_ACTIONS

    def test_a_plan_within_budget_is_not_padded(self):
        result = apply_safety_policy(f.plan(actions=[f.highlight_action()]))
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
