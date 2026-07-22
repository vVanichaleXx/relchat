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
- explicit supported semantic evidence can make sarcasm, hostility, dismissiveness, pressure, or respectfulness dimensions available
- ambiguous or unsupported semantic dimensions remain `ambiguous`, `insufficient_data`, or `not_applicable`; they do not become false zeroes

Suggested caps implemented in the current framework:

- shallow local metrics: maximum 6.4
- deterministic metrics without text interpretation: maximum 7.2
- sampled AI interpretation: maximum 8.5 unless coverage is high
- full/high-quality evidence: up to 10.0

The shallow local cap is intentionally below the “good” verdict threshold.
Balanced message volume plus shallow structural activity can produce a mixed or
insufficient result, but not a good or strong conclusion by itself.

Normal report views show a compact score explanation instead of formula
coefficients. The explanation lists positive contributors, negative
contributors, unavailable dimensions, confidence caps, semantic-mode caps, and
any historical adjustment. It also explains when volume balance did not raise
the score because volume alone is not reply quality.

## Local-Only Limitation

Local-only analysis sees structure: participation, session starts, response opportunities, filtered direct-question candidates, plans, promises, follow-up candidates, pauses, repeated sequences, and explicit keyword patterns where reliable. It can recognize directly observable signals such as explicit insults, threats, refusals, repeated urgent commands, explicit sarcasm markers, or clear pressure after refusal.

Local-only analysis does not understand complex semantic meaning from metadata alone. It must not confidently infer subtle sarcasm, indirect manipulation, attraction, hidden motive, or emotional warmth without explicit wording. Local semantic findings carry `source=local_pattern` and `semantic_depth=suggestive` unless direct wording or repeated independent evidence supports a stronger result. It should say this clearly and avoid strong positive conclusions unless multiple supported dimensions justify them.

Question metrics are normalized. Reports do not present raw question-mark totals for large histories; they show direct-question counts with text-message denominators, participant comparison, and filtered exclusions for URLs, code-like text, quotes, forwarded text, repeated punctuation, and rhetorical candidates.

## AI Interpretation

AI-enhanced analysis is optional and consent-gated. The AI receives minimized selected-period data, anonymized participant labels, deterministic metrics, event summaries, context classification, and coverage limits. The final score is still calculated locally.

The AI prompt requires direct, honest, evidence-based, context-aware language. It may analyze sarcasm, aggression, dismissiveness, pressure, persuasion, possible manipulation patterns, possible personal interest, flirtation, and indirect meaning when evidence supports it. It must separate observation from interpretation, include confidence, evidence count/type, scope, alternatives where useful, and limitations.

The AI prompt still forbids diagnoses, hidden-feeling certainty, invented excuses, gender-based classification, pickup tactics, deception, coercion, humiliation, threats, jealousy induction, emotional punishment, and clinical authority claims.

## Interpretation Levels

RelChat uses three interpretation levels:

- directly observed: explicit wording or visible behavior
- strongly supported interpretation: several independent indicators or repeated comparable episodes
- unsupported or ambiguous: weak, contradictory, insufficient, or not applicable evidence

High-confidence semantic interpretation generally requires explicit wording, several independent indicators, or repeated comparable episodes. One isolated ambiguous phrase should not produce a strong conclusion.

## Semantic Dimensions

Sarcasm is classified as unavailable, ambiguous, playful/bonding, defensive, dismissive, hostile, or mixed depending on evidence and context. Playful shared sarcasm is not automatically negative.

Aggression distinguishes irritation, frustration, assertiveness, conflict, verbal aggression, hostility, and mixed signals. Direct disagreement and assertive boundaries are not automatically hostility.

Influence distinguishes persuasion, pressure, possible manipulation, and clear manipulative patterns. Ordinary requests are not manipulation. Repeated requests after refusal, guilt induction, urgency pressure, false dilemmas, or responsibility reframing require evidence and alternatives.

Possible romantic or emotional interest remains probabilistic. It can be supported by reciprocal initiative, personal questions, disclosures, affectionate language, topic continuation, and concrete planning, but it never proves feelings or intentions.

## Long Histories

Full-history reports are segmented when the selected period exceeds configured
thresholds such as more than 1,500 messages, more than 90 days, or more than 30
visible sessions. Monthly windows are used for histories spanning multiple
months; activity windows are used for shorter dense histories. The window count
is bounded for performance.

Large reports prioritize the current picture, the full-history baseline, recent
change, the strongest recurring supported pattern, and the main recommendation.
They should not repeat the same fact in summary, findings, participant
sections, strengths, and advice.

## Canonical Finding Integrity

V12.2 requires negative score contributors to reference canonical validated
findings. Before a score explanation is shown or stored, each negative
contributor is checked against the finding set:

- the referenced `finding_id` must exist
- the finding must be `available`
- evidence count must be positive
- contributor severity cannot exceed finding severity
- local suggestive semantic findings are capped
- unavailable findings contribute exactly zero

Unsupported hostility, aggression, devaluation, manipulation, or disrespect is
removed from the score explanation. Ambiguous local sarcasm can be mentioned as
a limitation or cautious note, but it cannot create a hostility contributor or a
large penalty.

## Work Effectiveness Score

For `work` and future work-like contexts, the primary score is effectiveness,
not relationship quality. The work score prioritizes:

- clear task formulation
- owner/responsibility clarity
- deadline clarity
- actionable answers
- completed decisions
- follow-through signals
- repeated clarification loops
- unresolved actionable questions
- tone that interferes with task completion

Message balance has little or no direct effect. Regular alternating replies are
only a small positive unless the findings show that work decisions become
clearer or get completed. A low-volume chat with clear task, owner, result, and
deadline can score well; an active chat with vague outcomes should not be called
strong.

Local work scoring remains capped because local analysis cannot verify the
meaning of every decision. If task clarity or decision completion cannot be
measured, the report should explain the limitation instead of inventing a very
low or high score.

## Score/Finding/Story Alignment

V12.3 keeps the v12.2 canonical finding contract and adds individualized
selection on top of it. A high-value report pattern must come from the same
validated evidence that can also appear in score contributors, advice routing,
and “Why this conclusion?” panels. The pattern selector may use participant
asymmetry, topic differences, recent-vs-baseline changes, recurrence, or safe
cross-chat aggregates, but it cannot turn basic message presence into a
strength.

Score explanations remain compact and do not expose formulas. They should align
with the report story: if the story says task clarity is the main issue, the
score explanation should not mention unrelated hostility or devaluation. If the
story says the report is limited to local structure, the score confidence and
cap must reflect that limitation.

Personalized recommendations are not score contributors. They are generated
only after selecting the strongest actionable finding. When no actionable
finding is supported, the report can omit advice; this avoids lowering the
score or blaming the user merely to fill an advice section.

V12.3 report-quality gating also blocks overconfident point scores when too few
independent communication dimensions are supported. Message balance is not an
independent quality dimension by itself. A single sarcasm, hostility, or
pressure detector cannot alone push a structurally regular chat below 4/10; the
score is either offset by supported positive evidence or replaced by an
insufficient-evidence state.
