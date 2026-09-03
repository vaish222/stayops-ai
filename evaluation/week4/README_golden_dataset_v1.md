# StayOps AI Golden Dataset v1

This is a 50-case Week 4 evaluation dataset for StayOps AI.

## Distribution
- 25 happy-path
- 15 edge
- 7 failure/resilience
- 3 adversarial/safety

Default reference date: `2026-09-02`.

## Source of truth
Labels were designed against `vaish222/stayops-ai` on `main`, using:
- `data/properties.json`
- `data/property_rules.json`
- `data/reservations.json`
- `data/guest_messages.json`
- `data/cleaning_schedule.json`
- `data/maintenance_tickets.json`

The dataset labels intended product behavior, not current baseline behavior.

## Important fields
- `required_specialists`: minimal specialists necessary for a good trajectory.
- `allowed_specialists`: specialists that may run without counting as unnecessary.
- `required_tools`: sources necessary to answer safely.
- `allowed_tools`: supporting reads that are acceptable.
- `minimum_required_facts`: fixture-backed facts that must be represented.
- `forbidden_claims`: unsupported or unsafe outputs/actions that must not occur.
- `human_review_required`: normative HITL expectation.
- `failure_injection`: deterministic failure plan for resilience cases.
- `failure_behavior`: expected retry, incomplete-analysis, partial-result, or fallback behavior.

## Suggested primary metrics
1. Operational decision / required-fact accuracy
2. Specialist trajectory precision and recall
3. HITL / escalation correctness
4. Safe failure recovery
5. p95 end-to-end latency

Hard guardrails:
- Unauthorized writes = 0
- Unsupported critical claims = 0

## Before freezing
Manually review policy-sensitive labels such as whether a vague readiness question should map to
`risk_assessment` or `turnover_operations`. Do not alter fixture facts or trajectory labels merely to
improve baseline scores.
