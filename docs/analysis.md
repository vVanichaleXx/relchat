# Communication Analysis

RelChat analysis is built around observable behavior. It can interpret indirect meaning only when the available evidence supports that interpretation.

## Observation Versus Interpretation

Every important semantic finding separates:

- observation: what is directly visible in messages, metrics, events, or comparisons
- interpretation: what the observed pattern may mean in the selected context
- advice: what practical next step follows from the strongest evidence

Findings include confidence, evidence count, evidence types, period scope, context scope, alternatives when ambiguity matters, and limitations.

## Three Interpretation Levels

- Directly observed: explicit wording or visible behavior, such as an insult, refusal, threat, stated affection, direct invitation, ultimatum, or repeated command.
- Strongly supported interpretation: several independent indicators or repeated comparable episodes point to the same interpretation.
- Unsupported or ambiguous: evidence is weak, contradictory, insufficient, or not applicable.

Unsupported dimensions must not render as false zeroes. Use `insufficient_data`, `ambiguous`, or `not_applicable`.

Each semantic result carries source metadata:

- `explicit_rule`: direct wording or explicit visible behavior
- `local_pattern`: local structural or keyword pattern, usually suggestive
- `ai_interpretation`: contextual text interpretation after consent
- `historical_pattern`: recurring memory or comparable-period evidence
- `combined`: multiple source types support the same conclusion

It also carries `semantic_depth`: `direct`, `suggestive`, or `contextual`.
Local-only suggestive evidence must use cautious wording such as “may look like”
or “there are signs of.” It must not state contextual intent as fact.

## Semantic Analysis

Sarcasm is analyzed when content and context support it. Playful shared sarcasm may support rapport. Defensive sarcasm may avoid direct discussion. Dismissive sarcasm can invalidate a question or close a serious topic. Hostile sarcasm can function as indirect aggression.

Aggression analysis differentiates irritation, frustration, assertiveness, conflict, verbal aggression, hostility, and mixed signals. A disagreement or clear boundary is not automatically aggression.

Influence analysis differentiates persuasion, pressure, possible manipulation, and clear manipulative patterns. Persuasion can preserve choice. Pressure makes refusal harder or ignores reluctance. Manipulative patterns rely on concealed intent, emotional leverage, distortion, or unfair restriction of choice. Ordinary requests are not manipulation.

Possible interest analysis is allowed in relevant contexts, but remains probabilistic. Reciprocal initiative, personal questions, emotional disclosure, affectionate language, topic continuation, and concrete planning can support possible interest. RelChat must not say feelings or intentions are proven.

## Context Frameworks

The framework registry lets future modules define `framework_id`, supported contexts, dimensions, evidence rules, interpretation rules, advice rules, forbidden actions, localization keys, and evaluation fixture tags. Current frameworks cover the context-aware core, workplace communication, and romantic communication. Future tutorial modules should register a framework instead of rewriting the report flow or appending everything to one prompt.

## Personal Profile

The personal communication profile describes how the authenticated user communicates with one person in the selected chat and period. It may cover warmth, directness, initiative, responsiveness, questions, topic continuation, detail, acknowledgement, humour, sarcasm, planning, conflict, repair, pressure risk, persuasion, and boundaries. It is not a permanent personality label.

Cross-chat profile uses supported aggregate snapshots only. It never exposes raw text from one chat in another chat and never ranks people.

## Story, Evidence, Memory, Timeline

The story builder explains what is happening, what mainly drives the interaction, how the user communicates, how the other participant responds, what strengthens the dialogue, what creates friction, semantic dynamics, recurrence, and uncertainty. It must not invent findings.

“Why this conclusion?” shows observation, interpretation, supporting evidence, alternatives, confidence, and limitations for each important finding. It does not show raw message text.

Long-term memory promotes only recurring validated observations, explicit high-confidence behavior with enough coverage, user-confirmed observations, or patterns supported by comparable periods. Later contradictory evidence weakens or deactivates memory. Memory stores no raw messages and no permanent personality labels.

The communication timeline may show safe changes such as long pauses, resumed contact, initiative shifts, sarcasm direction changes, pressure patterns, repair attempts, or possible-interest signals. It must not turn interpretations into certain relationship milestones.

## Local Versus AI Capability

Local structural mode can analyze message balance, initiation, response timing, question candidates, plan candidates, pauses, repeated sequences, and explicit keyword patterns where reliable. It must not confidently infer complex sarcasm, manipulation, or attraction from metadata alone.

AI text interpretation may analyze semantic sarcasm, indirect aggression, conversational pressure, persuasive framing, possible emotional interest, dismissiveness, contextual humour, and indirect meaning only after consent and with minimized anonymized selected-period content.

## V12.1 Report Quality Rules

Finding-to-advice routing is typed. A recommendation must reference a supported
finding when one exists, and its category must match the finding type. Sarcasm
uses advice about returning to the direct question. Explicit aggression uses
boundary advice. Unanswered questions use one-question advice. Work ambiguity
uses task, owner, result, and deadline advice.

Participant sections require asymmetric evidence. If both sides are similar by
volume or average length, render one participation-balance statement and explain
what it does and does not prove. Do not duplicate the same sentence under both
participants.

Strengths require meaningful behavior such as reciprocal initiation, consistent
responses, answered questions, concrete plans, repair after conflict, emotional
acknowledgement, topic continuation, or balanced effort over several periods.
Message presence and equal volume are not strengths.

Questions are rendered as normalized rates with denominators. Raw question-mark
candidate counts are not user-facing evidence in full-history reports.

Large full-history reports are segmented into bounded windows and should surface
current picture, long-term pattern, recent change, supported friction, meaningful
strength if present, recommendation, and limitations.

Analysis jobs classify failures into safe categories and retry only transient
ones. Telegram auth, revoked consent, validation errors, deleted or forbidden
chats, and cancellation are not retried. Users see localized category messages
and retry buttons, not stack traces or exception class names.

Telethon clients are owned by the importer call that creates them and are
disconnected in `finally`. Analysis-owned background tasks are cancelled and
awaited during bot shutdown.

## V12.2 Evidence Integrity

V12.2 adds canonical validated findings as the single source of truth for
semantic/report integrity. Score explanations, advice, adaptive tone, memory,
timeline events, and visible evidence screens must consume the same finding
objects. A score contributor cannot mention hostility, aggression, devaluation,
manipulation, or dismissive sarcasm unless a matching validated finding exists,
is available, has enough evidence, and can be explained safely.

Canonical findings carry `finding_id`, `finding_type`, participant scope,
status, severity, semantic source/depth, confidence, evidence count and IDs,
score effect, advice category, memory eligibility, summary key, and limitations.
Ambiguous or unavailable findings contribute zero or only a tiny capped effect.
They cannot produce serious tone, major score penalties, memory promotion, or
aggression advice.

Sarcasm is not automatically escalated into hostility. Dismissive sarcasm may
affect directness, answer clarity, topic completion, or respect when evidence is
available, but hostility requires hostile sarcasm evidence or a separate
aggression finding. Threat wording in advice requires explicit threat evidence.

Work reports use a work-effectiveness framework. They focus on task clarity,
owner clarity, deadline clarity, actionable answers, repeated clarification,
decision completion, follow-through, status quality, response consistency, and
whether tone interferes with execution. Regular alternating replies count only
as a small structural positive unless they move work forward. Message balance is
informational and should not drive a high or very low work score.

The final report-consistency validator removes unsupported contradictions before
rendering or persistence. It downgrades unsupported certainty, drops aggression
advice without aggression evidence, filters score contributors that do not point
to validated findings, prevents serious tone from ambiguous findings, and
deduplicates repeated facts such as “no meaningful change.”

If an AI semantic call fails and local fallback is used, the fallback report is
rebuilt only from local validated findings. Partial or invalid provider
semantics must not leak into the local score, advice, or score explanation.

## V12.3 Individualized Reports

V12.3 adds a deterministic conversation fingerprint before story generation.
The fingerprint summarizes the selected context, period scope, participant
mapping confidence, dominant findings, participant asymmetries, recurring
patterns, topic differences, recent changes, safe cross-chat aggregate
features, uncertainties, and evidence coverage. It is built only from validated
findings and safe metrics; it does not store raw messages or personalized prose
as long-term personality memory.

The pattern selector ranks candidate observations by evidence strength, context
relevance, recurrence, recent importance, participant or period comparison,
topic specificity, practical usefulness, and independence from already selected
findings. It penalizes generic facts such as equal message volume, basic
participation, raw counts without interpretation, weak local semantic hints, and
repeated statements. Equivalent evidence produces deterministic output; reports
vary because their selected findings, context, asymmetries, and trends differ,
not because of random synonym selection.

The individualized story builder uses the selected patterns to create a compact
arc:

- overall picture
- distinctive dynamic
- how the authenticated user communicates in this chat and period
- how the other participant responds when there is asymmetric evidence
- main supported strength, only when meaningful
- main friction, only when supported
- recent or historical note
- practical next step or explicit advice omission
- important uncertainty

The report generator should omit generic filler such as “communication contains
patterns,” “visible data show,” or “clear communication is important.” When
there is enough evidence, a private-chat report should contain at least two
specific, non-duplicated observations. When evidence is weak, the report should
be shorter and state the limitation rather than inventing personalization.

Personalized feedback is tied to the strongest actionable validated finding. It
may recommend clearer directness, request placement, de-escalation, returning to
a question after sarcasm, pressure reduction, boundary setting, or task clarity
only when the evidence supports that route. If the user's wording is already
reasonable or no actionable problem is supported, advice may be omitted and the
report may say that no immediate communication change is visible.

Safe cross-chat personalization can compare compatible aggregate profile
snapshots, for example whether the user asks more follow-up questions here than
in similar contexts. It never exposes content from another chat, never ranks
people, and can be disabled by future settings without changing the report
architecture.

`specificity_validator.py` is the quality gate for non-template reports. It
checks evidence-linked observation count, participant-specific differences,
period/topic comparisons, prohibited generic phrases, semantic duplication,
advice specificity, context relevance, and uncertainty consistency. If a report
fails, the builder removes generic sections, reroutes or omits unsupported
advice, and shortens the report without inventing new facts.

## Report Integrity Rules

Participation is interpreted once per scope by `participation.py`. The neutral
range is explicit, so a period cannot be described as both balanced and
user-dominated unless the scopes differ. When full-history and recent-window
participation disagree, the report names both scopes.

Semantic composition is cleaned after report assembly. Repeated prefixes,
adjacent duplicate sentences, generic balanced-activity claims, and repeated
title/summary meaning are removed before output.

Visible influence wording is behavior-first. Internal categories may still
distinguish persuasion, pressure, possible manipulation, and clear manipulation,
but normal report prose prefers observable descriptions such as pressure through
obligation. Hidden intent is not claimed.

Advice alignment is enforced with `leading_finding_id` and `advice_target_id`.
The main recommendation must target the strongest actionable supported finding,
or be omitted when no useful action is supported.

## V13 Telegram Report Presentation

Telegram reports have two levels. Compact results are meant to be readable in a
short bot message. They show the chat title, one context/period metadata line,
score or local-mode state, the distinctive story or strongest supported
dynamic, the authenticated user's chat-specific pattern when supported, the
other participant's visible response only when asymmetric evidence exists, one
main friction or strength, one evidence-linked recommendation when useful, and
data/limitations once near the end.

Full analysis is opened from the compact result or Chat Home. It may include
evidence panels, score explanation, topic differences, period comparison,
history segmentation, memory, timeline, and limitations. The compact result
should not automatically dump the full report after every analysis.

Telegram formatting uses restrained hierarchy: bold titles and section
headings, short italic metadata lines, short paragraphs, and restrained emojis.
Navigation buttons may use icons for scanning; report body text should avoid an
emoji wall. Do not repeat period, message count, or confidence in multiple
sections. Do not render empty sections or technical metadata in the main report.

## Offline Evaluation Fixtures

Reusable fixtures describe constraints instead of exact wording. They cover healthy friendship, playful sarcasm, dismissive sarcasm, explicit aggression, assertive disagreement, repeated pressure, legitimate persuasion, ambiguous manipulation, mutual possible romantic interest, one-sided romantic effort, work-task confusion, supportive family conversation, conflict repair, active but superficial communication, short insufficient-data chat, groups, and channels.
