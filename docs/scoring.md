# Scoring And Context-Aware Analysis

RelChat scores visible communication behavior only. A score is not a measure of attraction, love, compatibility, mental health, truthfulness, or a participant's worth.

## Context Categories

Analysis starts with a context classification:

- romantic
- friendship
- family
- work
- customer_or_service
- group_social
- channel_or_broadcast
- mixed
- unknown

User-confirmed context is stored per `bot_user_id`, source, and chat. It overrides automatic classification until changed. Automatic classification may use saved category, chat type/title, deterministic topic signals, and the anonymized representative sample used for AI interpretation. It must not use gender, names, or stereotypes.

## Context Frameworks

Romantic analysis uses observable reciprocity, effort balance, emotional engagement, directness, planning cooperation, consistency, pressure, and avoidance of concrete answers. It must not promise attraction detection or recommend jealousy, intentional ignoring, push-pull games, emotional punishment, or making someone chase.

Work analysis uses clarity, responsiveness, task ownership, concrete commitments, unanswered work questions, professional tone, efficiency, planning, escalation, ambiguity, and blocking behavior. It must not use romantic-interest language.

Friendship, family, customer/service, group, and channel contexts use their own observable frameworks. Groups and channels avoid two-person relationship framing.

## Evidence Gates

Equal message volume does not prove strong communication. It shows activity balance only.

Score rules:

- message-volume balance can contribute no more than 15% of the positive score
- unavailable dimensions do not count as positive evidence
- unmeasured risk dimensions stay unavailable instead of becoming `0.0`
- shallow local metrics are capped
- deterministic metrics without text interpretation are capped
- sampled AI interpretation is capped unless coverage is high
- low context confidence caps score confidence
- a high score needs several independent supported dimensions

Suggested caps implemented in the current framework:

- shallow local metrics: maximum 6.5
- deterministic metrics without text interpretation: maximum 7.2
- sampled AI interpretation: maximum 8.5 unless coverage is high
- full/high-quality evidence: up to 10.0

## Local-Only Limitation

Local-only analysis sees structure: participation, session starts, response opportunities, unanswered-question candidates, plans, promises, and follow-up candidates. It does not understand the meaning of every reply. It should say this clearly and avoid strong positive conclusions unless multiple supported dimensions justify them.

## AI Interpretation

AI-enhanced analysis is optional and consent-gated. The AI receives minimized selected-period data, anonymized participant labels, deterministic metrics, event summaries, context classification, and coverage limits. The final score is still calculated locally.

The AI prompt requires direct, honest, evidence-based, context-aware, non-manipulative language. It forbids diagnoses, hidden-feeling certainty, invented excuses, gender-based classification, pickup tactics, and clinical authority claims.
