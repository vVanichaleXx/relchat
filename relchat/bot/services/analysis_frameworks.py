from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisFramework:
    framework_id: str
    supported_contexts: tuple[str, ...]
    dimensions: tuple[str, ...]
    evidence_rules: tuple[str, ...]
    interpretation_rules: tuple[str, ...]
    advice_rules: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    localization_keys: dict[str, str]
    evaluation_fixture_tags: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "framework_id": self.framework_id,
            "supported_contexts": list(self.supported_contexts),
            "dimensions": list(self.dimensions),
            "evidence_rules": list(self.evidence_rules),
            "interpretation_rules": list(self.interpretation_rules),
            "advice_rules": list(self.advice_rules),
            "forbidden_actions": list(self.forbidden_actions),
            "localization_keys": dict(self.localization_keys),
            "evaluation_fixture_tags": list(self.evaluation_fixture_tags),
        }


REGISTRY: dict[str, AnalysisFramework] = {
    "context_aware_core": AnalysisFramework(
        framework_id="context_aware_core",
        supported_contexts=(
            "romantic",
            "friendship",
            "family",
            "work",
            "customer_or_service",
            "group_social",
            "channel_or_broadcast",
            "mixed",
            "unknown",
        ),
        dimensions=(
            "reciprocity",
            "directness",
            "question_engagement",
            "topic_continuation",
            "planning_clarity",
            "boundary_respect",
            "repair",
            "sarcasm",
            "aggression",
            "influence",
            "possible_interest",
        ),
        evidence_rules=(
            "explicit wording can support high confidence",
            "several independent indicators can support medium/high confidence",
            "one isolated ambiguous phrase cannot support a strong interpretation",
            "semantic findings must include observation, interpretation, alternatives, confidence, limitations, and scope",
        ),
        interpretation_rules=(
            "separate directly observed behavior from interpretation",
            "scope conclusions to the selected period and chat",
            "do not infer context from gender, names, or stereotypes",
            "do not convert possible feelings into proven facts",
            "distinguish persuasion, pressure, and manipulative patterns",
        ),
        advice_rules=(
            "link advice to the strongest supported evidence",
            "prefer clarity, boundaries, de-escalation, transparent persuasion, repair, and direct invitations",
        ),
        forbidden_actions=(
            "deception",
            "coercion",
            "humiliation",
            "boundary violations",
            "jealousy induction",
            "threats",
            "emotional punishment",
        ),
        localization_keys={
            "title": "ai_communication_analysis",
            "why": "why_conclusion_title",
        },
        evaluation_fixture_tags=("core", "v12"),
    ),
    "workplace_communication": AnalysisFramework(
        framework_id="workplace_communication",
        supported_contexts=("work", "customer_or_service"),
        dimensions=(
            "clarity",
            "task_ownership",
            "responsiveness",
            "commitments",
            "planning_clarity",
            "escalation",
            "professional_tone",
            "blocking_behavior",
        ),
        evidence_rules=("use work-topic signals, explicit commitments, unanswered work questions, and repeated clarification loops",),
        interpretation_rules=("do not use romantic-interest language in work contexts",),
        advice_rules=("state task, owner, expected result, and deadline",),
        forbidden_actions=("coercion", "humiliation", "threats"),
        localization_keys={"title": "context_work"},
        evaluation_fixture_tags=("work", "service"),
    ),
    "romantic_communication": AnalysisFramework(
        framework_id="romantic_communication",
        supported_contexts=("romantic", "mixed"),
        dimensions=(
            "reciprocal_initiative",
            "emotional_engagement",
            "personal_questions",
            "planning_cooperation",
            "affectionate_language",
            "directness",
            "pressure",
            "possible_interest",
        ),
        evidence_rules=("use reciprocal initiative, personal topic continuation, explicit affection, and concrete planning; never use gender",),
        interpretation_rules=("possible interest remains probabilistic and cannot prove feelings",),
        advice_rules=("use clear interest, self-respect, boundaries, and direct invitations",),
        forbidden_actions=("jealousy induction", "making someone chase", "emotional punishment", "deception"),
        localization_keys={"title": "context_romantic"},
        evaluation_fixture_tags=("romantic", "interest"),
    ),
}


def get_framework(framework_id: str) -> AnalysisFramework:
    return REGISTRY.get(framework_id, REGISTRY["context_aware_core"])


def frameworks_for_context(context_category: str | None) -> list[AnalysisFramework]:
    category = context_category or "unknown"
    matches = [framework for framework in REGISTRY.values() if category in framework.supported_contexts]
    return matches or [REGISTRY["context_aware_core"]]


def framework_payload_for_context(context_category: str | None) -> dict[str, Any]:
    frameworks = frameworks_for_context(context_category)
    primary = frameworks[0]
    return {
        "primary": primary.to_payload(),
        "available_framework_ids": [framework.framework_id for framework in frameworks],
    }
