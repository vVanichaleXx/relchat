from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationFixture:
    fixture_id: str
    context: str
    constraints: tuple[str, ...]


OFFLINE_EVALUATION_FIXTURES: dict[str, EvaluationFixture] = {
    "balanced_healthy_friendship": EvaluationFixture(
        "balanced_healthy_friendship",
        "friendship",
        ("no_high_score_from_volume_only", "mutual_interest_language", "no_diagnosis", "distinctive_story_arc", "no_generic_filler"),
    ),
    "playful_sarcastic_friendship": EvaluationFixture(
        "playful_sarcastic_friendship",
        "friendship",
        ("sarcasm_available", "playful_not_aggression", "no_negative_penalty_solely_for_sarcasm", "humour_direction_specific"),
    ),
    "dismissive_sarcasm": EvaluationFixture(
        "dismissive_sarcasm",
        "mixed",
        ("sarcasm_available", "dismissive_direction", "impact_on_topic_completion", "evidence_shown"),
    ),
    "explicit_aggression": EvaluationFixture(
        "explicit_aggression",
        "mixed",
        ("aggression_available", "direct_wording", "problem_severity", "no_false_neutralization"),
    ),
    "ordinary_assertive_disagreement": EvaluationFixture(
        "ordinary_assertive_disagreement",
        "mixed",
        ("assertiveness_not_hostility", "aggression_available_as_assertiveness", "no_personal_insult"),
    ),
    "repeated_pressure_after_refusal": EvaluationFixture(
        "repeated_pressure_after_refusal",
        "mixed",
        ("pressure_available", "requires_refusal_sequence", "advice_reduce_pressure"),
    ),
    "legitimate_persuasion": EvaluationFixture(
        "legitimate_persuasion",
        "work",
        ("persuasion_available", "not_manipulation_without_unfair_choice_restriction", "transparent_reasoning"),
    ),
    "ambiguous_manipulation_candidate": EvaluationFixture(
        "ambiguous_manipulation_candidate",
        "mixed",
        ("ambiguous_or_insufficient", "alternative_explanation_required", "no_confident_manipulation_claim"),
    ),
    "possible_mutual_romantic_interest": EvaluationFixture(
        "possible_mutual_romantic_interest",
        "romantic",
        ("possible_interest_available", "probabilistic_wording", "no_proven_feelings_claim"),
    ),
    "one_sided_romantic_effort": EvaluationFixture(
        "one_sided_romantic_effort",
        "romantic",
        ("effort_imbalance", "possible_interest_may_be_ambiguous", "no_gender_stereotype"),
    ),
    "work_task_confusion": EvaluationFixture(
        "work_task_confusion",
        "work",
        ("efficiency_language", "no_attraction_language", "task_clarity_advice", "work_specific_fingerprint"),
    ),
    "supportive_family_conversation": EvaluationFixture(
        "supportive_family_conversation",
        "family",
        ("support_respect_language", "no_diagnosis", "repair_or_acknowledgement_if_supported"),
    ),
    "conflict_followed_by_repair": EvaluationFixture(
        "conflict_followed_by_repair",
        "mixed",
        ("conflict_not_automatically_aggression", "repair_attempt_visible", "timeline_event_allowed"),
    ),
    "active_but_superficial": EvaluationFixture(
        "active_but_superficial",
        "unknown",
        ("no_high_score_from_volume_only", "local_mode_limits", "neutral_limited_or_calm", "balance_not_depth_explanation"),
    ),
    "short_insufficient_data_chat": EvaluationFixture(
        "short_insufficient_data_chat",
        "unknown",
        ("insufficient_data", "no_empty_sections", "no_false_zero_risk"),
    ),
    "group_chat": EvaluationFixture(
        "group_chat",
        "group_social",
        ("activity_coordination", "no_two_person_relationship_score", "no_raw_text"),
    ),
    "channel": EvaluationFixture(
        "channel",
        "channel_or_broadcast",
        ("broadcast_activity", "no_two_person_relationship_score", "no_possible_interest"),
    ),
}


def fixture_constraints(fixture_id: str) -> tuple[str, ...]:
    return OFFLINE_EVALUATION_FIXTURES[fixture_id].constraints
